"""Closed V1 capability adapter: user notices, dry-run audit, and release only."""

from __future__ import annotations

import ctypes
import logging
import os
import threading
from dataclasses import dataclass
from typing import Protocol

from .models import AckStatus, Command, CommandType

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    def notify(self, title: str, message: str, topmost: bool = False) -> None: ...


class WindowsMessageNotifier:
    """Show a non-authoritative message without invoking a shell."""

    def notify(self, title: str, message: str, topmost: bool = False) -> None:
        if os.name != "nt":
            logger.info("%s: %s", title, message)
            return

        flags = 0x00000040  # MB_ICONINFORMATION
        if topmost:
            flags |= 0x00040000  # MB_TOPMOST

        def show() -> None:
            try:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.MessageBoxW(None, message, title, flags)
            except OSError:
                logger.warning("Unable to display Windows notification", exc_info=True)

        # MessageBox is blocking. Isolating it in a daemon thread keeps heartbeat and
        # Emergency Release available while the user decides when to dismiss it.
        threading.Thread(target=show, name="lifeos-notification", daemon=True).start()


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    status: AckStatus
    reason_codes: list[str]
    details: dict[str, object]


class SafeCapabilityAdapter:
    """The complete V1 capability surface; intentionally no destructive method."""

    def __init__(self, notifier: Notifier | None = None) -> None:
        self._notifier = notifier or WindowsMessageNotifier()
        self.would_block_audit: list[dict[str, object]] = []
        self.simulated_restrictions: set[str] = set()

    def execute(self, command: Command) -> CapabilityResult:
        if command.command_type == CommandType.SHOW_NOTIFICATION:
            message = command.payload.message or "Return to the current task."
            self._notifier.notify("LifeOS", message)
            return CapabilityResult(
                AckStatus.EXECUTED,
                command.reason_codes,
                {"outcome": "NOTIFIED", "notified": True},
            )

        if command.command_type == CommandType.SHOW_CONFIRMATION:
            choices = " / ".join(command.payload.choices or [])
            message = command.payload.message or "LifeOS check-in"
            if choices:
                message = f"{message}\n\n{choices}"
            self._notifier.notify("LifeOS check-in", message, topmost=True)
            return CapabilityResult(
                AckStatus.EXECUTED,
                command.reason_codes,
                {"outcome": "CONFIRMATION_SHOWN", "notified": True},
            )

        if command.command_type == CommandType.WOULD_BLOCK:
            entry: dict[str, object] = {
                "applications": list(command.payload.applications or []),
                "duration_seconds": command.payload.duration_seconds or 0,
                "restriction_id": (
                    str(command.payload.restriction_id) if command.payload.restriction_id else None
                ),
            }
            self.would_block_audit.append(entry)
            application_count = len(command.payload.applications or [])
            logger.info("Dry-run WOULD_BLOCK recorded for %d application(s)", application_count)
            return CapabilityResult(
                AckStatus.EXECUTED,
                ["WOULD_BLOCK_ONLY", "DRY_RUN_REQUIRED"],
                {"outcome": "WOULD_BLOCK", **entry},
            )

        if command.command_type == CommandType.RELEASE_ALL:
            return self.release_all()

        # START_BLOCK and ENTER_RECOVERY are frozen contract values for V2. V1 has
        # no implementation path for either, even if a malformed Core sends one.
        return CapabilityResult(
            AckStatus.REJECTED,
            ["WOULD_BLOCK_ONLY"],
            {"unsupported_command_type": command.command_type.value},
        )

    def release_all(self) -> CapabilityResult:
        released = len(self.simulated_restrictions)
        self.simulated_restrictions.clear()
        return CapabilityResult(
            AckStatus.EXECUTED,
            ["EMERGENCY_RELEASED"],
            {"outcome": "RELEASED", "released_count": released},
        )
