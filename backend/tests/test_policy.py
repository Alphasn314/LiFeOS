from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from lifeos.policy import evaluate_policy
from lifeos.schemas import FeatureRead, RuntimeStateRead

NOW = datetime(2026, 8, 28, 19, 0, tzinfo=UTC)
DEVICE_ID = UUID(int=1001)
SESSION_ID = UUID(int=1002)


def runtime_state(
    *,
    engagement: str = "OFF_TASK",
    confidence: float = 0.95,
    session_state: str = "RUNNING",
) -> RuntimeStateRead:
    return RuntimeStateRead(
        state_id=UUID(int=1003),
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        estimated_at=NOW,
        context="FOCUS",
        presence="PRESENT",
        engagement=engagement,
        session_state=session_state,
        device_role="PRIMARY_INTERACTION",
        confidence=confidence,
        reason_codes=["OFF_TASK_HYSTERESIS_ENTER"],
        valid_until=NOW + timedelta(seconds=30),
        state_version=7,
        features=FeatureRead(
            window_60_coverage_seconds=60,
            window_300_coverage_seconds=90,
            allowed_app_ratio_60s=0,
            blocked_app_ratio_60s=1,
            blocked_continuous_seconds=90,
            allowed_continuous_seconds=0,
            idle_seconds=0,
            sensor_conflict=False,
        ),
    )


def test_standard_policy_progresses_to_typed_dry_run_would_block() -> None:
    state = runtime_state()

    notification = evaluate_policy(
        state,
        commitment_mode="STANDARD",
        evaluated_at=NOW,
        off_task_seconds=45,
    )
    prompt = evaluate_policy(
        state,
        commitment_mode="STANDARD",
        evaluated_at=NOW,
        off_task_seconds=120,
    )
    would_block = evaluate_policy(
        state,
        commitment_mode="STANDARD",
        evaluated_at=NOW,
        off_task_seconds=181,
        allowed_blocklist=["CS2.EXE"],
    )

    assert notification.command is not None
    assert notification.command.command_type == "SHOW_NOTIFICATION"
    assert prompt.command is not None
    assert prompt.command.command_type == "SHOW_CONFIRMATION"
    assert would_block.decision.level == 3
    assert would_block.command is not None
    assert would_block.command.command_type == "WOULD_BLOCK"
    assert would_block.command.risk_level == "SAFE"
    assert would_block.command.role_lease_id is None
    assert would_block.command.dry_run is True
    assert would_block.command.payload.duration_seconds == 600
    assert would_block.command.payload.applications == ["cs2.exe"]
    assert would_block.command.required_state_version == state.state_version


def test_same_state_and_level_have_same_semantic_idempotency() -> None:
    first = evaluate_policy(
        runtime_state(),
        commitment_mode="STANDARD",
        evaluated_at=NOW,
        off_task_seconds=181,
        allowed_blocklist=["cs2.exe"],
    )
    second = evaluate_policy(
        runtime_state(),
        commitment_mode="STANDARD",
        evaluated_at=NOW + timedelta(seconds=5),
        off_task_seconds=240,
        allowed_blocklist=["cs2.exe"],
    )

    assert first.decision.decision_id == second.decision.decision_id
    assert first.command is not None and second.command is not None
    assert first.command.command_id == second.command.command_id
    assert first.command.idempotency_key == second.command.idempotency_key
    assert first.command.model_dump(mode="json") == second.command.model_dump(mode="json")


def test_unknown_or_low_confidence_state_never_escalates() -> None:
    result = evaluate_policy(
        runtime_state(engagement="UNKNOWN", confidence=0.4),
        commitment_mode="STRICT",
        evaluated_at=NOW,
        off_task_seconds=600,
        ignored_prompts=10,
        allowed_blocklist=["cs2.exe"],
    )

    assert result.decision.level == 0
    assert result.command is None
    assert "ENGAGEMENT_UNKNOWN" in result.decision.reason_codes


def test_advisory_never_creates_a_block_command() -> None:
    result = evaluate_policy(
        runtime_state(),
        commitment_mode="ADVISORY",
        evaluated_at=NOW,
        off_task_seconds=600,
        ignored_prompts=10,
        allowed_blocklist=["cs2.exe"],
    )

    assert result.decision.level == 2
    assert result.command is not None
    assert result.command.command_type == "SHOW_NOTIFICATION"
    assert result.command.risk_level == "SAFE"


def test_strict_recovery_and_level_five_remain_safe_dry_run_outputs() -> None:
    recovery = evaluate_policy(
        runtime_state(),
        commitment_mode="STRICT",
        evaluated_at=NOW,
        off_task_seconds=181,
        ignored_prompts=2,
        allowed_blocklist=["cs2.exe"],
    )
    interrupted = evaluate_policy(
        runtime_state(),
        commitment_mode="STRICT",
        evaluated_at=NOW,
        off_task_seconds=181,
        ignored_prompts=3,
        allowed_blocklist=["cs2.exe"],
    )

    assert recovery.decision.level == 4
    assert recovery.command is not None
    assert recovery.command.command_type == "WOULD_BLOCK"
    assert recovery.command.payload.duration_seconds == 900
    assert recovery.command.dry_run is True
    assert interrupted.decision.level == 5
    assert interrupted.command is not None
    assert interrupted.command.command_type == "SHOW_NOTIFICATION"
