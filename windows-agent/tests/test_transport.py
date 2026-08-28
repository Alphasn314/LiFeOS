from __future__ import annotations

import json
import uuid
from datetime import datetime

import httpx
import pytest
from conftest import make_command

from lifeos_windows_agent.transport import CoreTransport


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 201])
async def test_http_transport_enrolls_stable_device_idempotently(
    device_id: uuid.UUID, status_code: int
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code, json={"device_id": str(device_id)})

    transport = CoreTransport(
        "http://core.test",
        device_id,
        "secret",
        1,
        http_transport=httpx.MockTransport(handler),
    )
    try:
        await transport.enroll_device("Research PC", ["ACTIVITY_SAMPLE"])
    finally:
        await transport.aclose()

    assert seen[0].method == "PUT"
    assert seen[0].url.path == f"/api/v1/devices/{device_id}"
    assert json.loads(seen[0].content) == {
        "name": "Research PC",
        "device_type": "WINDOWS",
        "capabilities": ["ACTIVITY_SAMPLE"],
    }


@pytest.mark.asyncio
async def test_http_transport_uses_frozen_payloads_and_configured_device(
    device_id: uuid.UUID, now: datetime
) -> None:
    command = make_command(device_id=device_id, now=now)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "commands": [command.model_dump(mode="json")],
                    "latest_state_version": 7,
                    "role_leases": [],
                },
            )
        assert json.loads(request.content) == {"sample": True}
        return httpx.Response(202, json={"accepted": True})

    transport = CoreTransport(
        "http://core.test",
        device_id,
        "secret",
        1,
        http_transport=httpx.MockTransport(handler),
    )
    await transport.send_message("observation", {"sample": True})
    batch = await transport.fetch_commands()
    await transport.aclose()

    assert batch.latest_state_version == 7
    assert batch.commands == [command]
    assert seen[0].headers["authorization"] == "Bearer secret"
    assert seen[1].url.path == f"/api/v1/devices/{device_id}/commands"


@pytest.mark.asyncio
async def test_active_session_transport_distinguishes_assignment_from_no_session(
    device_id: uuid.UUID,
) -> None:
    session_id = uuid.uuid4()
    responses = iter(
        [
            httpx.Response(200, json={"session_id": str(session_id)}),
            httpx.Response(204),
        ]
    )

    transport = CoreTransport(
        "http://core.test",
        device_id,
        None,
        1,
        http_transport=httpx.MockTransport(lambda _request: next(responses)),
    )
    try:
        assert await transport.fetch_active_session() == session_id
        assert await transport.fetch_active_session() is None
    finally:
        await transport.aclose()
