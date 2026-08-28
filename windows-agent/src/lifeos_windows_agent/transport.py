"""HTTP transport; all write payloads can first live in the SQLite outbox."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from .models import CommandBatch


@dataclass(frozen=True, slots=True)
class EndpointPaths:
    enrollment: str = "/api/v1/devices/{device_id}"
    observations: str = "/api/v1/observations"
    heartbeats: str = "/api/v1/devices/heartbeats"
    acknowledgements: str = "/api/v1/commands/acks"
    commands: str = "/api/v1/devices/{device_id}/commands"
    active_session: str = "/api/v1/devices/{device_id}/active-session"


class CoreTransport:
    def __init__(
        self,
        base_url: str,
        device_id: uuid.UUID,
        token: str | None,
        timeout_seconds: float,
        paths: EndpointPaths | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.paths = paths or EndpointPaths()
        self.device_id = device_id
        self.core_reachable = False
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout_seconds,
            transport=http_transport,
        )

    async def enroll_device(self, name: str, capabilities: list[str]) -> None:
        """Idempotently enroll this stable device identity with Core."""

        path = self.paths.enrollment.format(device_id=self.device_id)
        payload = {
            "name": name,
            "device_type": "WINDOWS",
            "capabilities": capabilities,
        }
        try:
            response = await self._client.put(path, json=payload)
            response.raise_for_status()
            self.core_reachable = True
        except httpx.HTTPError:
            self.core_reachable = False
            raise

    async def send_message(
        self, message_type: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        path_by_type = {
            "observation": self.paths.observations,
            "heartbeat": self.paths.heartbeats,
            "ack": self.paths.acknowledgements,
        }
        try:
            response = await self._client.post(path_by_type[message_type], json=payload)
            response.raise_for_status()
            self.core_reachable = True
        except (httpx.HTTPError, KeyError):
            self.core_reachable = False
            raise
        if response.status_code == 204 or not response.content:
            return None
        body = response.json()
        return body if isinstance(body, dict) else None

    async def fetch_commands(self) -> CommandBatch:
        path = self.paths.commands.format(device_id=self.device_id)
        try:
            response = await self._client.get(path)
            response.raise_for_status()
            self.core_reachable = True
        except httpx.HTTPError:
            self.core_reachable = False
            raise

        if response.status_code == 204 or not response.content:
            return CommandBatch(commands=[])
        body = response.json()
        if isinstance(body, list):
            return CommandBatch(commands=body)
        if not isinstance(body, dict):
            raise ValueError("command endpoint must return a JSON object or list")
        normalized = {
            "commands": body.get("commands", body.get("items", [])),
            "latest_state_version": body.get("latest_state_version", body.get("state_version")),
            "role_leases": body.get("role_leases", []),
        }
        return CommandBatch.model_validate(normalized)

    async def fetch_active_session(self) -> uuid.UUID | None:
        """Return Core's active session assignment for this device.

        A successful 204 is authoritative and clears a previously cached session.
        Transport and server failures raise so the Agent can retain its last known
        assignment while offline.
        """

        path = self.paths.active_session.format(device_id=self.device_id)
        try:
            response = await self._client.get(path)
            response.raise_for_status()
            self.core_reachable = True
        except httpx.HTTPError:
            self.core_reachable = False
            raise

        if response.status_code == 204 or not response.content:
            return None
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("active-session endpoint must return a JSON object or 204")
        session_id = body.get("session_id")
        if session_id is None:
            raise ValueError("active-session response is missing session_id")
        return uuid.UUID(str(session_id))

    async def aclose(self) -> None:
        await self._client.aclose()
