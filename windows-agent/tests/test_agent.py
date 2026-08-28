from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import make_command

from lifeos_windows_agent.agent import LifeOSWindowsAgent
from lifeos_windows_agent.collector import ActivityCollector, RawWindowsSample
from lifeos_windows_agent.config import AgentConfig
from lifeos_windows_agent.models import CommandBatch
from lifeos_windows_agent.queue import SQLiteAgentStore


@dataclass
class FakeClock:
    current: datetime
    tick: float = 0

    def now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return self.tick

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)
        self.tick += seconds


class FakeSensor:
    def collect(self) -> RawWindowsSample:
        return RawWindowsSample(None, "Research", 3, False)


class FakeTransport:
    def __init__(self) -> None:
        self.core_reachable = False
        self.fail_enrollment = False
        self.fail_writes = True
        self.fail_session_fetch = False
        self.active_session_id: uuid.UUID | None = None
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.batch = CommandBatch(commands=[])
        self.enrollments: list[tuple[str, list[str]]] = []
        self.enrollment_started: asyncio.Event | None = None
        self.enrollment_release: asyncio.Event | None = None

    async def enroll_device(self, name: str, capabilities: list[str]) -> None:
        self.enrollments.append((name, capabilities))
        if self.enrollment_started is not None:
            self.enrollment_started.set()
        if self.enrollment_release is not None:
            await self.enrollment_release.wait()
        if self.fail_enrollment:
            self.core_reachable = False
            raise ConnectionError("offline")
        self.core_reachable = True

    async def send_message(
        self, message_type: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        if self.fail_writes:
            self.core_reachable = False
            raise ConnectionError("offline")
        self.core_reachable = True
        self.sent.append((message_type, payload))
        return {"state_version": 7} if message_type == "observation" else None

    async def fetch_commands(self) -> CommandBatch:
        self.core_reachable = True
        return self.batch

    async def fetch_active_session(self) -> uuid.UUID | None:
        if self.fail_session_fetch:
            self.core_reachable = False
            raise ConnectionError("offline")
        self.core_reachable = True
        return self.active_session_id

    async def aclose(self) -> None:
        return None


def make_agent(
    tmp_path: Path,
    device_id: uuid.UUID,
    now: datetime,
) -> tuple[LifeOSWindowsAgent, FakeTransport, FakeClock]:
    transport = FakeTransport()
    clock = FakeClock(now)
    config = AgentConfig(device_id=device_id, queue_path=tmp_path / "agent.db")
    agent = LifeOSWindowsAgent(
        config,
        collector=ActivityCollector(FakeSensor()),
        store=SQLiteAgentStore(config.queue_path),
        transport=transport,
        clock=clock,
    )
    return agent, transport, clock


@pytest.mark.asyncio
async def test_offline_observation_and_heartbeat_store_then_forward_oldest_first(
    tmp_path: Path, device_id: uuid.UUID, now: datetime
) -> None:
    agent, transport, clock = make_agent(tmp_path, device_id, now)
    observation = agent.sample_once()
    heartbeat = agent.heartbeat_once()

    assert heartbeat.core_reachable is False
    assert agent.store.pending_count() == 2
    assert await agent.flush_outbox() == 0
    clock.advance(1)
    transport.fail_writes = False

    assert await agent.flush_outbox() == 2
    assert [kind for kind, _ in transport.sent] == ["observation", "heartbeat"]
    assert transport.sent[0][1]["idempotency_key"] == observation.idempotency_key
    assert agent.store.latest_state_version() == 7
    assert agent.store.pending_count() == 0


@pytest.mark.asyncio
async def test_command_ack_is_durable_before_transport(
    tmp_path: Path, device_id: uuid.UUID, now: datetime
) -> None:
    agent, transport, _clock = make_agent(tmp_path, device_id, now)
    transport.batch = CommandBatch(
        commands=[make_command(device_id=device_id, now=now)],
        latest_state_version=7,
    )

    assert await agent.poll_commands_once() == 1
    assert agent.store.pending_count() == 1
    assert agent.adapter.would_block_audit[0]["applications"] == ["cs2.exe"]


@pytest.mark.asyncio
async def test_cold_agent_defers_non_release_command_until_state_sync(
    tmp_path: Path, device_id: uuid.UUID, now: datetime
) -> None:
    agent, transport, _clock = make_agent(tmp_path, device_id, now)
    transport.batch = CommandBatch(commands=[make_command(device_id=device_id, now=now)])

    assert await agent.poll_commands_once() == 0
    assert agent.store.pending_count() == 0
    assert agent.adapter.would_block_audit == []


def test_default_heartbeat_cadence_is_fifteen_seconds(tmp_path: Path, device_id: uuid.UUID) -> None:
    config = AgentConfig(device_id=device_id, queue_path=tmp_path / "agent.db")
    assert config.heartbeat_seconds == 15
    with pytest.raises(ValueError, match="15-second"):
        AgentConfig(
            device_id=device_id,
            queue_path=tmp_path / "bad.db",
            heartbeat_seconds=14.9,
        )


@pytest.mark.asyncio
async def test_sample_cycle_syncs_active_session_into_real_observation_payload(
    tmp_path: Path, device_id: uuid.UUID, now: datetime
) -> None:
    agent, transport, _clock = make_agent(tmp_path, device_id, now)
    session_id = uuid.uuid4()
    transport.active_session_id = session_id
    transport.fail_writes = False

    await agent._sample_cycle()

    assert agent.session_id == session_id
    assert transport.sent[0][0] == "observation"
    assert transport.sent[0][1]["session_id"] == str(session_id)


@pytest.mark.asyncio
async def test_initial_enrollment_is_reused_by_sample_and_heartbeat_cycles(
    tmp_path: Path, device_id: uuid.UUID, now: datetime
) -> None:
    agent, transport, _clock = make_agent(tmp_path, device_id, now)

    await agent._sample_cycle()
    await agent._heartbeat_cycle()

    assert transport.enrollments == [(agent.config.device_name, agent.CAPABILITIES)]
    assert agent.store.pending_count() == 2


@pytest.mark.asyncio
async def test_failed_enrollment_keeps_observation_and_retries_next_cycle(
    tmp_path: Path, device_id: uuid.UUID, now: datetime
) -> None:
    agent, transport, _clock = make_agent(tmp_path, device_id, now)
    transport.fail_enrollment = True

    await agent._sample_cycle()
    assert len(transport.enrollments) == 1
    assert agent.store.pending_count() == 1

    transport.fail_enrollment = False
    await agent._heartbeat_cycle()
    assert len(transport.enrollments) == 2
    assert agent.store.pending_count() == 2


@pytest.mark.asyncio
async def test_concurrent_cycles_share_one_enrollment_request(
    tmp_path: Path, device_id: uuid.UUID, now: datetime
) -> None:
    agent, transport, _clock = make_agent(tmp_path, device_id, now)
    transport.enrollment_started = asyncio.Event()
    transport.enrollment_release = asyncio.Event()

    sample = asyncio.create_task(agent._sample_cycle())
    await transport.enrollment_started.wait()
    heartbeat = asyncio.create_task(agent._heartbeat_cycle())
    await asyncio.sleep(0)
    assert len(transport.enrollments) == 1

    transport.enrollment_release.set()
    await asyncio.gather(sample, heartbeat)
    assert len(transport.enrollments) == 1


@pytest.mark.asyncio
async def test_active_session_sync_clears_only_on_authoritative_no_session(
    tmp_path: Path, device_id: uuid.UUID, now: datetime
) -> None:
    agent, transport, _clock = make_agent(tmp_path, device_id, now)
    known_session_id = uuid.uuid4()
    agent.session_id = known_session_id
    transport.fail_session_fetch = True

    assert await agent.sync_active_session_once() == known_session_id
    assert agent.session_id == known_session_id

    transport.fail_session_fetch = False
    transport.active_session_id = None
    assert await agent.sync_active_session_once() is None
    assert agent.session_id is None
