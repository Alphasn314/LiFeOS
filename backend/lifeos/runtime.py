from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PureWindowsPath
from uuid import UUID, uuid5

from lifeos.schemas import (
    BlockKind,
    Context,
    DeviceRole,
    Engagement,
    FeatureRead,
    ObservationIn,
    ObservationKind,
    Presence,
    RuntimeStateRead,
    ScheduleBlockRead,
    SessionState,
    utc,
)

FEATURE_ALGORITHM_VERSION = "activity-features-v1"
_FEATURE_NAMESPACE = UUID("492fc23e-e56b-483f-9e4c-90616e131eba")
_TERMINAL_SESSION_STATES = {
    SessionState.COMPLETED,
    SessionState.ABORTED,
    SessionState.MISSED,
}
_SESSION_TRANSITIONS: dict[str, set[str]] = {
    SessionState.PLANNED: {SessionState.DUE, SessionState.MISSED, SessionState.ABORTED},
    SessionState.DUE: {SessionState.STARTING, SessionState.MISSED, SessionState.ABORTED},
    SessionState.STARTING: {SessionState.RUNNING, SessionState.ABORTED},
    SessionState.RUNNING: {
        SessionState.PAUSED,
        SessionState.INTERRUPTED,
        SessionState.RECOVERY,
        SessionState.COMPLETED,
        SessionState.ABORTED,
    },
    SessionState.PAUSED: {
        SessionState.RUNNING,
        SessionState.INTERRUPTED,
        SessionState.ABORTED,
    },
    SessionState.INTERRUPTED: {
        SessionState.RUNNING,
        SessionState.RECOVERY,
        SessionState.ABORTED,
    },
    SessionState.RECOVERY: {
        SessionState.RUNNING,
        SessionState.INTERRUPTED,
        SessionState.ABORTED,
    },
    SessionState.COMPLETED: set(),
    SessionState.ABORTED: set(),
    SessionState.MISSED: set(),
}


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    feature_id: UUID
    device_id: UUID
    session_id: UUID | None
    evaluated_at: datetime
    window_60_coverage_seconds: float
    window_300_coverage_seconds: float
    allowed_app_ratio_60s: float
    blocked_app_ratio_60s: float
    blocked_continuous_seconds: float
    allowed_continuous_seconds: float
    idle_seconds: int | None
    sensor_conflict: bool
    sensor_failed: bool
    is_locked: bool
    manual_presence: str | None
    manual_presence_continuous_seconds: float
    confidence: float
    off_task_candidate: bool
    on_task_candidate: bool
    reason_codes: tuple[str, ...]
    algorithm_version: str = FEATURE_ALGORITHM_VERSION

    def contract_features(self) -> FeatureRead:
        return FeatureRead(
            window_60_coverage_seconds=self.window_60_coverage_seconds,
            window_300_coverage_seconds=self.window_300_coverage_seconds,
            allowed_app_ratio_60s=self.allowed_app_ratio_60s,
            blocked_app_ratio_60s=self.blocked_app_ratio_60s,
            blocked_continuous_seconds=self.blocked_continuous_seconds,
            allowed_continuous_seconds=self.allowed_continuous_seconds,
            idle_seconds=self.idle_seconds,
            sensor_conflict=self.sensor_conflict,
        )


def build_feature_snapshot(
    observations: Sequence[ObservationIn],
    *,
    device_id: UUID,
    session_id: UUID | None,
    evaluated_at: datetime,
    allowed_apps: Sequence[str],
    blocked_apps: Sequence[str],
    sample_hold_seconds: int = 15,
) -> FeatureSnapshot:
    """Turn point observations into bounded 60/300-second activity evidence."""
    if sample_hold_seconds <= 0:
        raise ValueError("sample_hold_seconds must be positive")
    now = utc(evaluated_at)
    allowed = {_process_name(item) for item in allowed_apps}
    blocked = {_process_name(item) for item in blocked_apps}
    if allowed & blocked:
        raise ValueError("allowed_apps and blocked_apps must be disjoint")

    ordered = sorted(
        (item for item in observations if utc(item.observed_at) <= now),
        key=lambda item: (utc(item.observed_at), str(item.observation_id)),
    )
    for item in ordered:
        if item.device_id != device_id or item.session_id != session_id:
            raise ValueError("all observations must match the requested device/session scope")

    activity = [item for item in ordered if item.kind == ObservationKind.ACTIVITY_SAMPLE]
    segments = _activity_segments(activity, now, sample_hold_seconds, allowed, blocked)
    coverage_60, allowed_60, blocked_60 = _window_totals(segments, now, 60)
    coverage_300, _, _ = _window_totals(segments, now, 300)
    allowed_continuous = _continuous_seconds(segments, now, "ALLOWED")
    blocked_continuous = _continuous_seconds(segments, now, "BLOCKED")

    recent = [item for item in ordered if utc(item.observed_at) >= now - timedelta(seconds=300)]
    idle_seconds = _latest_payload_value(recent, "idle_seconds")
    is_locked = bool(_latest_payload_value(recent, "is_locked", False))
    manual_presence = _latest_payload_value(recent, "manual_presence")
    manual_duration = _manual_presence_duration(recent, now, manual_presence)
    sensor_ok = _latest_payload_value(recent, "sensor_ok")
    sensor_failed = sensor_ok is False
    sensor_conflict = _sensor_conflict(recent)

    allowed_ratio = allowed_60 / coverage_60 if coverage_60 else 0.0
    blocked_ratio = blocked_60 / coverage_60 if coverage_60 else 0.0
    off_task_candidate = blocked_continuous >= 30 or blocked_ratio >= 0.60
    on_task_candidate = allowed_ratio >= 0.75
    confidence = min(1.0, coverage_60 / 60)
    if is_locked:
        confidence = 1.0
    if sensor_failed or sensor_conflict:
        confidence = 0.0

    reasons: list[str] = []
    if sensor_conflict:
        reasons.append("SENSOR_CONFLICT")
    if sensor_failed:
        reasons.append("SENSOR_FAILURE")
    if is_locked:
        reasons.append("PC_LOCKED")
    if coverage_60 < 45 and not is_locked:
        reasons.append("SENSOR_DATA_INSUFFICIENT")
    if blocked_continuous >= 30:
        reasons.append("BLOCKED_APP_CONTINUOUS")
    if blocked_ratio >= 0.60:
        reasons.append("BLOCKED_APP_RATIO")
    if allowed_ratio >= 0.75:
        reasons.append("ALLOWED_APP_RATIO")
    if not reasons:
        reasons.append("SENSOR_DATA_INSUFFICIENT")

    evidence_parts = [str(device_id), str(session_id), now.isoformat()]
    evidence_parts.extend(str(item.observation_id) for item in ordered)
    evidence_key = "|".join(evidence_parts)
    return FeatureSnapshot(
        feature_id=uuid5(_FEATURE_NAMESPACE, evidence_key),
        device_id=device_id,
        session_id=session_id,
        evaluated_at=now,
        window_60_coverage_seconds=round(coverage_60, 6),
        window_300_coverage_seconds=round(coverage_300, 6),
        allowed_app_ratio_60s=round(allowed_ratio, 6),
        blocked_app_ratio_60s=round(blocked_ratio, 6),
        blocked_continuous_seconds=round(blocked_continuous, 6),
        allowed_continuous_seconds=round(allowed_continuous, 6),
        idle_seconds=idle_seconds if isinstance(idle_seconds, int) else None,
        sensor_conflict=sensor_conflict,
        sensor_failed=sensor_failed,
        is_locked=is_locked,
        manual_presence=str(manual_presence) if manual_presence is not None else None,
        manual_presence_continuous_seconds=manual_duration,
        confidence=round(confidence, 6),
        off_task_candidate=off_task_candidate,
        on_task_candidate=on_task_candidate,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def reduce_runtime_state(
    features: FeatureSnapshot,
    *,
    estimated_at: datetime,
    context: Context,
    session_state: SessionState,
    device_role: DeviceRole,
    state_version: int,
    idle_tolerance_seconds: int,
    previous_state: RuntimeStateRead | None = None,
    previous_features: FeatureSnapshot | None = None,
    valid_for_seconds: int = 30,
) -> RuntimeStateRead:
    """Reduce one feature snapshot using uncertainty-first engagement hysteresis."""
    if state_version < 1:
        raise ValueError("state_version must be positive")
    if idle_tolerance_seconds <= 0 or valid_for_seconds <= 0:
        raise ValueError("runtime thresholds must be positive")
    if previous_state is not None:
        scope_changed = (
            previous_state.device_id != features.device_id
            or previous_state.session_id != features.session_id
        )
        if scope_changed:
            raise ValueError("previous_state belongs to a different device/session scope")
        if state_version <= previous_state.state_version:
            raise ValueError("state_version must increase monotonically")
    if previous_features is not None and (
        previous_features.device_id != features.device_id
        or previous_features.session_id != features.session_id
    ):
        raise ValueError("previous_features belongs to a different device/session scope")

    now = utc(estimated_at)
    reasons: list[str] = []
    effective_session_state = str(session_state)
    presence = Presence.UNKNOWN
    engagement = Engagement.UNKNOWN

    if features.is_locked:
        effective_session_state = _interrupt(str(session_state))
        reasons.append("PC_LOCKED")
    elif features.sensor_failed or features.sensor_conflict:
        reasons.append("SENSOR_FAILURE" if features.sensor_failed else "SENSOR_CONFLICT")
    elif features.window_60_coverage_seconds < 45:
        reasons.append("SENSOR_DATA_INSUFFICIENT")
    elif features.confidence < 0.65:
        reasons.extend(["CONFIDENCE_TOO_LOW", "SENSOR_DATA_INSUFFICIENT"])
    else:
        if features.manual_presence == Presence.PRESENT:
            presence = Presence.PRESENT
            reasons.append("MANUAL_PRESENT")
        elif features.manual_presence == Presence.ABSENT:
            presence = Presence.ABSENT
            reasons.append("MANUAL_ABSENT")
            if features.manual_presence_continuous_seconds >= 90:
                effective_session_state = _interrupt(str(session_state))
        else:
            presence = Presence.PRESENT

        if presence == Presence.ABSENT:
            engagement = Engagement.UNKNOWN
        elif features.idle_seconds is not None and features.idle_seconds > idle_tolerance_seconds:
            engagement = Engagement.IDLE
            reasons.append("IDLE_TOLERANCE_EXCEEDED")
        else:
            previous_engagement = str(previous_state.engagement) if previous_state else None
            consecutive_candidate = _is_consecutive_candidate(features, previous_features)
            if (
                previous_engagement == Engagement.OFF_TASK
                and features.allowed_continuous_seconds >= 30
            ):
                engagement = Engagement.ON_TASK
                reasons.append("ALLOWED_APP_CONTINUOUS_EXIT")
            elif previous_engagement == Engagement.OFF_TASK:
                engagement = Engagement.OFF_TASK
                reasons.append("OFF_TASK_HYSTERESIS_HOLD")
            elif features.blocked_continuous_seconds >= 90 or (
                features.off_task_candidate and consecutive_candidate
            ):
                engagement = Engagement.OFF_TASK
                reasons.append("OFF_TASK_HYSTERESIS_ENTER")
            elif features.on_task_candidate:
                engagement = Engagement.ON_TASK
                reasons.append("ALLOWED_APP_RATIO")
            else:
                reasons.append("SENSOR_DATA_INSUFFICIENT")

    if not reasons:
        reasons.append("SENSOR_DATA_INSUFFICIENT")
    state_key = f"{features.device_id}|{features.session_id}|{state_version}|{now.isoformat()}"
    return RuntimeStateRead(
        state_id=uuid5(_FEATURE_NAMESPACE, state_key),
        device_id=features.device_id,
        session_id=features.session_id,
        estimated_at=now,
        context=context,
        presence=presence,
        engagement=engagement,
        session_state=SessionState(effective_session_state),
        device_role=device_role,
        confidence=features.confidence,
        reason_codes=list(dict.fromkeys(reasons)),
        valid_until=now + timedelta(seconds=valid_for_seconds),
        state_version=state_version,
        features=features.contract_features(),
    )


def context_for_block(block: ScheduleBlockRead | None) -> Context:
    if block is None:
        return Context.UNPLANNED
    if block.kind == BlockKind.TASK:
        return Context.FOCUS
    if block.kind == BlockKind.FIXED_EVENT:
        return Context.CLASS if str(block.activity_profile) == "CLASS" else Context.FOCUS
    return {
        BlockKind.TRAVEL: Context.TRAVEL,
        BlockKind.MEAL: Context.MEAL,
        BlockKind.SLEEP: Context.SLEEP,
        BlockKind.BREAK: Context.BREAK,
        BlockKind.BUFFER: Context.FREE,
        BlockKind.UNPLANNED: Context.UNPLANNED,
    }[block.kind]


def can_transition_session(previous: SessionState, following: SessionState) -> bool:
    return str(following) in _SESSION_TRANSITIONS[str(previous)]


def _activity_segments(
    observations: Sequence[ObservationIn],
    now: datetime,
    sample_hold_seconds: int,
    allowed: set[str],
    blocked: set[str],
) -> list[tuple[datetime, datetime, str]]:
    segments: list[tuple[datetime, datetime, str]] = []
    for index, item in enumerate(observations):
        start = utc(item.observed_at)
        next_start = (
            utc(observations[index + 1].observed_at) if index + 1 < len(observations) else now
        )
        end = min(start + timedelta(seconds=sample_hold_seconds), next_start, now)
        if end <= start:
            continue
        process = _process_name(item.payload.foreground_process or "")
        if process in blocked:
            classification = "BLOCKED"
        elif process in allowed:
            classification = "ALLOWED"
        else:
            classification = "OTHER"
        segments.append((start, end, classification))
    return segments


def _window_totals(
    segments: Sequence[tuple[datetime, datetime, str]],
    now: datetime,
    seconds: int,
) -> tuple[float, float, float]:
    start = now - timedelta(seconds=seconds)
    coverage = allowed = blocked = 0.0
    for segment_start, segment_end, classification in segments:
        overlap = max(0.0, (min(segment_end, now) - max(segment_start, start)).total_seconds())
        coverage += overlap
        if classification == "ALLOWED":
            allowed += overlap
        elif classification == "BLOCKED":
            blocked += overlap
    return min(float(seconds), coverage), allowed, blocked


def _continuous_seconds(
    segments: Sequence[tuple[datetime, datetime, str]],
    now: datetime,
    classification: str,
) -> float:
    cursor = now
    total = 0.0
    for start, end, segment_classification in reversed(segments):
        if end < cursor:
            break
        if segment_classification != classification:
            break
        total += max(0.0, (min(end, cursor) - start).total_seconds())
        cursor = start
    return total


def _latest_payload_value(
    observations: Sequence[ObservationIn],
    field: str,
    default: object = None,
) -> object:
    for item in reversed(observations):
        value = getattr(item.payload, field)
        if value is not None:
            return value
    return default


def _manual_presence_duration(
    observations: Sequence[ObservationIn],
    now: datetime,
    latest_presence: object,
) -> float:
    if latest_presence is None:
        return 0.0
    earliest = now
    for item in reversed(observations):
        value = item.payload.manual_presence
        if value is None:
            continue
        if str(value) != str(latest_presence):
            break
        earliest = utc(item.observed_at)
    return max(0.0, (now - earliest).total_seconds())


def _sensor_conflict(observations: Sequence[ObservationIn]) -> bool:
    by_time: dict[datetime, dict[str, set[object]]] = {}
    for item in observations:
        values = by_time.setdefault(utc(item.observed_at), {})
        for field in ("is_locked", "manual_presence", "sensor_ok"):
            value = getattr(item.payload, field)
            if value is not None:
                values.setdefault(field, set()).add(str(value))
    return any(len(options) > 1 for values in by_time.values() for options in values.values())


def _is_consecutive_candidate(
    current: FeatureSnapshot,
    previous: FeatureSnapshot | None,
) -> bool:
    if previous is None or not previous.off_task_candidate or previous.confidence < 0.65:
        return False
    separation = (current.evaluated_at - previous.evaluated_at).total_seconds()
    return 0 < separation <= 90 and not previous.sensor_conflict and not previous.sensor_failed


def _process_name(value: str) -> str:
    normalized = value.strip().replace("/", "\\")
    return PureWindowsPath(normalized).name.casefold()


def _interrupt(session_state: str) -> str:
    if session_state in _TERMINAL_SESSION_STATES:
        return session_state
    return SessionState.INTERRUPTED
