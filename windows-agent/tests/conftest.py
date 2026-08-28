from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from lifeos_windows_agent.models import Command, CommandPayload


@pytest.fixture
def device_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def make_command(
    *,
    device_id: uuid.UUID,
    now: datetime,
    command_type: str = "WOULD_BLOCK",
    required_state_version: int = 7,
    target_device_id: uuid.UUID | None = None,
    dry_run: bool = True,
) -> Command:
    from datetime import timedelta

    return Command.model_validate(
        {
            "schema_version": "1.0",
            "command_id": str(uuid.uuid4()),
            "target_device_id": str(target_device_id or device_id),
            "session_id": str(uuid.uuid4()),
            "decision_id": str(uuid.uuid4()),
            "role_lease_id": None,
            "authorized_commitment_mode": "STANDARD",
            "command_type": command_type,
            "risk_level": "SAFE",
            "issued_at": now.isoformat(),
            "not_before": now.isoformat(),
            "expires_at": (now + timedelta(minutes=1)).isoformat(),
            "required_state_version": required_state_version,
            "idempotency_key": f"command:{uuid.uuid4()}",
            "payload": CommandPayload(
                message="Return to Research",
                applications=["cs2.exe"],
                duration_seconds=600,
            ).model_dump(mode="json"),
            "dry_run": dry_run,
            "reason_codes": ["OFF_TASK_180_SECONDS", "WOULD_BLOCK_ONLY"],
        }
    )
