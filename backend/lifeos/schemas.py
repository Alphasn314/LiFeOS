from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(UTC)


def _unique_reason_codes(value: list[str]) -> list[str]:
    if len(value) != len(set(value)):
        raise ValueError("reason_codes must be unique")
    return value


ReasonCode = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")]
ReasonCodes = Annotated[
    list[ReasonCode],
    Field(min_length=1, max_length=32),
    AfterValidator(_unique_reason_codes),
]
UtcDatetime = Annotated[
    AwareDatetime,
    AfterValidator(_normalize_utc),
    Field(description="Timezone-aware timestamp normalized to UTC"),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    @field_validator("*", mode="before")
    @classmethod
    def reject_naive_datetime(cls, value: Any) -> Any:
        if isinstance(value, datetime) and value.tzinfo is None:
            raise ValueError("datetime must include a timezone")
        return value


def utc(value: datetime) -> datetime:
    return _normalize_utc(value)


class TaskStatus(StrEnum):
    BACKLOG = "BACKLOG"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ActivityProfile(StrEnum):
    READING = "READING"
    WRITING = "WRITING"
    CODING = "CODING"
    CLASS = "CLASS"
    ADMIN = "ADMIN"
    PHYSICAL = "PHYSICAL"
    PASSIVE_VIDEO = "PASSIVE_VIDEO"
    OTHER = "OTHER"


class PlanTrigger(StrEnum):
    DAY_STARTED = "DAY_STARTED"
    USER_REQUESTED_REPLAN = "USER_REQUESTED_REPLAN"
    TASK_COMPLETED_EARLY = "TASK_COMPLETED_EARLY"
    TASK_OVERRUN = "TASK_OVERRUN"
    BLOCK_MISSED = "BLOCK_MISSED"
    FIXED_EVENT_CHANGED = "FIXED_EVENT_CHANGED"
    USER_REPORTED_FATIGUE = "USER_REPORTED_FATIGUE"
    USER_REPORTED_EMERGENCY = "USER_REPORTED_EMERGENCY"
    SESSION_ABORTED = "SESSION_ABORTED"
    AVAILABLE_TIME_CHANGED = "AVAILABLE_TIME_CHANGED"


class PlanStatus(StrEnum):
    FEASIBLE = "FEASIBLE"
    PARTIAL = "PARTIAL"
    INFEASIBLE = "INFEASIBLE"


class BlockKind(StrEnum):
    FIXED_EVENT = "FIXED_EVENT"
    TASK = "TASK"
    TRAVEL = "TRAVEL"
    MEAL = "MEAL"
    SLEEP = "SLEEP"
    BREAK = "BREAK"
    BUFFER = "BUFFER"
    UNPLANNED = "UNPLANNED"


class Hardness(StrEnum):
    HARD = "HARD"
    REQUIRED = "REQUIRED"
    SOFT = "SOFT"


class Context(StrEnum):
    FOCUS = "FOCUS"
    CLASS = "CLASS"
    BREAK = "BREAK"
    MEAL = "MEAL"
    TRAVEL = "TRAVEL"
    FREE = "FREE"
    SLEEP = "SLEEP"
    RECOVERY = "RECOVERY"
    EMERGENCY = "EMERGENCY"
    UNPLANNED = "UNPLANNED"


class Presence(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


class Engagement(StrEnum):
    ON_TASK = "ON_TASK"
    OFF_TASK = "OFF_TASK"
    IDLE = "IDLE"
    UNKNOWN = "UNKNOWN"


class SessionState(StrEnum):
    PLANNED = "PLANNED"
    DUE = "DUE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    INTERRUPTED = "INTERRUPTED"
    RECOVERY = "RECOVERY"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    MISSED = "MISSED"


class DeviceRole(StrEnum):
    PRIMARY_INTERACTION = "PRIMARY_INTERACTION"
    PRIMARY_ENFORCEMENT = "PRIMARY_ENFORCEMENT"
    SENSOR = "SENSOR"
    NOTIFICATION_ONLY = "NOTIFICATION_ONLY"
    AI_WORKER = "AI_WORKER"
    STANDBY = "STANDBY"


class CommitmentMode(StrEnum):
    ADVISORY = "ADVISORY"
    STANDARD = "STANDARD"
    STRICT = "STRICT"


class CommandType(StrEnum):
    SHOW_NOTIFICATION = "SHOW_NOTIFICATION"
    SHOW_CONFIRMATION = "SHOW_CONFIRMATION"
    WOULD_BLOCK = "WOULD_BLOCK"
    START_BLOCK = "START_BLOCK"
    ENTER_RECOVERY = "ENTER_RECOVERY"
    RELEASE_ALL = "RELEASE_ALL"


class TaskCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: TaskStatus = TaskStatus.READY
    priority: int = Field(default=3, ge=1, le=5)
    mandatory: bool = False
    deadline: UtcDatetime | None = None
    estimated_minutes: int = Field(ge=1, le=10080)
    remaining_minutes: int | None = Field(default=None, ge=0, le=10080)
    minimum_chunk_minutes: int = Field(default=25, ge=5, le=180)
    activity_profile: ActivityProfile = ActivityProfile.OTHER
    required_location: str | None = Field(default=None, max_length=128)
    required_device_capabilities: list[str] = Field(default_factory=list, max_length=32)
    allowed_apps: list[str] = Field(default_factory=list, max_length=128)
    blocked_apps: list[str] = Field(default_factory=list, max_length=128)
    idle_tolerance_seconds: int = Field(default=300, ge=30, le=7200)

    @model_validator(mode="after")
    def normalize(self) -> TaskCreate:
        if self.remaining_minutes is None:
            self.remaining_minutes = self.estimated_minutes
        if self.minimum_chunk_minutes > self.estimated_minutes:
            raise ValueError("minimum_chunk_minutes cannot exceed estimated_minutes")
        self.required_device_capabilities = sorted(set(self.required_device_capabilities))
        self.allowed_apps = sorted({app.lower() for app in self.allowed_apps})
        self.blocked_apps = sorted({app.lower() for app in self.blocked_apps})
        if set(self.allowed_apps) & set(self.blocked_apps):
            raise ValueError("an application cannot be both allowed and blocked")
        if self.deadline is not None:
            self.deadline = utc(self.deadline)
        return self


class TaskUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: TaskStatus | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    mandatory: bool | None = None
    deadline: UtcDatetime | None = None
    estimated_minutes: int | None = Field(default=None, ge=1, le=10080)
    remaining_minutes: int | None = Field(default=None, ge=0, le=10080)
    minimum_chunk_minutes: int | None = Field(default=None, ge=5, le=180)
    activity_profile: ActivityProfile | None = None
    required_location: str | None = Field(default=None, max_length=128)
    required_device_capabilities: list[str] | None = Field(default=None, max_length=32)
    allowed_apps: list[str] | None = Field(default=None, max_length=128)
    blocked_apps: list[str] | None = Field(default=None, max_length=128)
    idle_tolerance_seconds: int | None = Field(default=None, ge=30, le=7200)


class TaskRead(TaskCreate):
    schema_version: Literal["1.0"] = "1.0"
    task_id: UUID
    remaining_minutes: int
    created_at: UtcDatetime
    updated_at: UtcDatetime
    version: int = Field(ge=1)


class FixedEventCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    start_at: UtcDatetime
    end_at: UtcDatetime
    location: str | None = Field(default=None, max_length=128)
    activity_profile: ActivityProfile = ActivityProfile.CLASS
    travel_before_minutes: int = Field(default=0, ge=0, le=360)
    travel_after_minutes: int = Field(default=0, ge=0, le=360)

    @model_validator(mode="after")
    def interval_is_positive(self) -> FixedEventCreate:
        self.start_at = utc(self.start_at)
        self.end_at = utc(self.end_at)
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class FixedEventUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    start_at: UtcDatetime | None = None
    end_at: UtcDatetime | None = None
    location: str | None = Field(default=None, max_length=128)
    activity_profile: ActivityProfile | None = None
    travel_before_minutes: int | None = Field(default=None, ge=0, le=360)
    travel_after_minutes: int | None = Field(default=None, ge=0, le=360)


class FixedEventRead(FixedEventCreate):
    fixed_event_id: UUID
    created_at: UtcDatetime
    updated_at: UtcDatetime
    version: int = Field(ge=1)


class PlannerParameters(StrictModel):
    focus_minutes: int = Field(default=50, ge=10, le=90)
    break_minutes: int = Field(default=10, ge=5, le=30)
    max_focus_minutes: int = Field(default=90, ge=10, le=120)
    buffer_ratio: float = Field(default=0.10, ge=0, le=0.5)
    freeze_horizon_minutes: int = Field(default=15, ge=0, le=120)
    replan_debounce_seconds: int = Field(default=120, ge=0, le=3600)
    maximum_automatic_replans_per_hour: int = Field(default=3, ge=0, le=20)

    @model_validator(mode="after")
    def focus_bounds(self) -> PlannerParameters:
        if self.focus_minutes > self.max_focus_minutes:
            raise ValueError("focus_minutes cannot exceed max_focus_minutes")
        return self


class PlanRequest(StrictModel):
    plan_date: date
    display_timezone: str = Field(default="Asia/Shanghai", max_length=64)
    trigger: PlanTrigger = PlanTrigger.DAY_STARTED
    now: UtcDatetime | None = None
    parameters: PlannerParameters = Field(default_factory=PlannerParameters)
    available_start_local: str = Field(default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    available_end_local: str = Field(default="23:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    available_location: str | None = Field(default=None, max_length=128)
    available_device_capabilities: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("display_timezone")
    @classmethod
    def valid_display_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("display_timezone must be a valid IANA timezone") from exc
        return value


class PlanConflict(StrictModel):
    code: str
    severity: Literal["WARNING", "ERROR"]
    entity_ids: list[UUID] = Field(default_factory=list)
    start_at: UtcDatetime | None = None
    end_at: UtcDatetime | None = None
    required_minutes: int | None = Field(default=None, ge=0)
    available_minutes: int | None = Field(default=None, ge=0)
    detail: str = Field(max_length=500)


class ScheduleBlockRead(StrictModel):
    block_id: UUID
    kind: BlockKind
    title: str
    start_at: UtcDatetime
    end_at: UtcDatetime
    task_id: UUID | None = None
    fixed_event_id: UUID | None = None
    source_block_id: UUID | None = None
    hardness: Hardness
    activity_profile: ActivityProfile
    reason_codes: ReasonCodes


class PlanVersionRead(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    plan_version_id: UUID
    plan_date: date
    display_timezone: str
    revision: int = Field(ge=1)
    based_on_plan_version_id: UUID | None = None
    trigger: PlanTrigger
    status: PlanStatus
    algorithm_version: str = "deterministic-v1"
    created_at: UtcDatetime
    created_state_version: int | None = Field(default=None, ge=1)
    parameters: PlannerParameters
    blocks: list[ScheduleBlockRead]
    conflicts: list[PlanConflict]
    reason_codes: ReasonCodes


class SessionStart(StrictModel):
    block_id: UUID
    device_id: UUID
    commitment_mode: CommitmentMode = CommitmentMode.ADVISORY
    expected_plan_revision: int = Field(ge=1)


class SessionAction(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


class OverrideRequest(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class EmergencyReleaseRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=200)
    reason: str = Field(default="user emergency release", min_length=1, max_length=500)


class BreakRequest(StrictModel):
    expected_version: int = Field(ge=1)
    duration_minutes: int = Field(default=10, ge=5, le=30)
    reason: str = Field(default="user requested rest", min_length=1, max_length=500)


class ExecutionSessionRead(StrictModel):
    session_id: UUID
    plan_version_id: UUID
    block_id: UUID
    task_id: UUID | None
    device_id: UUID
    commitment_mode: CommitmentMode
    session_state: SessionState
    scheduled_start_at: UtcDatetime
    scheduled_end_at: UtcDatetime
    started_at: UtcDatetime | None
    ended_at: UtcDatetime | None
    dry_run: bool
    intervention_level: int = Field(ge=0, le=5)
    emergency_released_at: UtcDatetime | None
    override_reason: str | None
    version: int = Field(ge=1)
    reason_codes: ReasonCodes


class BreakResponse(StrictModel):
    session: ExecutionSessionRead
    plan: PlanVersionRead


class ObservationKind(StrEnum):
    ACTIVITY_SAMPLE = "ACTIVITY_SAMPLE"
    LOCK_STATE = "LOCK_STATE"
    SESSION_STATE = "SESSION_STATE"
    MANUAL_CHECK_IN = "MANUAL_CHECK_IN"
    SENSOR_STATUS = "SENSOR_STATUS"


class ObservationPayload(StrictModel):
    foreground_process: str | None = Field(default=None, max_length=128)
    window_title: str | None = Field(default=None, max_length=256)
    idle_seconds: int | None = Field(default=None, ge=0, le=86400)
    is_locked: bool | None = None
    manual_presence: Presence | None = None
    sensor_ok: bool | None = None
    client_session_state: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def has_evidence(self) -> ObservationPayload:
        if not self.model_fields_set:
            raise ValueError("observation payload must contain at least one evidence field")
        return self


class ObservationIn(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    observation_id: UUID
    device_id: UUID
    session_id: UUID | None
    kind: ObservationKind
    observed_at: UtcDatetime
    received_at: UtcDatetime | None = None
    idempotency_key: str = Field(min_length=8, max_length=200)
    payload: ObservationPayload
    reason_codes: ReasonCodes = Field(default_factory=lambda: ["SENSOR_SAMPLE"])


class FeatureRead(StrictModel):
    window_60_coverage_seconds: float = Field(ge=0, le=60)
    window_300_coverage_seconds: float = Field(ge=0, le=300)
    allowed_app_ratio_60s: float = Field(ge=0, le=1)
    blocked_app_ratio_60s: float = Field(ge=0, le=1)
    blocked_continuous_seconds: float = Field(ge=0)
    allowed_continuous_seconds: float = Field(ge=0)
    idle_seconds: int | None = Field(default=None, ge=0)
    sensor_conflict: bool


class RuntimeStateRead(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    state_id: UUID
    device_id: UUID
    session_id: UUID | None
    estimated_at: UtcDatetime
    context: Context
    presence: Presence
    engagement: Engagement
    session_state: SessionState
    device_role: DeviceRole
    confidence: float = Field(ge=0, le=1)
    reason_codes: ReasonCodes
    valid_until: UtcDatetime
    state_version: int = Field(ge=1)
    features: FeatureRead


class DeviceRegister(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    device_type: Literal["WINDOWS", "WEB", "MOBILE", "SERVER"] = "WINDOWS"
    capabilities: list[str] = Field(default_factory=list, max_length=32)


class DeviceRead(DeviceRegister):
    device_id: UUID
    status: Literal["ONLINE", "OFFLINE", "UNKNOWN"]
    last_heartbeat_at: UtcDatetime | None
    version: int


class HeartbeatIn(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    heartbeat_id: UUID
    device_id: UUID
    observed_at: UtcDatetime
    agent_version: str = Field(min_length=1, max_length=32)
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    latest_state_version: int | None = Field(default=None, ge=1)
    core_reachable: bool
    idempotency_key: str = Field(min_length=8, max_length=200)
    reason_codes: ReasonCodes = Field(default_factory=lambda: ["HEARTBEAT_RECEIVED"])


class CommandPayload(StrictModel):
    message: str | None = Field(default=None, max_length=500)
    choices: list[Literal["RETURN_TO_TASK", "BREAK_10_MINUTES", "REPLAN", "END_SESSION"]] = Field(
        default_factory=list, max_length=4
    )
    applications: list[str] = Field(default_factory=list, max_length=64)
    duration_seconds: int = Field(default=0, ge=0, le=1800)
    restriction_id: UUID | None = None


class CommandRead(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    command_id: UUID
    target_device_id: UUID
    session_id: UUID
    decision_id: UUID
    role_lease_id: UUID | None
    authorized_commitment_mode: CommitmentMode
    command_type: CommandType
    risk_level: Literal["SAFE", "HARD"]
    issued_at: UtcDatetime
    not_before: UtcDatetime
    expires_at: UtcDatetime
    required_state_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=200)
    payload: CommandPayload
    dry_run: bool
    reason_codes: ReasonCodes

    @model_validator(mode="after")
    def valid_command_window(self) -> CommandRead:
        if not (self.issued_at <= self.not_before < self.expires_at):
            raise ValueError("command timing must satisfy issued_at <= not_before < expires_at")
        if self.risk_level == "HARD":
            if self.role_lease_id is None:
                raise ValueError("hard command requires role_lease_id")
            if self.authorized_commitment_mode == CommitmentMode.ADVISORY:
                raise ValueError("ADVISORY cannot authorize hard command")
        return self


class RoleLeaseRead(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    lease_id: UUID
    device_id: UUID
    role: DeviceRole
    issued_at: UtcDatetime
    expires_at: UtcDatetime
    revoked_at: UtcDatetime | None
    issued_for_state_version: int = Field(ge=1)
    version: int = Field(ge=1)
    reason_codes: ReasonCodes


class CommandPollResponse(StrictModel):
    commands: list[CommandRead]
    latest_state_version: int | None = Field(default=None, ge=1)
    role_leases: list[RoleLeaseRead] = Field(default_factory=list)


class CommandAckIn(StrictModel):
    ack_id: UUID
    command_id: UUID
    device_id: UUID
    acknowledged_at: UtcDatetime
    status: Literal["ACCEPTED", "EXECUTED", "REJECTED", "FAILED", "EXPIRED"]
    observed_state_version: int | None = Field(default=None, ge=1)
    idempotency_key: str = Field(min_length=8, max_length=200)
    details: dict[str, Any] = Field(default_factory=dict)
    reason_codes: ReasonCodes


class CommandAckRead(CommandAckIn):
    duplicate: bool = False


class EventEnvelopeIn(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: UUID
    event_type: str = Field(pattern=r"^[A-Z][A-Z0-9_.]{2,127}$")
    occurred_at: UtcDatetime
    received_at: UtcDatetime | None = None
    source: str = Field(min_length=1, max_length=64)
    entity_type: str = Field(min_length=1, max_length=64)
    entity_id: UUID
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    idempotency_key: str = Field(min_length=8, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)
    reason_codes: ReasonCodes

    @field_validator("payload")
    @classmethod
    def bounded_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 128:
            raise ValueError("event payload cannot contain more than 128 properties")
        return value


class EventAccepted(StrictModel):
    event_id: UUID
    duplicate: bool
    side_effect_ids: list[UUID] = Field(default_factory=list)
    reason_codes: ReasonCodes


class EventEnvelopeRead(EventEnvelopeIn):
    received_at: UtcDatetime


class ErrorItem(StrictModel):
    path: str
    message: str


class ErrorResponse(StrictModel):
    type: str = "about:blank"
    title: str
    status: int = Field(ge=400, le=599)
    detail: str
    error_code: str
    reason_codes: ReasonCodes
    correlation_id: UUID
    errors: list[ErrorItem] = Field(default_factory=list)


class AIPlanningRequest(StrictModel):
    message_type: Literal["AI_PLANNING_REQUEST"] = "AI_PLANNING_REQUEST"
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    requested_at: UtcDatetime
    current_time: UtcDatetime
    runtime_state: dict[str, Any] | None
    current_plan: dict[str, Any] | None
    current_block_id: UUID | None
    future_blocks: list[dict[str, Any]] = Field(max_length=3)
    today_progress: dict[str, Any]
    unfinished_tasks: list[dict[str, Any]] = Field(max_length=256)
    active_incident: dict[str, Any] | None
    policy_constraints: dict[str, Any]
    reason_codes: ReasonCodes


class AIPlanningResponse(StrictModel):
    message_type: Literal["AI_PLANNING_RESPONSE"] = "AI_PLANNING_RESPONSE"
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    response_id: UUID
    provider: str = Field(max_length=64)
    created_at: UtcDatetime
    recommendation: dict[str, Any]
    conflict_explanations: list[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list, max_length=64
    )
    reason_codes: ReasonCodes

    @field_validator("recommendation")
    @classmethod
    def bounded_recommendation(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 64:
            raise ValueError("recommendation cannot contain more than 64 properties")
        return value


class AIJobSubmit(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=200)
    request: AIPlanningRequest


class AIJobRead(StrictModel):
    job_id: UUID
    request_id: UUID
    provider: str
    job_type: str
    status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
    schema_version: str
    request_payload: dict[str, Any]
    response_payload: dict[str, Any] | None
    attempts: int
    max_attempts: int
    last_error: str | None
    idempotency_key: str
    created_at: UtcDatetime
    started_at: UtcDatetime | None
    completed_at: UtcDatetime | None
    fallback_used: bool
