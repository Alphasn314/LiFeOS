from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from conftest import ApiHarness
from fastapi.testclient import TestClient
from sqlalchemy import select

from lifeos.api import create_app
from lifeos.db import Database
from lifeos.models import (
    CommandRow,
    EventLedgerRow,
    PolicyDecisionRow,
    RuntimeStateHeadRow,
    RuntimeStateRow,
)


def _start_session(harness: ApiHarness) -> tuple[dict, dict]:
    client, headers = harness.client, harness.headers
    device_response = client.post(
        "/api/v1/devices",
        headers=headers,
        json={"name": "Command PC", "device_type": "WINDOWS", "capabilities": []},
    )
    assert device_response.status_code == 201
    device = device_response.json()
    task_response = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": f"Command safety {uuid4()}",
            "estimated_minutes": 25,
            "minimum_chunk_minutes": 25,
            "mandatory": True,
        },
    )
    assert task_response.status_code == 201
    plan_response = client.post(
        "/api/v1/plans/generate",
        headers=headers,
        json={"plan_date": "2026-08-29", "now": harness.clock.now().isoformat()},
    )
    assert plan_response.status_code == 201
    plan = plan_response.json()
    block = next(item for item in plan["blocks"] if item["kind"] == "TASK")
    session_response = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={
            "block_id": block["block_id"],
            "device_id": device["device_id"],
            "commitment_mode": "STANDARD",
            "expected_plan_revision": plan["revision"],
        },
    )
    assert session_response.status_code == 201
    active = client.get(
        f"/api/v1/devices/{device['device_id']}/active-session", headers=headers
    )
    assert active.status_code == 200
    assert active.json()["session_id"] == session_response.json()["session_id"]
    return device, session_response.json()


def test_core_rejects_expired_and_stale_commands_and_deduplicates_ack(
    api_harness: ApiHarness,
) -> None:
    device, execution = _start_session(api_harness)
    device_id = UUID(device["device_id"])
    session_id = UUID(execution["session_id"])
    now = api_harness.clock.now()
    with api_harness.database.session() as db:
        head = db.scalar(
            select(RuntimeStateHeadRow).where(RuntimeStateHeadRow.device_id == device_id)
        )
        assert head is not None
        state = db.get(RuntimeStateRow, head.current_state_id)
        assert state is not None
        decision = PolicyDecisionRow(
            session_id=session_id,
            state_id=state.state_id,
            state_version=head.state_version,
            commitment_mode="STANDARD",
            intervention_level=1,
            action="NOTIFY",
            risk_level="SAFE",
            dry_run=True,
            decided_at=now,
            expires_at=now + timedelta(minutes=5),
            idempotency_key=f"decision:test:{uuid4()}",
            reason_codes=["OFF_TASK_30_SECONDS"],
        )
        db.add(decision)
        db.flush()
        expired = CommandRow(
            target_device_id=device_id,
            session_id=session_id,
            decision_id=decision.decision_id,
            role_lease_id=None,
            authorized_commitment_mode="STANDARD",
            command_type="SHOW_NOTIFICATION",
            risk_level="SAFE",
            status="PENDING",
            issued_at=now - timedelta(minutes=2),
            not_before=now - timedelta(minutes=2),
            expires_at=now,
            required_state_version=head.state_version,
            idempotency_key=f"command:expired:{uuid4()}",
            payload={"message": "expired", "duration_seconds": 0},
            dry_run=True,
            reason_codes=["OFF_TASK_30_SECONDS"],
            updated_at=now,
        )
        stale = CommandRow(
            target_device_id=device_id,
            session_id=session_id,
            decision_id=decision.decision_id,
            role_lease_id=None,
            authorized_commitment_mode="STANDARD",
            command_type="SHOW_NOTIFICATION",
            risk_level="SAFE",
            status="PENDING",
            issued_at=now,
            not_before=now,
            expires_at=now + timedelta(minutes=5),
            required_state_version=head.state_version + 1,
            idempotency_key=f"command:stale:{uuid4()}",
            payload={"message": "stale", "duration_seconds": 0},
            dry_run=True,
            reason_codes=["OFF_TASK_30_SECONDS"],
            updated_at=now,
        )
        valid = CommandRow(
            target_device_id=device_id,
            session_id=session_id,
            decision_id=decision.decision_id,
            role_lease_id=None,
            authorized_commitment_mode="STANDARD",
            command_type="SHOW_NOTIFICATION",
            risk_level="SAFE",
            status="PENDING",
            issued_at=now,
            not_before=now,
            expires_at=now + timedelta(minutes=5),
            required_state_version=head.state_version,
            idempotency_key=f"command:valid:{uuid4()}",
            payload={"message": "valid", "duration_seconds": 0},
            dry_run=True,
            reason_codes=["OFF_TASK_30_SECONDS"],
            updated_at=now,
        )
        db.add_all([expired, stale, valid])
        db.flush()
        expired_id, stale_id, valid_id = expired.command_id, stale.command_id, valid.command_id
        state_version = head.state_version

    polled = api_harness.client.get(
        f"/api/v1/devices/{device['device_id']}/commands", headers=api_harness.headers
    )
    assert polled.status_code == 200
    assert [item["command_id"] for item in polled.json()["commands"]] == [str(valid_id)]
    with api_harness.database.session() as db:
        assert db.get(CommandRow, expired_id).status == "EXPIRED"  # type: ignore[union-attr]
        assert db.get(CommandRow, stale_id).status == "REJECTED"  # type: ignore[union-attr]
        reasons = set(
            db.scalars(
                select(EventLedgerRow.event_type).where(
                    EventLedgerRow.entity_id.in_([expired_id, stale_id])
                )
            ).all()
        )
    assert reasons == {"COMMAND.REJECTED"}

    ack_id = uuid4()
    ack_body = {
        "ack_id": str(ack_id),
        "command_id": str(valid_id),
        "device_id": device["device_id"],
        "acknowledged_at": now.isoformat(),
        "status": "EXECUTED",
        "observed_state_version": state_version,
        "idempotency_key": f"ack:{ack_id}",
        "details": {"outcome": "shown"},
        "reason_codes": ["COMMAND_EXECUTED"],
    }
    first = api_harness.client.post(
        "/api/v1/commands/acks", headers=api_harness.headers, json=ack_body
    )
    replay = api_harness.client.post(
        "/api/v1/commands/acks", headers=api_harness.headers, json=ack_body
    )
    assert first.status_code == replay.status_code == 200
    assert first.json()["duplicate"] is False
    assert replay.json()["duplicate"] is True
    conflict = api_harness.client.post(
        "/api/v1/commands/acks",
        headers=api_harness.headers,
        json={**ack_body, "status": "FAILED"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "IDEMPOTENCY_CONFLICT"

    current = api_harness.client.get(
        f"/api/v1/sessions/{execution['session_id']}", headers=api_harness.headers
    ).json()
    aborted = api_harness.client.post(
        f"/api/v1/sessions/{execution['session_id']}/abort",
        headers=api_harness.headers,
        json={"expected_version": current["version"], "reason": "test complete"},
    )
    assert aborted.status_code == 200
    no_active = api_harness.client.get(
        f"/api/v1/devices/{device['device_id']}/active-session",
        headers=api_harness.headers,
    )
    assert no_active.status_code == 204


def test_core_restart_does_not_replay_an_expired_delivered_command(
    api_harness: ApiHarness,
) -> None:
    device, execution = _start_session(api_harness)
    release_key = f"restart-release:{uuid4()}"
    released = api_harness.client.post(
        f"/api/v1/sessions/{execution['session_id']}/emergency-release",
        headers=api_harness.headers,
        json={"idempotency_key": release_key, "reason": "restart safety test"},
    )
    assert released.status_code == 200
    delivered = api_harness.client.get(
        f"/api/v1/devices/{device['device_id']}/commands",
        headers=api_harness.headers,
    )
    assert delivered.status_code == 200
    release_command = next(
        item for item in delivered.json()["commands"] if item["command_type"] == "RELEASE_ALL"
    )

    api_harness.clock.value += timedelta(minutes=5)
    api_harness.client.close()
    api_harness.database.dispose()
    restarted_database = Database(api_harness.database_url)
    restarted_client = TestClient(
        create_app(
            settings=api_harness.settings,
            database=restarted_database,
            clock=api_harness.clock,
        )
    )
    try:
        after_restart = restarted_client.get(
            f"/api/v1/devices/{device['device_id']}/commands",
            headers=api_harness.headers,
        )
        assert after_restart.status_code == 200
        assert after_restart.json()["commands"] == []
        with restarted_database.session() as db:
            stored = db.get(CommandRow, UUID(release_command["command_id"]))
            assert stored is not None
            assert stored.status == "EXPIRED"
    finally:
        restarted_client.close()
        restarted_database.dispose()


def test_emergency_release_cancels_delivered_enforcement_before_returning(
    api_harness: ApiHarness,
) -> None:
    device, execution = _start_session(api_harness)
    for _ in range(21):
        observation_id = uuid4()
        response = api_harness.client.post(
            "/api/v1/observations",
            headers=api_harness.headers,
            json={
                "observation_id": str(observation_id),
                "device_id": device["device_id"],
                "session_id": execution["session_id"],
                "kind": "ACTIVITY_SAMPLE",
                "observed_at": api_harness.clock.now().isoformat(),
                "received_at": api_harness.clock.now().isoformat(),
                "idempotency_key": f"observation:{observation_id}",
                "payload": {
                    "foreground_process": "cs2.exe",
                    "window_title": "test",
                    "idle_seconds": 0,
                    "sensor_ok": True,
                },
                "reason_codes": ["SENSOR_SAMPLE"],
            },
        )
        assert response.status_code == 201
        api_harness.clock.value += timedelta(seconds=15)

    before = api_harness.client.get(
        f"/api/v1/devices/{device['device_id']}/commands",
        headers=api_harness.headers,
    )
    assert before.status_code == 200
    would_block = next(
        item for item in before.json()["commands"] if item["command_type"] == "WOULD_BLOCK"
    )
    released_at = api_harness.clock.now()
    emergency = api_harness.client.post(
        f"/api/v1/sessions/{execution['session_id']}/emergency-release",
        headers=api_harness.headers,
        json={
            "idempotency_key": f"emergency-race:{uuid4()}",
            "reason": "cancel delivered enforcement immediately",
        },
    )
    assert emergency.status_code == 200
    assert emergency.json()["emergency_released_at"] == released_at.isoformat().replace(
        "+00:00", "Z"
    )
    with api_harness.database.session() as db:
        cancelled = db.get(CommandRow, UUID(would_block["command_id"]))
        assert cancelled is not None
        assert cancelled.status == "CANCELLED"

    after = api_harness.client.get(
        f"/api/v1/devices/{device['device_id']}/commands",
        headers=api_harness.headers,
    )
    assert after.status_code == 200
    assert not any(item["command_type"] == "WOULD_BLOCK" for item in after.json()["commands"])
    assert any(item["command_type"] == "RELEASE_ALL" for item in after.json()["commands"])


def test_terminal_session_can_release_without_revival_but_cannot_override(
    api_harness: ApiHarness,
) -> None:
    device, execution = _start_session(api_harness)
    completed = api_harness.client.post(
        f"/api/v1/sessions/{execution['session_id']}/complete",
        headers=api_harness.headers,
        json={"expected_version": execution["version"], "reason": "work finished"},
    )
    assert completed.status_code == 200
    assert completed.json()["session_state"] == "COMPLETED"

    override = api_harness.client.post(
        f"/api/v1/sessions/{execution['session_id']}/ordinary-override",
        headers=api_harness.headers,
        json={"expected_version": completed.json()["version"], "reason": "too late"},
    )
    assert override.status_code == 409
    assert override.json()["error_code"] == "INVALID_SESSION_TRANSITION"

    released = api_harness.client.post(
        f"/api/v1/sessions/{execution['session_id']}/emergency-release",
        headers=api_harness.headers,
        json={
            "idempotency_key": f"terminal-emergency:{uuid4()}",
            "reason": "release remains available after completion",
        },
    )
    assert released.status_code == 200
    assert released.json()["session_state"] == "COMPLETED"
    assert released.json()["emergency_released_at"] is not None
    active = api_harness.client.get(
        f"/api/v1/devices/{device['device_id']}/active-session",
        headers=api_harness.headers,
    )
    assert active.status_code == 204
    commands = api_harness.client.get(
        f"/api/v1/devices/{device['device_id']}/commands",
        headers=api_harness.headers,
    )
    assert commands.status_code == 200
    assert any(item["command_type"] == "RELEASE_ALL" for item in commands.json()["commands"])

    observation_id = uuid4()
    unassigned_observation = api_harness.client.post(
        "/api/v1/observations",
        headers=api_harness.headers,
        json={
            "observation_id": str(observation_id),
            "device_id": device["device_id"],
            "session_id": None,
            "kind": "ACTIVITY_SAMPLE",
            "observed_at": api_harness.clock.now().isoformat(),
            "idempotency_key": f"observation:{observation_id}",
            "payload": {"foreground_process": "explorer.exe", "sensor_ok": True},
            "reason_codes": ["SENSOR_SAMPLE"],
        },
    )
    assert unassigned_observation.status_code == 201
    assert unassigned_observation.json()["session_id"] is None
