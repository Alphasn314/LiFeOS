from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from lifeos.runtime import (
    build_feature_snapshot,
    can_transition_session,
    reduce_runtime_state,
)
from lifeos.schemas import (
    Context,
    DeviceRole,
    ObservationIn,
    ObservationKind,
    ObservationPayload,
    SessionState,
)

NOW = datetime(2026, 8, 28, 18, 0, tzinfo=UTC)
DEVICE_ID = UUID(int=501)
SESSION_ID = UUID(int=502)


def observation(
    identifier: int,
    seconds_ago: int,
    *,
    process: str | None = None,
    locked: bool | None = None,
) -> ObservationIn:
    kind = ObservationKind.LOCK_STATE if locked is not None else ObservationKind.ACTIVITY_SAMPLE
    at = NOW - timedelta(seconds=seconds_ago)
    return ObservationIn(
        observation_id=UUID(int=identifier),
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        kind=kind,
        observed_at=at,
        received_at=at,
        idempotency_key=f"observation-{identifier}",
        payload=ObservationPayload(foreground_process=process, is_locked=locked),
    )


def test_ninety_seconds_of_cs2_enters_off_task() -> None:
    samples = [
        observation(600 + index, seconds_ago, process="cs2.exe")
        for index, seconds_ago in enumerate((90, 75, 60, 45, 30, 15))
    ]
    features = build_feature_snapshot(
        samples,
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        evaluated_at=NOW,
        allowed_apps=["code.exe"],
        blocked_apps=["cs2.exe"],
    )
    state = reduce_runtime_state(
        features,
        estimated_at=NOW,
        context=Context.FOCUS,
        session_state=SessionState.RUNNING,
        device_role=DeviceRole.PRIMARY_INTERACTION,
        state_version=1,
        idle_tolerance_seconds=300,
    )

    assert features.blocked_app_ratio_60s == 1.0
    assert features.blocked_continuous_seconds == 90
    assert state.engagement == "OFF_TASK"
    assert "OFF_TASK_HYSTERESIS_ENTER" in state.reason_codes
    assert state.confidence == 1.0


def test_lock_is_unknown_and_interrupts_without_claiming_absence() -> None:
    features = build_feature_snapshot(
        [observation(701, 0, locked=True)],
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        evaluated_at=NOW,
        allowed_apps=["code.exe"],
        blocked_apps=["cs2.exe"],
    )
    state = reduce_runtime_state(
        features,
        estimated_at=NOW,
        context=Context.FOCUS,
        session_state=SessionState.RUNNING,
        device_role=DeviceRole.SENSOR,
        state_version=1,
        idle_tolerance_seconds=300,
    )

    assert state.presence == "UNKNOWN"
    assert state.engagement == "UNKNOWN"
    assert state.session_state == "INTERRUPTED"
    assert "PC_LOCKED" in state.reason_codes


def test_off_task_exits_after_thirty_seconds_of_allowed_activity() -> None:
    blocked = [
        observation(800 + index, seconds_ago, process="cs2.exe")
        for index, seconds_ago in enumerate((90, 75, 60, 45, 30, 15))
    ]
    blocked_features = build_feature_snapshot(
        blocked,
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        evaluated_at=NOW,
        allowed_apps=["code.exe"],
        blocked_apps=["cs2.exe"],
    )
    previous = reduce_runtime_state(
        blocked_features,
        estimated_at=NOW,
        context=Context.FOCUS,
        session_state=SessionState.RUNNING,
        device_role=DeviceRole.SENSOR,
        state_version=1,
        idle_tolerance_seconds=300,
    )
    later = NOW + timedelta(seconds=45)
    allowed_samples = [
        ObservationIn(
            observation_id=UUID(int=900 + index),
            device_id=DEVICE_ID,
            session_id=SESSION_ID,
            kind=ObservationKind.ACTIVITY_SAMPLE,
            observed_at=later - timedelta(seconds=seconds_ago),
            received_at=later - timedelta(seconds=seconds_ago),
            idempotency_key=f"allowed-observation-{index}",
            payload=ObservationPayload(foreground_process="code.exe"),
        )
        for index, seconds_ago in enumerate((45, 30, 15))
    ]
    allowed_features = build_feature_snapshot(
        allowed_samples,
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        evaluated_at=later,
        allowed_apps=["code.exe"],
        blocked_apps=["cs2.exe"],
    )
    state = reduce_runtime_state(
        allowed_features,
        estimated_at=later,
        context=Context.FOCUS,
        session_state=SessionState.RUNNING,
        device_role=DeviceRole.SENSOR,
        state_version=2,
        idle_tolerance_seconds=300,
        previous_state=previous,
    )

    assert allowed_features.allowed_continuous_seconds == 45
    assert state.engagement == "ON_TASK"
    assert "ALLOWED_APP_CONTINUOUS_EXIT" in state.reason_codes


def test_session_transition_graph_rejects_terminal_revival() -> None:
    assert can_transition_session(SessionState.PLANNED, SessionState.DUE)
    assert can_transition_session(SessionState.RUNNING, SessionState.PAUSED)
    assert not can_transition_session(SessionState.COMPLETED, SessionState.RUNNING)


def test_stale_candidate_window_does_not_satisfy_consecutive_hysteresis() -> None:
    samples = [
        observation(950 + index, seconds_ago, process="cs2.exe")
        for index, seconds_ago in enumerate((60, 45, 30, 15))
    ]
    features = build_feature_snapshot(
        samples,
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        evaluated_at=NOW,
        allowed_apps=["code.exe"],
        blocked_apps=["cs2.exe"],
    )
    stale_previous = replace(features, evaluated_at=NOW - timedelta(minutes=5))

    state = reduce_runtime_state(
        features,
        estimated_at=NOW,
        context=Context.FOCUS,
        session_state=SessionState.RUNNING,
        device_role=DeviceRole.SENSOR,
        state_version=1,
        idle_tolerance_seconds=300,
        previous_features=stale_previous,
    )

    assert features.blocked_continuous_seconds == 60
    assert state.engagement == "UNKNOWN"


def test_short_window_requires_full_forty_five_seconds_of_coverage() -> None:
    insufficient = build_feature_snapshot(
        [
            observation(980 + index, seconds_ago, process="code.exe")
            for index, seconds_ago in enumerate((44, 29, 14))
        ],
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        evaluated_at=NOW,
        allowed_apps=["code.exe"],
        blocked_apps=["cs2.exe"],
    )
    insufficient_state = reduce_runtime_state(
        insufficient,
        estimated_at=NOW,
        context=Context.FOCUS,
        session_state=SessionState.RUNNING,
        device_role=DeviceRole.SENSOR,
        state_version=1,
        idle_tolerance_seconds=300,
    )
    assert insufficient.window_60_coverage_seconds == 44
    assert insufficient.confidence > 0.65
    assert insufficient_state.engagement == "UNKNOWN"
    assert "SENSOR_DATA_INSUFFICIENT" in insufficient_state.reason_codes

    sufficient = build_feature_snapshot(
        [
            observation(990 + index, seconds_ago, process="code.exe")
            for index, seconds_ago in enumerate((45, 30, 15))
        ],
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        evaluated_at=NOW,
        allowed_apps=["code.exe"],
        blocked_apps=["cs2.exe"],
    )
    sufficient_state = reduce_runtime_state(
        sufficient,
        estimated_at=NOW,
        context=Context.FOCUS,
        session_state=SessionState.RUNNING,
        device_role=DeviceRole.SENSOR,
        state_version=1,
        idle_tolerance_seconds=300,
    )
    assert sufficient.window_60_coverage_seconds == 45
    assert sufficient_state.engagement == "ON_TASK"
