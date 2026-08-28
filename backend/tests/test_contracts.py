from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from pydantic import ValidationError as PydanticValidationError
from referencing import Registry, Resource

from lifeos.schemas import (
    AIPlanningRequest,
    AIPlanningResponse,
    CommandPayload,
    CommandRead,
    ErrorResponse,
    EventEnvelopeIn,
    FeatureRead,
    HeartbeatIn,
    ObservationIn,
    ObservationPayload,
    PlanVersionRead,
    RuntimeStateRead,
    TaskRead,
)

CONTRACT_DIR = Path(__file__).parents[2] / "contracts"


def load_contracts() -> tuple[dict[str, dict], Registry]:
    schemas = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in CONTRACT_DIR.glob("*.schema.json")
    }
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    return schemas, registry


def validate(schema_name: str, value: object) -> None:
    schemas, registry = load_contracts()
    Draft202012Validator(
        schemas[schema_name], registry=registry, format_checker=FormatChecker()
    ).validate(value)


def dumped(model: object) -> dict:
    return model.model_dump(mode="json")  # type: ignore[attr-defined,no-any-return]


def test_all_committed_schemas_are_valid_draft_2020_12() -> None:
    schemas, _ = load_contracts()
    assert len(schemas) == 11
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)


def test_frozen_contract_positive_examples() -> None:
    now = datetime(2026, 8, 29, 1, 0, tzinfo=UTC)
    task_id, device_id, session_id, decision_id = uuid4(), uuid4(), uuid4(), uuid4()
    task = TaskRead(
        task_id=task_id,
        title="English",
        status="READY",
        priority=4,
        mandatory=True,
        deadline=now + timedelta(hours=4),
        estimated_minutes=50,
        remaining_minutes=50,
        minimum_chunk_minutes=25,
        activity_profile="READING",
        allowed_apps=["msedge.exe"],
        blocked_apps=["cs2.exe"],
        created_at=now,
        updated_at=now,
        version=1,
    )
    observation = ObservationIn(
        observation_id=uuid4(),
        device_id=device_id,
        session_id=session_id,
        kind="ACTIVITY_SAMPLE",
        observed_at=now,
        received_at=now,
        idempotency_key=f"observation:{uuid4()}",
        payload=ObservationPayload(
            foreground_process="cs2.exe", window_title="Counter-Strike 2", idle_seconds=0
        ),
        reason_codes=["SENSOR_SAMPLE"],
    )
    features = FeatureRead(
        window_60_coverage_seconds=60,
        window_300_coverage_seconds=300,
        allowed_app_ratio_60s=0,
        blocked_app_ratio_60s=1,
        blocked_continuous_seconds=90,
        allowed_continuous_seconds=0,
        idle_seconds=0,
        sensor_conflict=False,
    )
    state = RuntimeStateRead(
        state_id=uuid4(),
        device_id=device_id,
        session_id=session_id,
        estimated_at=now,
        context="FOCUS",
        presence="PRESENT",
        engagement="OFF_TASK",
        session_state="RUNNING",
        device_role="SENSOR",
        confidence=0.95,
        reason_codes=["BLOCKED_APP_CONTINUOUS"],
        valid_until=now + timedelta(seconds=30),
        state_version=3,
        features=features,
    )
    command = CommandRead(
        command_id=uuid4(),
        target_device_id=device_id,
        session_id=session_id,
        decision_id=decision_id,
        role_lease_id=None,
        authorized_commitment_mode="STANDARD",
        command_type="WOULD_BLOCK",
        risk_level="SAFE",
        issued_at=now,
        not_before=now,
        expires_at=now + timedelta(minutes=10),
        required_state_version=3,
        idempotency_key=f"command:{uuid4()}",
        payload=CommandPayload(applications=["cs2.exe"], duration_seconds=600),
        dry_run=True,
        reason_codes=["WOULD_BLOCK_ONLY"],
    )
    plan = PlanVersionRead(
        plan_version_id=uuid4(),
        plan_date=date(2026, 8, 29),
        display_timezone="Asia/Shanghai",
        revision=1,
        trigger="DAY_STARTED",
        status="FEASIBLE",
        created_at=now,
        parameters={},
        blocks=[],
        conflicts=[],
        reason_codes=["PLAN_FEASIBLE"],
    )
    event = EventEnvelopeIn(
        event_id=uuid4(),
        event_type="TASK.CREATED",
        occurred_at=now,
        received_at=now,
        source="contract-test",
        entity_type="Task",
        entity_id=task_id,
        idempotency_key=f"event:{uuid4()}",
        payload={},
        reason_codes=["EVENT_ACCEPTED"],
    )
    heartbeat = HeartbeatIn(
        heartbeat_id=uuid4(),
        device_id=device_id,
        observed_at=now,
        agent_version="0.1.0",
        capabilities=["FOREGROUND_PROCESS", "IDLE_SECONDS"],
        latest_state_version=3,
        core_reachable=True,
        idempotency_key=f"heartbeat:{uuid4()}",
    )
    request = AIPlanningRequest(
        request_id=uuid4(),
        requested_at=now,
        current_time=now,
        runtime_state=dumped(state),
        current_plan=dumped(plan),
        current_block_id=None,
        future_blocks=[],
        today_progress={},
        unfinished_tasks=[dumped(task)],
        active_incident=None,
        policy_constraints={"dry_run": True},
        reason_codes=["CONTEXT_DEFAULT_BOUNDED"],
    )
    response = AIPlanningResponse(
        request_id=request.request_id,
        response_id=uuid4(),
        provider="mock",
        created_at=now,
        recommendation={"action": "USE_DETERMINISTIC_PLAN"},
        reason_codes=["AI_MOCK_RESPONSE"],
    )
    error = ErrorResponse(
        title="Conflict",
        status=409,
        detail="version mismatch",
        error_code="VERSION_CONFLICT",
        reason_codes=["VERSION_CONFLICT"],
        correlation_id=uuid4(),
    )
    lease = {
        "schema_version": "1.0",
        "lease_id": str(uuid4()),
        "device_id": str(device_id),
        "role": "PRIMARY_ENFORCEMENT",
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=30)).isoformat(),
        "revoked_at": None,
        "issued_for_state_version": 3,
        "version": 1,
        "reason_codes": ["LEASE_ISSUED"],
    }

    validate("task.schema.json", dumped(task))
    validate("observation.schema.json", dumped(observation))
    validate("runtime-state.schema.json", dumped(state))
    validate("command.schema.json", dumped(command))
    validate("plan-version.schema.json", dumped(plan))
    validate("event-envelope.schema.json", dumped(event))
    validate("device-heartbeat.schema.json", dumped(heartbeat))
    validate("role-lease.schema.json", lease)
    validate("ai-planning.schema.json", dumped(request))
    validate("ai-planning.schema.json", dumped(response))
    validate("error-response.schema.json", dumped(error))


def test_command_contract_forbids_arbitrary_shell_payload() -> None:
    now = datetime(2026, 8, 29, 1, 0, tzinfo=UTC)
    bad = {
        "schema_version": "1.0",
        "command_id": str(uuid4()),
        "target_device_id": str(uuid4()),
        "session_id": str(uuid4()),
        "decision_id": str(uuid4()),
        "role_lease_id": None,
        "authorized_commitment_mode": "STRICT",
        "command_type": "WOULD_BLOCK",
        "risk_level": "SAFE",
        "issued_at": now.isoformat(),
        "not_before": now.isoformat(),
        "expires_at": (now + timedelta(minutes=1)).isoformat(),
        "required_state_version": 1,
        "idempotency_key": f"command:{uuid4()}",
        "payload": {"shell": "Remove-Item -Recurse C:\\"},
        "dry_run": True,
        "reason_codes": ["WOULD_BLOCK_ONLY"],
    }
    with pytest.raises(ValidationError):
        validate("command.schema.json", bad)


@pytest.mark.parametrize(
    "missing_field",
    [
        "command_id",
        "target_device_id",
        "session_id",
        "decision_id",
        "expires_at",
        "required_state_version",
        "idempotency_key",
        "reason_codes",
    ],
)
def test_command_contract_rejects_missing_safety_fields(missing_field: str) -> None:
    now = datetime(2026, 8, 29, 1, 0, tzinfo=UTC)
    command = {
        "schema_version": "1.0",
        "command_id": str(uuid4()),
        "target_device_id": str(uuid4()),
        "session_id": str(uuid4()),
        "decision_id": str(uuid4()),
        "role_lease_id": None,
        "authorized_commitment_mode": "STANDARD",
        "command_type": "SHOW_NOTIFICATION",
        "risk_level": "SAFE",
        "issued_at": now.isoformat(),
        "not_before": now.isoformat(),
        "expires_at": (now + timedelta(minutes=1)).isoformat(),
        "required_state_version": 1,
        "idempotency_key": f"command:{uuid4()}",
        "payload": {"message": "safe notification"},
        "dry_run": True,
        "reason_codes": ["OFF_TASK_30_SECONDS"],
    }
    del command[missing_field]
    with pytest.raises(ValidationError):
        validate("command.schema.json", command)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [("required_state_version", 0), ("idempotency_key", "short"), ("reason_codes", [])],
)
def test_command_contract_rejects_invalid_safety_values(
    field: str, invalid_value: object
) -> None:
    now = datetime(2026, 8, 29, 1, 0, tzinfo=UTC)
    command = {
        "schema_version": "1.0",
        "command_id": str(uuid4()),
        "target_device_id": str(uuid4()),
        "session_id": str(uuid4()),
        "decision_id": str(uuid4()),
        "role_lease_id": None,
        "authorized_commitment_mode": "STANDARD",
        "command_type": "SHOW_NOTIFICATION",
        "risk_level": "SAFE",
        "issued_at": now.isoformat(),
        "not_before": now.isoformat(),
        "expires_at": (now + timedelta(minutes=1)).isoformat(),
        "required_state_version": 1,
        "idempotency_key": f"command:{uuid4()}",
        "payload": {"message": "safe notification"},
        "dry_run": True,
        "reason_codes": ["OFF_TASK_30_SECONDS"],
    }
    command[field] = invalid_value
    with pytest.raises(ValidationError):
        validate("command.schema.json", command)


def test_runtime_models_normalize_aware_timestamps_and_enforce_reason_code_contract() -> None:
    offset = timezone(timedelta(hours=8))
    event = EventEnvelopeIn(
        event_id=uuid4(),
        event_type="TASK.CREATED",
        occurred_at=datetime(2026, 8, 29, 9, 0, tzinfo=offset),
        source="contract-test",
        entity_type="Task",
        entity_id=uuid4(),
        idempotency_key=f"event:{uuid4()}",
        reason_codes=["EVENT_ACCEPTED"],
    )
    assert event.occurred_at == datetime(2026, 8, 29, 1, 0, tzinfo=UTC)
    assert dumped(event)["occurred_at"].endswith("Z")

    for reason_codes in (["lowercase"], ["EVENT_ACCEPTED", "EVENT_ACCEPTED"]):
        with pytest.raises(PydanticValidationError):
            EventEnvelopeIn(
                event_id=uuid4(),
                event_type="TASK.CREATED",
                occurred_at=datetime(2026, 8, 29, 1, 0, tzinfo=UTC),
                source="contract-test",
                entity_type="Task",
                entity_id=uuid4(),
                idempotency_key=f"event:{uuid4()}",
                reason_codes=reason_codes,
            )
