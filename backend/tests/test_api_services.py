from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from conftest import ApiHarness
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lifeos.ai import OfflineAIProvider
from lifeos.api import create_app
from lifeos.models import EventLedgerRow, OutboxRow


def test_task_crud_auth_occ_and_structured_errors(api_harness: ApiHarness) -> None:
    client, headers = api_harness.client, api_harness.headers
    assert client.get("/api/v1/tasks").status_code == 401

    created = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "English",
            "estimated_minutes": 50,
            "mandatory": True,
            "allowed_apps": ["MSWORD.EXE"],
            "blocked_apps": ["cs2.exe"],
        },
    )
    assert created.status_code == 201
    task = created.json()
    assert task["allowed_apps"] == ["msword.exe"]
    assert task["remaining_minutes"] == 50

    conflict = client.patch(
        f"/api/v1/tasks/{task['task_id']}",
        headers=headers,
        json={"expected_version": 99, "priority": 5},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "VERSION_CONFLICT"

    updated = client.patch(
        f"/api/v1/tasks/{task['task_id']}",
        headers=headers,
        json={"expected_version": 1, "priority": 5, "remaining_minutes": 25},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    deleted = client.delete(f"/api/v1/tasks/{task['task_id']}?expected_version=2", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "CANCELLED"
    assert client.get("/api/v1/tasks", headers=headers).json() == []


def test_external_event_replay_has_one_ledger_and_outbox_side_effect(
    api_harness: ApiHarness,
) -> None:
    occurred = api_harness.clock.now().isoformat()
    entity_id = str(uuid4())
    key = f"external:{uuid4()}"
    base = {
        "event_id": str(uuid4()),
        "event_type": "AVAILABLE_TIME.CHANGED",
        "occurred_at": occurred,
        "received_at": occurred,
        "source": "test-client",
        "entity_type": "Availability",
        "entity_id": entity_id,
        "idempotency_key": key,
        "payload": {"available": False},
        "reason_codes": ["AVAILABLE_TIME_CHANGED"],
    }
    first = api_harness.client.post("/api/v1/events", headers=api_harness.headers, json=base)
    replay = api_harness.client.post(
        "/api/v1/events",
        headers=api_harness.headers,
        json={**base, "event_id": str(uuid4())},
    )
    assert first.status_code == replay.status_code == 202
    assert replay.json()["duplicate"] is True
    assert replay.json()["event_id"] == first.json()["event_id"]

    changed = api_harness.client.post(
        "/api/v1/events",
        headers=api_harness.headers,
        json={**base, "event_id": str(uuid4()), "payload": {"available": True}},
    )
    assert changed.status_code == 409
    assert changed.json()["error_code"] == "IDEMPOTENCY_CONFLICT"

    with api_harness.database.session() as db:
        ledger_count = db.scalar(
            select(func.count())
            .select_from(EventLedgerRow)
            .where(EventLedgerRow.idempotency_key == key)
        )
        event_id = db.scalar(
            select(EventLedgerRow.event_id).where(EventLedgerRow.idempotency_key == key)
        )
        outbox_count = db.scalar(
            select(func.count()).select_from(OutboxRow).where(OutboxRow.event_id == event_id)
        )
    assert ledger_count == 1
    assert outbox_count == 1


def test_ai_offline_is_recorded_and_deterministic_core_still_plans(
    api_harness: ApiHarness,
) -> None:
    offline_app = create_app(
        settings=api_harness.settings,
        database=api_harness.database,
        clock=api_harness.clock,
        ai_provider=OfflineAIProvider(),
    )
    with TestClient(offline_app) as client:
        now = api_harness.clock.now()
        request_id = str(uuid4())
        response = client.post(
            "/api/v1/ai/jobs",
            headers=api_harness.headers,
            json={
                "idempotency_key": f"ai-job:{uuid4()}",
                "request": {
                    "request_id": request_id,
                    "requested_at": now.isoformat(),
                    "current_time": now.isoformat(),
                    "runtime_state": None,
                    "current_plan": None,
                    "current_block_id": None,
                    "future_blocks": [],
                    "today_progress": {},
                    "unfinished_tasks": [],
                    "active_incident": {"type": "AI_OFFLINE"},
                    "policy_constraints": {"dry_run": True},
                    "reason_codes": ["CONTEXT_DEFAULT_BOUNDED"],
                },
            },
        )
        assert response.status_code == 201
        assert response.json()["status"] == "FAILED"
        assert response.json()["fallback_used"] is True

        assert (
            client.post(
                "/api/v1/tasks",
                headers=api_harness.headers,
                json={"title": "Offline-safe task", "estimated_minutes": 50},
            ).status_code
            == 201
        )
        plan = client.post(
            "/api/v1/plans/generate",
            headers=api_harness.headers,
            json={
                "plan_date": "2026-08-29",
                "now": (now + timedelta(minutes=1)).isoformat(),
            },
        )
        assert plan.status_code == 201
        assert plan.json()["status"] in {"FEASIBLE", "PARTIAL"}


def test_fixed_event_crud_and_heartbeat_offline_boundary(
    api_harness: ApiHarness,
) -> None:
    client, headers, clock = api_harness.client, api_harness.headers, api_harness.clock
    created = client.post(
        "/api/v1/fixed-events",
        headers=headers,
        json={
            "title": "Morning class",
            "start_at": "2026-08-29T00:00:00Z",
            "end_at": "2026-08-29T01:00:00Z",
            "travel_before_minutes": 15,
        },
    )
    assert created.status_code == 201
    event = created.json()
    assert event["version"] == 1

    stale = client.patch(
        f"/api/v1/fixed-events/{event['fixed_event_id']}",
        headers=headers,
        json={"expected_version": 99, "title": "Stale write"},
    )
    assert stale.status_code == 409
    updated = client.patch(
        f"/api/v1/fixed-events/{event['fixed_event_id']}",
        headers=headers,
        json={"expected_version": 1, "title": "Updated class"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    listed = client.get(
        "/api/v1/fixed-events",
        headers=headers,
        params={
            "start_at": "2026-08-28T23:00:00Z",
            "end_at": "2026-08-29T02:00:00Z",
        },
    )
    assert listed.status_code == 200
    assert [item["title"] for item in listed.json()] == ["Updated class"]
    deleted = client.delete(
        f"/api/v1/fixed-events/{event['fixed_event_id']}?expected_version=2",
        headers=headers,
    )
    assert deleted.status_code == 204

    device = client.post(
        "/api/v1/devices",
        headers=headers,
        json={"name": "Boundary PC", "device_type": "WINDOWS", "capabilities": []},
    ).json()
    heartbeat_id = uuid4()
    heartbeat = {
        "heartbeat_id": str(heartbeat_id),
        "device_id": device["device_id"],
        "observed_at": clock.now().isoformat(),
        "agent_version": "0.1.0",
        "capabilities": ["FOREGROUND_PROCESS"],
        "latest_state_version": None,
        "core_reachable": True,
        "idempotency_key": f"heartbeat:{heartbeat_id}",
        "reason_codes": ["HEARTBEAT_RECEIVED"],
    }
    first = client.post("/api/v1/devices/heartbeats", headers=headers, json=heartbeat)
    replay = client.post("/api/v1/devices/heartbeats", headers=headers, json=heartbeat)
    assert first.status_code == replay.status_code == 200
    assert first.json()["status"] == replay.json()["status"] == "ONLINE"
    with api_harness.database.session() as db:
        count = db.scalar(
            select(func.count())
            .select_from(EventLedgerRow)
            .where(EventLedgerRow.idempotency_key == heartbeat["idempotency_key"])
        )
    assert count == 1

    clock.value += timedelta(seconds=44, milliseconds=999)
    assert (
        client.get(f"/api/v1/devices/{device['device_id']}", headers=headers).json()["status"]
        == "ONLINE"
    )
    clock.value += timedelta(milliseconds=1)
    assert (
        client.get(f"/api/v1/devices/{device['device_id']}", headers=headers).json()["status"]
        == "OFFLINE"
    )
    conflict = client.post(
        "/api/v1/devices/heartbeats",
        headers=headers,
        json={**heartbeat, "capabilities": ["IDLE_SECONDS"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "IDEMPOTENCY_CONFLICT"

    newer_id = uuid4()
    newer_time = clock.now()
    newer = {
        **heartbeat,
        "heartbeat_id": str(newer_id),
        "observed_at": newer_time.isoformat(),
        "idempotency_key": f"heartbeat:{newer_id}",
    }
    assert (
        client.post("/api/v1/devices/heartbeats", headers=headers, json=newer).status_code
        == 200
    )
    older_id = uuid4()
    delayed_older = {
        **heartbeat,
        "heartbeat_id": str(older_id),
        "observed_at": (newer_time - timedelta(minutes=5)).isoformat(),
        "idempotency_key": f"heartbeat:{older_id}",
    }
    delayed = client.post(
        "/api/v1/devices/heartbeats", headers=headers, json=delayed_older
    )
    assert delayed.status_code == 200
    assert delayed.json()["last_heartbeat_at"] == newer_time.isoformat().replace("+00:00", "Z")
    assert delayed.json()["status"] == "ONLINE"

    future_id = uuid4()
    future = {
        **heartbeat,
        "heartbeat_id": str(future_id),
        "observed_at": (clock.now() + timedelta(minutes=5, milliseconds=1)).isoformat(),
        "idempotency_key": f"heartbeat:{future_id}",
    }
    rejected_future = client.post(
        "/api/v1/devices/heartbeats", headers=headers, json=future
    )
    assert rejected_future.status_code == 422
    assert rejected_future.json()["error_code"] == "HEARTBEAT_FROM_FUTURE"


def test_agent_device_enrollment_is_idempotent(api_harness: ApiHarness) -> None:
    device_id = uuid4()
    payload = {
        "name": "Auto-enrolled Windows PC",
        "device_type": "WINDOWS",
        "capabilities": ["ACTIVITY_SAMPLE", "OFFLINE_QUEUE"],
    }
    first = api_harness.client.put(
        f"/api/v1/devices/{device_id}", headers=api_harness.headers, json=payload
    )
    replay = api_harness.client.put(
        f"/api/v1/devices/{device_id}", headers=api_harness.headers, json=payload
    )
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json()["device_id"] == str(device_id)
    with api_harness.database.session() as db:
        events = db.scalar(
            select(func.count())
            .select_from(EventLedgerRow)
            .where(EventLedgerRow.idempotency_key == f"device:enroll:{device_id}")
        )
    assert events == 1

    conflict = api_harness.client.put(
        f"/api/v1/devices/{device_id}",
        headers=api_harness.headers,
        json={**payload, "device_type": "MOBILE"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "DEVICE_ID_CONFLICT"


def test_infeasible_revision_does_not_block_the_next_plan_version(
    api_harness: ApiHarness,
) -> None:
    client, headers, now = (
        api_harness.client,
        api_harness.headers,
        api_harness.clock.now(),
    )
    created = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "Revision recovery",
            "estimated_minutes": 50,
            "minimum_chunk_minutes": 25,
            "mandatory": True,
        },
    )
    assert created.status_code == 201
    first = client.post(
        "/api/v1/plans/generate",
        headers=headers,
        json={"plan_date": "2026-08-29", "now": now.isoformat()},
    )
    assert first.status_code == 201
    assert first.json()["revision"] == 1

    infeasible = client.post(
        "/api/v1/plans/generate",
        headers=headers,
        json={
            "plan_date": "2026-08-29",
            "trigger": "USER_REQUESTED_REPLAN",
            "now": now.isoformat(),
            "available_start_local": "22:30",
            "available_end_local": "23:00",
        },
    )
    assert infeasible.status_code == 201
    assert infeasible.json()["revision"] == 2
    assert infeasible.json()["status"] == "INFEASIBLE"
    current = client.get(
        "/api/v1/plans/current?plan_date=2026-08-29", headers=headers
    )
    assert current.json()["plan_version_id"] == first.json()["plan_version_id"]

    recovered = client.post(
        "/api/v1/plans/generate",
        headers=headers,
        json={
            "plan_date": "2026-08-29",
            "trigger": "USER_REQUESTED_REPLAN",
            "now": now.isoformat(),
        },
    )
    assert recovered.status_code == 201, recovered.text
    assert recovered.json()["revision"] == 3
    assert recovered.json()["status"] == "FEASIBLE"
    history = client.get(
        "/api/v1/plans/history?plan_date=2026-08-29", headers=headers
    )
    assert [item["revision"] for item in history.json()] == [1, 2, 3]
