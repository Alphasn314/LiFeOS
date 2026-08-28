"""LifeOS Windows Agent orchestration."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar, Protocol

from .capabilities import CapabilityResult, SafeCapabilityAdapter
from .clock import Clock, SystemClock
from .collector import ActivityCollector
from .commands import CommandProcessor
from .config import AgentConfig
from .models import DeviceHeartbeat, Observation, ObservationKind
from .queue import SQLiteAgentStore
from .transport import CoreTransport

logger = logging.getLogger(__name__)


class AgentTransport(Protocol):
    core_reachable: bool

    async def enroll_device(self, name: str, capabilities: list[str]) -> None: ...

    async def send_message(
        self, message_type: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def fetch_commands(self) -> Any: ...

    async def fetch_active_session(self) -> uuid.UUID | None: ...

    async def aclose(self) -> None: ...


class LifeOSWindowsAgent:
    CAPABILITIES: ClassVar[list[str]] = [
        "ACTIVITY_SAMPLE",
        "IDLE_STATE",
        "LOCK_STATE",
        "NOTIFICATION",
        "WOULD_BLOCK",
        "RELEASE_ALL",
        "OFFLINE_QUEUE",
    ]

    def __init__(
        self,
        config: AgentConfig,
        collector: ActivityCollector | None = None,
        store: SQLiteAgentStore | None = None,
        adapter: SafeCapabilityAdapter | None = None,
        transport: AgentTransport | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.config = config
        self.clock = clock or SystemClock()
        self.collector = collector or ActivityCollector()
        self.store = store or SQLiteAgentStore(config.queue_path)
        self.adapter = adapter or SafeCapabilityAdapter()
        self.transport = transport or CoreTransport(
            base_url=config.core_url,
            device_id=config.device_id,
            token=config.dev_token,
            timeout_seconds=config.request_timeout_seconds,
        )
        self.command_processor = CommandProcessor(
            device_id=config.device_id,
            store=self.store,
            adapter=self.adapter,
            clock=self.clock,
            clock_skew_seconds=config.clock_skew_seconds,
        )
        self.session_id: uuid.UUID | None = None
        self._enrolled = False
        self._enrollment_task: asyncio.Task[bool] | None = None
        self._stop = asyncio.Event()
        self._flush_lock = asyncio.Lock()

    def sample_once(self) -> Observation:
        payload, reasons = self.collector.collect()
        now = self.clock.now()
        observation_id = uuid.uuid4()
        observation = Observation(
            observation_id=observation_id,
            device_id=self.config.device_id,
            session_id=self.session_id,
            kind=ObservationKind.ACTIVITY_SAMPLE,
            observed_at=now,
            received_at=now,
            idempotency_key=f"observation:{observation_id}",
            payload=payload,
            reason_codes=reasons,
        )
        self.store.enqueue(
            "observation",
            observation.idempotency_key,
            observation.model_dump(mode="json"),
            now,
        )
        return observation

    def heartbeat_once(self) -> DeviceHeartbeat:
        now = self.clock.now()
        heartbeat_id = uuid.uuid4()
        heartbeat = DeviceHeartbeat(
            heartbeat_id=heartbeat_id,
            device_id=self.config.device_id,
            observed_at=now,
            agent_version=self.config.agent_version,
            capabilities=self.CAPABILITIES,
            latest_state_version=self.store.latest_state_version(),
            core_reachable=self.transport.core_reachable,
            idempotency_key=f"heartbeat:{heartbeat_id}",
            reason_codes=["HEARTBEAT_RECEIVED"],
        )
        self.store.enqueue(
            "heartbeat",
            heartbeat.idempotency_key,
            heartbeat.model_dump(mode="json"),
            now,
        )
        return heartbeat

    async def flush_outbox(self, limit: int = 100) -> int:
        delivered = 0
        async with self._flush_lock:
            for item in self.store.due(self.clock.now(), limit=limit):
                try:
                    response = await self.transport.send_message(item.message_type, item.payload)
                except Exception as exc:  # transport implementations have different error types
                    self.store.mark_failed(item, self.clock.now(), type(exc).__name__)
                    break
                if item.message_type == "observation" and response is not None:
                    state_version = response.get("state_version")
                    if isinstance(state_version, int) and state_version >= 1:
                        self.store.set_latest_state_version(state_version)
                self.store.mark_delivered(item.sequence)
                delivered += 1
        return delivered

    async def poll_commands_once(self) -> int:
        batch = await self.transport.fetch_commands()
        if batch.latest_state_version is not None:
            self.store.set_latest_state_version(batch.latest_state_version)
        current_version = self.store.latest_state_version()
        processed = 0
        for command in batch.commands:
            if current_version is None and command.command_type != "RELEASE_ALL":
                # A cold Agent has not yet observed an authoritative RuntimeState.
                # Core keeps DELIVERED commands pollable, so defer without ACK.
                continue
            ack = await self.command_processor.process(
                command,
                current_state_version=current_version,
                core_reachable=self.transport.core_reachable,
                leases=batch.role_leases,
            )
            self.store.enqueue(
                "ack",
                ack.idempotency_key,
                ack.model_dump(mode="json"),
                self.clock.now(),
            )
            processed += 1
        return processed

    async def ensure_enrolled_once(self) -> bool:
        """Single-flight enrollment shared by concurrent sampling/heartbeat cycles."""

        if self._enrolled:
            return True
        task = self._enrollment_task
        if task is None:
            task = asyncio.create_task(self._enroll(), name="lifeos-enrollment")
            self._enrollment_task = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done() and self._enrollment_task is task:
                self._enrollment_task = None

    async def _enroll(self) -> bool:
        try:
            await self.transport.enroll_device(self.config.device_name, self.CAPABILITIES)
        except Exception:
            logger.warning("Core device enrollment failed; will retry", exc_info=True)
            return False
        self._enrolled = True
        return True

    async def sync_active_session_once(self) -> uuid.UUID | None:
        """Refresh the Core-owned session assignment without clearing it on outage."""

        try:
            active_session_id = await self.transport.fetch_active_session()
        except Exception:
            logger.warning(
                "Core active-session sync failed; retaining last known session",
                exc_info=True,
            )
            return self.session_id
        self.session_id = active_session_id
        return self.session_id

    def emergency_release_local(self) -> CapabilityResult:
        return self.command_processor.local_emergency_release()

    async def run(self) -> None:
        tasks = [
            asyncio.create_task(
                self._periodic(self._sample_cycle, self.config.sample_seconds),
                name="lifeos-sample",
            ),
            asyncio.create_task(
                self._periodic(self._heartbeat_cycle, self.config.heartbeat_seconds),
                name="lifeos-heartbeat",
            ),
            asyncio.create_task(
                self._periodic(self._command_cycle, self.config.command_poll_seconds),
                name="lifeos-commands",
            ),
        ]
        try:
            await self._stop.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.transport.aclose()
            self.store.close()

    def stop(self) -> None:
        self._stop.set()

    async def _sample_cycle(self) -> None:
        if await self.ensure_enrolled_once():
            await self.sync_active_session_once()
        self.sample_once()
        await self.flush_outbox()

    async def _heartbeat_cycle(self) -> None:
        await self.ensure_enrolled_once()
        self.heartbeat_once()
        await self.flush_outbox()

    async def _command_cycle(self) -> None:
        try:
            await self.poll_commands_once()
            await self.flush_outbox()
        except Exception:
            logger.warning("Core command poll failed; no command executed", exc_info=True)

    async def _periodic(
        self,
        operation: Callable[[], Awaitable[None]],
        interval_seconds: float,
    ) -> None:
        while not self._stop.is_set():
            started = self.clock.monotonic()
            try:
                await operation()
            except Exception:
                logger.warning("Agent cycle failed safely", exc_info=True)
            delay = max(0.0, interval_seconds - (self.clock.monotonic() - started))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                pass
