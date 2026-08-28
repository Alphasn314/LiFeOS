"""Environment-backed Agent configuration with conservative defaults."""

from __future__ import annotations

import os
import platform
import uuid
from dataclasses import dataclass, field
from pathlib import Path


def _stable_device_id() -> uuid.UUID:
    material = f"{platform.node()}:{uuid.getnode()}"
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"lifeos-windows-agent:{material}")


def _default_queue_path() -> Path:
    local_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_data) if local_data else Path.cwd()
    return root / "LifeOS" / "agent-queue.db"


@dataclass(frozen=True, slots=True)
class AgentConfig:
    core_url: str = "http://127.0.0.1:8000"
    device_id: uuid.UUID = field(default_factory=_stable_device_id)
    device_name: str = field(default_factory=lambda: platform.node() or "Windows PC")
    dev_token: str | None = None
    queue_path: Path = field(default_factory=_default_queue_path)
    heartbeat_seconds: float = 15.0
    sample_seconds: float = 5.0
    command_poll_seconds: float = 5.0
    request_timeout_seconds: float = 5.0
    clock_skew_seconds: float = 0.0
    agent_version: str = "0.1.0"

    def __post_init__(self) -> None:
        if self.heartbeat_seconds < 15:
            raise ValueError("heartbeat_seconds cannot be lower than the frozen 15-second cadence")
        if self.sample_seconds <= 0 or self.command_poll_seconds <= 0:
            raise ValueError("sampling and polling intervals must be positive")
        if self.request_timeout_seconds <= 0 or self.clock_skew_seconds < 0:
            raise ValueError("timeout must be positive and clock skew cannot be negative")

    @classmethod
    def from_env(cls) -> AgentConfig:
        raw_device_id = os.environ.get("LIFEOS_DEVICE_ID")
        return cls(
            core_url=os.environ.get("LIFEOS_CORE_URL", "http://127.0.0.1:8000"),
            device_id=uuid.UUID(raw_device_id) if raw_device_id else _stable_device_id(),
            device_name=os.environ.get("LIFEOS_DEVICE_NAME") or platform.node() or "Windows PC",
            dev_token=os.environ.get("LIFEOS_DEV_TOKEN"),
            queue_path=Path(os.environ.get("LIFEOS_AGENT_DB", str(_default_queue_path()))),
            heartbeat_seconds=float(os.environ.get("LIFEOS_HEARTBEAT_SECONDS", "15")),
            sample_seconds=float(os.environ.get("LIFEOS_SAMPLE_SECONDS", "5")),
            command_poll_seconds=float(os.environ.get("LIFEOS_COMMAND_POLL_SECONDS", "5")),
            request_timeout_seconds=float(os.environ.get("LIFEOS_REQUEST_TIMEOUT_SECONDS", "5")),
            clock_skew_seconds=float(os.environ.get("LIFEOS_CLOCK_SKEW_SECONDS", "0")),
        )
