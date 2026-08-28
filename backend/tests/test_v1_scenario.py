from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from conftest import ApiHarness
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lifeos.ai import OfflineAIProvider
from lifeos.api import create_app
from lifeos.db import Database
from lifeos.models import (
    CommandRow,
    EventLedgerRow,
    PlanVersionRow,
    PolicyDecisionRow,
    RuntimeStateRow,
)


def _post_observation(
    harness: ApiHarness, *, device_id: str, session_id: str, process: str
) -> tuple[dict, dict]:
    observation_id = uuid4()
    body = {
        "observation_id": str(observation_id),
        "device_id": device_id,
        "session_id": session_id,
        "kind": "ACTIVITY_SAMPLE",
        "observed_at": harness.clock.now().isoformat(),
        "received_at": harness.clock.now().isoformat(),
        "idempotency_key": f"observation:{observation_id}",
        "payload": {
            "foreground_process": process,
            "window_title": "redacted-test-title",
            "idle_seconds": 0,
            "sensor_ok": True,
        },
        "reason_codes": ["SENSOR_SAMPLE"],
    }
    response = harness.client.post("/api/v1/observations", headers=harness.headers, json=body)
    assert response.status_code == 201, response.text
    return response.json(), body


def test_named_v1_closed_loop_scenario_and_restart(api_harness: ApiHarness) -> None:
    client, headers, clock = (
        api_harness.client,
        api_harness.headers,
        api_harness.clock,
    )
    device = client.post(
        "/api/v1/devices",
        headers=headers,
        json={
            "name": "Study PC",
            "device_type": "WINDOWS",
            "capabilities": ["FOREGROUND_PROCESS", "IDLE_SECONDS", "LOCAL_NOTIFICATION"],
        },
    ).json()

    for title, start_at, end_at in (
        ("Class 1", "2026-08-29T00:00:00Z", "2026-08-29T01:00:00Z"),
        ("Class 2", "2026-08-29T02:00:00Z", "2026-08-29T03:00:00Z"),
        ("Class 3", "2026-08-29T06:00:00Z", "2026-08-29T07:00:00Z"),
    ):
        response = client.post(
            "/api/v1/fixed-events",
            headers=headers,
            json={"title": title, "start_at": start_at, "end_at": end_at},
        )
        assert response.status_code == 201

    for task in (
        {
            "title": "English",
            "estimated_minutes": 50,
            "mandatory": True,
            "priority": 4,
            "deadline": "2026-08-29T08:00:00Z",
            "activity_profile": "WRITING",
            "allowed_apps": ["winword.exe"],
            "blocked_apps": ["cs2.exe"],
        },
        {
            "title": "Research",
            "estimated_minutes": 100,
            "mandatory": True,
            "priority": 5,
            "deadline": "2026-08-29T10:00:00Z",
            "activity_profile": "CODING",
            "allowed_apps": ["code.exe"],
            "blocked_apps": ["cs2.exe"],
        },
    ):
        assert client.post("/api/v1/tasks", headers=headers, json=task).status_code == 201

    initial = client.post(
        "/api/v1/plans/generate",
        headers=headers,
        json={"plan_date": "2026-08-29", "now": clock.now().isoformat()},
    )
    assert initial.status_code == 201
    plan_v1 = initial.json()
    assert plan_v1["revision"] == 1
    assert plan_v1["status"] == "FEASIBLE"
    assert len([block for block in plan_v1["blocks"] if block["kind"] == "FIXED_EVENT"]) == 3
    assert any(block["kind"] == "BREAK" for block in plan_v1["blocks"])
    assert any(block["kind"] == "BUFFER" for block in plan_v1["blocks"])

    clock.value += timedelta(minutes=30)
    late_event_id = uuid4()
    late_event_body = {
        "event_id": str(late_event_id),
        "event_type": "AVAILABLE_TIME_CHANGED",
        "occurred_at": clock.now().isoformat(),
        "received_at": clock.now().isoformat(),
        "source": "scenario",
        "entity_type": "PlanVersion",
        "entity_id": plan_v1["plan_version_id"],
        "idempotency_key": f"late-arrival:{late_event_id}",
        "payload": {
            "plan_date": "2026-08-29",
            "display_timezone": "Asia/Shanghai",
            "available_start_local": "07:30",
        },
        "reason_codes": ["AVAILABLE_TIME_CHANGED", "USER_ARRIVED_LATE"],
    }
    late = client.post(
        "/api/v1/events",
        headers=headers,
        json=late_event_body,
    )
    assert late.status_code == 202, late.text
    assert late.json()["duplicate"] is False
    assert len(late.json()["side_effect_ids"]) == 1
    plan_v2_response = client.get(
        "/api/v1/plans/current?plan_date=2026-08-29", headers=headers
    )
    assert plan_v2_response.status_code == 200
    plan_v2 = plan_v2_response.json()
    assert late.json()["side_effect_ids"] == [plan_v2["plan_version_id"]]
    assert plan_v2["revision"] == 2
    assert plan_v2["based_on_plan_version_id"] == plan_v1["plan_version_id"]
    history = client.get("/api/v1/plans/history?plan_date=2026-08-29", headers=headers).json()
    assert history[0] == plan_v1

    task_block = next(
        block
        for block in plan_v2["blocks"]
        if block["kind"] == "TASK" and block["start_at"] >= clock.now().isoformat()
    )
    started = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={
            "block_id": task_block["block_id"],
            "device_id": device["device_id"],
            "commitment_mode": "STANDARD",
            "expected_plan_revision": 2,
        },
    )
    assert started.status_code == 201
    execution = started.json()
    assert execution["dry_run"] is True

    allowed_process = "code.exe" if task_block["title"] == "Research" else "winword.exe"
    latest_state = None
    for _ in range(21):
        latest_state, _ = _post_observation(
            api_harness,
            device_id=device["device_id"],
            session_id=execution["session_id"],
            process=allowed_process,
        )
        clock.value += timedelta(seconds=15)
    assert latest_state is not None and latest_state["engagement"] == "ON_TASK"

    last_body: dict | None = None
    for _ in range(21):
        latest_state, last_body = _post_observation(
            api_harness,
            device_id=device["device_id"],
            session_id=execution["session_id"],
            process="cs2.exe",
        )
        clock.value += timedelta(seconds=15)
    assert latest_state["engagement"] == "OFF_TASK"
    assert latest_state["confidence"] >= 0.65
    assert "OFF_TASK_HYSTERESIS_ENTER" in latest_state["reason_codes"] or (
        "OFF_TASK_HYSTERESIS_HOLD" in latest_state["reason_codes"]
    )

    with api_harness.database.session() as db:
        actions = set(
            db.scalars(
                select(PolicyDecisionRow.action).where(
                    PolicyDecisionRow.session_id == UUID(execution["session_id"])
                )
            ).all()
        )
        commands = db.scalars(
            select(CommandRow).where(
                CommandRow.session_id == UUID(execution["session_id"])
            )
        ).all()
    assert {"NOTIFY", "CONFIRM", "WOULD_BLOCK"}.issubset(actions)
    assert any(command.command_type == "WOULD_BLOCK" for command in commands)
    assert all(command.dry_run and command.risk_level == "SAFE" for command in commands)

    envelope = client.get(f"/api/v1/devices/{device['device_id']}/commands", headers=headers).json()
    assert envelope["latest_state_version"] == latest_state["state_version"]
    would_block = next(
        command for command in envelope["commands"] if command["command_type"] == "WOULD_BLOCK"
    )
    assert would_block["payload"]["duration_seconds"] == 600
    assert "WOULD_BLOCK_ONLY" in would_block["reason_codes"]

    assert last_body is not None
    with api_harness.database.session() as db:
        counts_before = (
            db.scalar(select(func.count()).select_from(RuntimeStateRow)),
            db.scalar(select(func.count()).select_from(PolicyDecisionRow)),
            db.scalar(select(func.count()).select_from(CommandRow)),
        )
    replay = client.post("/api/v1/observations", headers=headers, json=last_body)
    assert replay.status_code == 201
    assert replay.json()["state_version"] == latest_state["state_version"]
    with api_harness.database.session() as db:
        counts_after = (
            db.scalar(select(func.count()).select_from(RuntimeStateRow)),
            db.scalar(select(func.count()).select_from(PolicyDecisionRow)),
            db.scalar(select(func.count()).select_from(CommandRow)),
        )
    assert counts_after == counts_before

    session_now = client.get(f"/api/v1/sessions/{execution['session_id']}", headers=headers).json()
    break_result = client.post(
        f"/api/v1/sessions/{execution['session_id']}/break",
        headers=headers,
        json={"expected_version": session_now["version"], "duration_minutes": 10},
    )
    assert break_result.status_code == 201, break_result.text
    break_data = break_result.json()
    assert break_data["session"]["session_state"] == "PAUSED"
    assert break_data["plan"]["revision"] == 3
    assert break_data["plan"]["trigger"] == "USER_REPORTED_FATIGUE"
    user_break = next(
        block
        for block in break_data["plan"]["blocks"]
        if "USER_REPORTED_FATIGUE" in block["reason_codes"]
    )
    assert (
        datetime.fromisoformat(user_break["end_at"])
        - datetime.fromisoformat(user_break["start_at"])
    ).total_seconds() == 600

    release_envelope = client.get(
        f"/api/v1/devices/{device['device_id']}/commands", headers=headers
    ).json()
    release = next(
        command
        for command in release_envelope["commands"]
        if command["command_type"] == "RELEASE_ALL"
    )
    ack_id = uuid4()
    ack = client.post(
        "/api/v1/commands/acks",
        headers=headers,
        json={
            "ack_id": str(ack_id),
            "command_id": release["command_id"],
            "device_id": device["device_id"],
            "acknowledged_at": clock.now().isoformat(),
            "status": "EXECUTED",
            "observed_state_version": release["required_state_version"],
            "idempotency_key": f"ack:{ack_id}",
            "details": {"outcome": "RELEASED"},
            "reason_codes": ["USER_REPORTED_FATIGUE"],
        },
    )
    assert ack.status_code == 200

    emergency_key = f"emergency:{uuid4()}"
    emergency_body = {
        "idempotency_key": emergency_key,
        "reason": "user pressed Emergency Release in the scenario",
    }
    emergency = client.post(
        f"/api/v1/sessions/{execution['session_id']}/emergency-release",
        headers=headers,
        json=emergency_body,
    )
    assert emergency.status_code == 200, emergency.text
    assert emergency.json()["session_state"] == "INTERRUPTED"
    assert emergency.json()["emergency_released_at"] is not None
    emergency_replay = client.post(
        f"/api/v1/sessions/{execution['session_id']}/emergency-release",
        headers=headers,
        json=emergency_body,
    )
    assert emergency_replay.status_code == 200
    assert emergency_replay.json()["version"] == emergency.json()["version"]
    emergency_conflict = client.post(
        f"/api/v1/sessions/{execution['session_id']}/emergency-release",
        headers=headers,
        json={**emergency_body, "reason": "different input with the same key"},
    )
    assert emergency_conflict.status_code == 409

    emergency_commands = client.get(
        f"/api/v1/devices/{device['device_id']}/commands", headers=headers
    ).json()
    emergency_release = next(
        command
        for command in emergency_commands["commands"]
        if command["command_type"] == "RELEASE_ALL"
        and "EMERGENCY_RELEASED" in command["reason_codes"]
    )
    emergency_ack_id = uuid4()
    emergency_ack = client.post(
        "/api/v1/commands/acks",
        headers=headers,
        json={
            "ack_id": str(emergency_ack_id),
            "command_id": emergency_release["command_id"],
            "device_id": device["device_id"],
            "acknowledged_at": clock.now().isoformat(),
            "status": "EXECUTED",
            "observed_state_version": emergency_release["required_state_version"],
            "idempotency_key": f"ack:{emergency_ack_id}",
            "details": {"outcome": "EMERGENCY_RELEASED"},
            "reason_codes": ["EMERGENCY_RELEASED"],
        },
    )
    assert emergency_ack.status_code == 200

    with api_harness.database.session() as db:
        before_restart = {
            "events": db.scalar(select(func.count()).select_from(EventLedgerRow)),
            "plans": db.scalar(select(func.count()).select_from(PlanVersionRow)),
        }

    api_harness.client.close()
    api_harness.database.dispose()
    restarted_db = Database(api_harness.database_url)
    restarted_client = TestClient(
        create_app(
            settings=api_harness.settings,
            database=restarted_db,
            clock=api_harness.clock,
            ai_provider=OfflineAIProvider(),
        )
    )
    try:
        recovered_plan = restarted_client.get(
            "/api/v1/plans/current?plan_date=2026-08-29", headers=headers
        )
        recovered_session = restarted_client.get(
            f"/api/v1/sessions/{execution['session_id']}", headers=headers
        )
        remaining_commands = restarted_client.get(
            f"/api/v1/devices/{device['device_id']}/commands", headers=headers
        )
        assert recovered_plan.status_code == recovered_session.status_code == 200
        assert recovered_plan.json()["plan_version_id"] == break_data["plan"]["plan_version_id"]
        assert recovered_session.json()["session_state"] == "INTERRUPTED"
        assert remaining_commands.json()["commands"] == []
        late_replay = restarted_client.post(
            "/api/v1/events", headers=headers, json=late_event_body
        )
        assert late_replay.status_code == 202
        assert late_replay.json()["duplicate"] is True
        assert late_replay.json()["side_effect_ids"] == [plan_v2["plan_version_id"]]
        with restarted_db.session() as db:
            after_restart = {
                "events": db.scalar(select(func.count()).select_from(EventLedgerRow)),
                "plans": db.scalar(select(func.count()).select_from(PlanVersionRow)),
            }
        assert after_restart == before_restart

        ai_request_id = uuid4()
        offline_ai = restarted_client.post(
            "/api/v1/ai/jobs",
            headers=headers,
            json={
                "idempotency_key": f"ai-job:{uuid4()}",
                "request": {
                    "request_id": str(ai_request_id),
                    "requested_at": clock.now().isoformat(),
                    "current_time": clock.now().isoformat(),
                    "runtime_state": latest_state,
                    "current_plan": recovered_plan.json(),
                    "current_block_id": None,
                    "future_blocks": recovered_plan.json()["blocks"][:3],
                    "today_progress": {},
                    "unfinished_tasks": [],
                    "active_incident": {"type": "AI_OFFLINE"},
                    "policy_constraints": {"dry_run": True},
                    "reason_codes": ["CONTEXT_DEFAULT_BOUNDED"],
                },
            },
        )
        assert offline_ai.status_code == 201
        assert offline_ai.json()["status"] == "FAILED"
        assert offline_ai.json()["fallback_used"] is True
        assert (
            restarted_client.get(
                "/api/v1/plans/current?plan_date=2026-08-29", headers=headers
            ).json()["plan_version_id"]
            == break_data["plan"]["plan_version_id"]
        )
    finally:
        restarted_client.close()
        restarted_db.dispose()
