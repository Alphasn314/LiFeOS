"""Agent-side command guard and idempotent execution."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

from .capabilities import CapabilityResult, SafeCapabilityAdapter
from .clock import Clock
from .models import (
    AckStatus,
    Command,
    CommandAck,
    CommandType,
    DeviceRole,
    RiskLevel,
    RoleLease,
)
from .queue import SQLiteAgentStore


class CommandProcessor:
    def __init__(
        self,
        device_id: uuid.UUID,
        store: SQLiteAgentStore,
        adapter: SafeCapabilityAdapter,
        clock: Clock,
        clock_skew_seconds: float = 0,
    ) -> None:
        self._device_id = device_id
        self._store = store
        self._adapter = adapter
        self._clock = clock
        self._clock_skew = timedelta(seconds=clock_skew_seconds)
        self._lock = asyncio.Lock()

    async def process(
        self,
        command: Command,
        current_state_version: int | None,
        core_reachable: bool,
        leases: list[RoleLease] | None = None,
    ) -> CommandAck:
        async with self._lock:
            duplicate = self._store.processed_ack(str(command.command_id), command.idempotency_key)
            if duplicate is not None:
                return duplicate

            rejection = self._validate(
                command,
                current_state_version=current_state_version,
                core_reachable=core_reachable,
                leases=leases or [],
            )
            result = rejection or self._adapter.execute(command)
            ack = CommandAck(
                ack_id=uuid.uuid4(),
                command_id=command.command_id,
                device_id=self._device_id,
                status=result.status,
                acknowledged_at=self._clock.now(),
                observed_state_version=current_state_version,
                idempotency_key=f"ack:{command.command_id}",
                details=result.details,
                reason_codes=result.reason_codes,
            )
            return self._store.record_processed(ack, command.idempotency_key)

    def local_emergency_release(self) -> CapabilityResult:
        """Fail-open local path that cannot be blocked by Core/network availability."""

        return self._adapter.release_all()

    def _validate(
        self,
        command: Command,
        current_state_version: int | None,
        core_reachable: bool,
        leases: list[RoleLease],
    ) -> CapabilityResult | None:
        now = self._clock.now()
        if command.target_device_id != self._device_id:
            return self._rejection("TARGET_DEVICE_MISMATCH")
        if now + self._clock_skew < command.not_before:
            return self._rejection("COMMAND_NOT_YET_VALID")
        if now - self._clock_skew >= command.expires_at:
            return self._rejection("COMMAND_EXPIRED", status=AckStatus.EXPIRED)
        # RELEASE_ALL is intentionally independent of a stale engagement estimate.
        # It remains target- and TTL-bound, matching the Core safety guard.
        if command.command_type == CommandType.RELEASE_ALL:
            return None

        if current_state_version != command.required_state_version:
            return self._rejection("STATE_VERSION_MISMATCH")

        if command.command_type == CommandType.WOULD_BLOCK and not command.dry_run:
            return self._rejection("DRY_RUN_REQUIRED")

        if command.command_type in {CommandType.START_BLOCK, CommandType.ENTER_RECOVERY}:
            return self._rejection("WOULD_BLOCK_ONLY")

        if command.risk_level == RiskLevel.HARD:
            if not core_reachable:
                return self._rejection("CORE_UNREACHABLE")
            if not command.dry_run:
                return self._rejection("DRY_RUN_REQUIRED")
            lease = next(
                (item for item in leases if item.lease_id == command.role_lease_id),
                None,
            )
            if lease is None:
                return self._rejection("LEASE_REQUIRED")
            if (
                lease.device_id != self._device_id
                or lease.role != DeviceRole.PRIMARY_ENFORCEMENT
                or lease.revoked_at is not None
                or lease.expires_at <= now
                or lease.issued_for_state_version != command.required_state_version
            ):
                return self._rejection("LEASE_EXPIRED")
        return None

    @staticmethod
    def _rejection(
        reason_code: str,
        status: AckStatus = AckStatus.REJECTED,
    ) -> CapabilityResult:
        return CapabilityResult(
            status,
            [reason_code],
            {"rejected": True},
        )
