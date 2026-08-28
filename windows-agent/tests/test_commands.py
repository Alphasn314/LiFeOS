from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from conftest import make_command

from lifeos_windows_agent.capabilities import SafeCapabilityAdapter
from lifeos_windows_agent.commands import CommandProcessor
from lifeos_windows_agent.models import AckStatus, RoleLease
from lifeos_windows_agent.queue import SQLiteAgentStore


@dataclass
class FakeClock:
    current: datetime

    def now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return 0.0


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, bool]] = []

    def notify(self, title: str, message: str, topmost: bool = False) -> None:
        self.messages.append((title, message, topmost))


def processor(tmp_path: Path, device_id: uuid.UUID, now: datetime):
    store = SQLiteAgentStore(tmp_path / "agent.db")
    adapter = SafeCapabilityAdapter(RecordingNotifier())
    return CommandProcessor(device_id, store, adapter, FakeClock(now)), adapter


def test_active_role_lease_accepts_null_revocation(device_id: uuid.UUID, now: datetime) -> None:
    lease = RoleLease.model_validate(
        {
            "schema_version": "1.0",
            "lease_id": str(uuid.uuid4()),
            "device_id": str(device_id),
            "role": "PRIMARY_ENFORCEMENT",
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=1)).isoformat(),
            "revoked_at": None,
            "issued_for_state_version": 7,
            "version": 1,
            "reason_codes": ["HEARTBEAT_RECEIVED"],
        }
    )

    assert lease.revoked_at is None


@pytest.mark.asyncio
async def test_would_block_is_audited_without_os_action_and_is_idempotent(
    tmp_path: Path, device_id: uuid.UUID, now: datetime
) -> None:
    subject, adapter = processor(tmp_path, device_id, now)
    command = make_command(device_id=device_id, now=now)

    first = await subject.process(command, 7, True)
    duplicate = await subject.process(command, 7, True)

    assert first.status == AckStatus.EXECUTED
    assert first.observed_state_version == 7
    assert first.details["outcome"] == "WOULD_BLOCK"
    assert set(first.model_dump(mode="json")) == {
        "ack_id",
        "command_id",
        "device_id",
        "status",
        "acknowledged_at",
        "observed_state_version",
        "idempotency_key",
        "details",
        "reason_codes",
    }
    assert duplicate.ack_id == first.ack_id
    assert adapter.would_block_audit == [
        {"applications": ["cs2.exe"], "duration_seconds": 600, "restriction_id": None}
    ]
    assert adapter.simulated_restrictions == set()


@pytest.mark.asyncio
async def test_command_at_expiry_boundary_is_rejected(
    tmp_path: Path, device_id: uuid.UUID, now: datetime
) -> None:
    subject, adapter = processor(tmp_path, device_id, now)
    command = make_command(device_id=device_id, now=now)
    subject._clock.current = command.expires_at  # type: ignore[attr-defined]

    ack = await subject.process(command, 7, True)

    assert ack.status == AckStatus.EXPIRED
    assert ack.reason_codes == ["COMMAND_EXPIRED"]
    assert adapter.would_block_audit == []


@pytest.mark.asyncio
async def test_state_and_device_mismatch_reject_before_adapter(
    tmp_path: Path, device_id: uuid.UUID, now: datetime
) -> None:
    subject, adapter = processor(tmp_path, device_id, now)
    stale = make_command(device_id=device_id, now=now)
    stale_ack = await subject.process(stale, 8, True)
    wrong_target = make_command(
        device_id=device_id,
        target_device_id=uuid.uuid4(),
        now=now + timedelta(seconds=1),
    )
    wrong_ack = await subject.process(wrong_target, 7, True)

    assert stale_ack.reason_codes == ["STATE_VERSION_MISMATCH"]
    assert wrong_ack.reason_codes == ["TARGET_DEVICE_MISMATCH"]
    assert adapter.would_block_audit == []


@pytest.mark.asyncio
async def test_not_before_and_v1_unsupported_hard_action_reject(
    tmp_path: Path, device_id: uuid.UUID, now: datetime
) -> None:
    subject, adapter = processor(tmp_path, device_id, now)
    future = make_command(device_id=device_id, now=now)
    future = future.model_copy(update={"not_before": now + timedelta(seconds=10)})
    future_ack = await subject.process(future, 7, True)
    unsupported = make_command(
        device_id=device_id,
        now=now,
        command_type="START_BLOCK",
    )
    unsupported_ack = await subject.process(unsupported, 7, True)

    assert future_ack.reason_codes == ["COMMAND_NOT_YET_VALID"]
    assert unsupported_ack.reason_codes == ["WOULD_BLOCK_ONLY"]
    assert adapter.simulated_restrictions == set()


@pytest.mark.asyncio
async def test_release_all_and_local_emergency_release_are_idempotent(
    tmp_path: Path, device_id: uuid.UUID, now: datetime
) -> None:
    subject, adapter = processor(tmp_path, device_id, now)
    adapter.simulated_restrictions.update({"one", "two"})
    release = make_command(
        device_id=device_id,
        now=now,
        command_type="RELEASE_ALL",
    )

    ack = await subject.process(release, 999, False)
    local = subject.local_emergency_release()

    assert ack.status == AckStatus.EXECUTED
    assert ack.details["released_count"] == 2
    assert local.status == AckStatus.EXECUTED
    assert local.details["released_count"] == 0
    assert adapter.simulated_restrictions == set()
