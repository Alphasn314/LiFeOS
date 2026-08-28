"""SQLAlchemy 2.0 persistence model for the LifeOS modular monolith.

Transport schemas remain the external boundary.  These rows include additional
internal columns needed for optimistic concurrency, durable queues, and audit
history.  Evidence and historical plan/state rows are append-only by design;
mutable heads and lifecycle rows use SQLAlchemy's version counter support.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    """Return an aware UTC timestamp for Python-side defaults."""

    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Persist only aware timestamps and always return them normalized to UTC.

    PostgreSQL stores this as ``TIMESTAMP WITH TIME ZONE``. SQLite drops timezone
    metadata, so the result hook restores UTC awareness for portable tests.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LifeOS timestamps must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class VersionedMixin:
    """Add integer optimistic concurrency control to a mutable row."""

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.version}


class TaskRow(VersionedMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('BACKLOG','READY','IN_PROGRESS','COMPLETED','CANCELLED')", name="status"
        ),
        CheckConstraint("priority BETWEEN 1 AND 5", name="priority_range"),
        CheckConstraint("estimated_minutes BETWEEN 1 AND 10080", name="estimated_minutes_range"),
        CheckConstraint("remaining_minutes BETWEEN 0 AND 10080", name="remaining_minutes_range"),
        CheckConstraint("minimum_chunk_minutes BETWEEN 5 AND 180", name="minimum_chunk_range"),
        CheckConstraint("idle_tolerance_seconds BETWEEN 30 AND 7200", name="idle_tolerance_range"),
        CheckConstraint(
            "activity_profile IN "
            "('READING','WRITING','CODING','CLASS','ADMIN',"
            "'PHYSICAL','PASSIVE_VIDEO','OTHER')",
            name="activity_profile",
        ),
        Index("ix_tasks_status_deadline", "status", "deadline"),
        Index("ix_tasks_mandatory_priority", "mandatory", "priority"),
    )

    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="BACKLOG", server_default="BACKLOG"
    )
    priority: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=3, server_default=text("3")
    )
    mandatory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    deadline: Mapped[datetime | None] = mapped_column(UTCDateTime)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_chunk_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=25, server_default=text("25")
    )
    activity_profile: Mapped[str] = mapped_column(
        String(32), nullable=False, default="OTHER", server_default="OTHER"
    )
    required_location: Mapped[str | None] = mapped_column(String(128))
    required_device_capabilities: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    allowed_apps: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    blocked_apps: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    idle_tolerance_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300, server_default=text("300")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now()
    )


class FixedEventRow(VersionedMixin, Base):
    __tablename__ = "fixed_events"
    __table_args__ = (
        UniqueConstraint(
            "external_source", "external_id", name="uq_fixed_events_external_source_id"
        ),
        CheckConstraint("end_at > start_at", name="valid_interval"),
        CheckConstraint("hardness IN ('HARD','REQUIRED','SOFT')", name="hardness"),
        CheckConstraint("travel_before_minutes BETWEEN 0 AND 1440", name="travel_before_range"),
        CheckConstraint("travel_after_minutes BETWEEN 0 AND 1440", name="travel_after_range"),
        CheckConstraint(
            "activity_profile IN "
            "('READING','WRITING','CODING','CLASS','ADMIN',"
            "'PHYSICAL','PASSIVE_VIDEO','OTHER')",
            name="activity_profile",
        ),
        Index("ix_fixed_events_start_end", "start_at", "end_at"),
    )

    fixed_event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    display_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai"
    )
    location: Mapped[str | None] = mapped_column(String(128))
    hardness: Mapped[str] = mapped_column(
        String(16), nullable=False, default="HARD", server_default="HARD"
    )
    activity_profile: Mapped[str] = mapped_column(
        String(32), nullable=False, default="CLASS", server_default="CLASS"
    )
    travel_before_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    travel_after_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    recurrence_rule: Mapped[str | None] = mapped_column(String(500))
    external_source: Mapped[str | None] = mapped_column(String(64))
    external_id: Mapped[str | None] = mapped_column(String(200))
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now()
    )


class PlanVersionRow(Base):
    __tablename__ = "plan_versions"
    __table_args__ = (
        UniqueConstraint(
            "plan_date",
            "display_timezone",
            "revision",
            name="uq_plan_versions_date_timezone_revision",
        ),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("status IN ('FEASIBLE','PARTIAL','INFEASIBLE')", name="status"),
        CheckConstraint(
            "trigger IN ('DAY_STARTED','USER_REQUESTED_REPLAN','TASK_COMPLETED_EARLY',"
            "'TASK_OVERRUN','BLOCK_MISSED','FIXED_EVENT_CHANGED','USER_REPORTED_FATIGUE',"
            "'USER_REPORTED_EMERGENCY','SESSION_ABORTED','AVAILABLE_TIME_CHANGED')",
            name="trigger",
        ),
        Index("ix_plan_versions_date_created", "plan_date", "created_at"),
    )

    plan_version_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    display_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    based_on_plan_version_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("plan_versions.plan_version_id", ondelete="SET NULL"),
    )
    trigger: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    created_state_version: Mapped[int | None] = mapped_column(Integer)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    conflicts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class PlanHeadRow(VersionedMixin, Base):
    __tablename__ = "plan_heads"
    __table_args__ = (
        UniqueConstraint("plan_date", "display_timezone", name="uq_plan_heads_date_timezone"),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )

    plan_head_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    display_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai"
    )
    current_plan_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("plan_versions.plan_version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now()
    )


class ScheduleBlockRow(Base):
    __tablename__ = "schedule_blocks"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="valid_interval"),
        CheckConstraint(
            "kind IN ('FIXED_EVENT','TASK','TRAVEL','MEAL','SLEEP','BREAK','BUFFER','UNPLANNED')",
            name="kind",
        ),
        CheckConstraint("hardness IN ('HARD','REQUIRED','SOFT')", name="hardness"),
        CheckConstraint(
            "activity_profile IN "
            "('READING','WRITING','CODING','CLASS','ADMIN',"
            "'PHYSICAL','PASSIVE_VIDEO','OTHER')",
            name="activity_profile",
        ),
        UniqueConstraint("plan_version_id", "block_id", name="uq_schedule_blocks_plan_block"),
        Index("ix_schedule_blocks_plan_start", "plan_version_id", "start_at"),
        Index("ix_schedule_blocks_task_start", "task_id", "start_at"),
    )

    block_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("plan_versions.plan_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("tasks.task_id", ondelete="RESTRICT")
    )
    fixed_event_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("fixed_events.fixed_event_id", ondelete="RESTRICT"),
    )
    source_block_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("schedule_blocks.block_id", ondelete="SET NULL"),
    )
    hardness: Mapped[str] = mapped_column(String(16), nullable=False)
    activity_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    allowed_apps: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    blocked_apps: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class ExecutionSessionRow(VersionedMixin, Base):
    __tablename__ = "execution_sessions"
    __table_args__ = (
        CheckConstraint(
            "commitment_mode IN ('ADVISORY','STANDARD','STRICT')", name="commitment_mode"
        ),
        CheckConstraint(
            "session_state IN ('PLANNED','DUE','STARTING','RUNNING','PAUSED',"
            "'INTERRUPTED','RECOVERY','COMPLETED','ABORTED','MISSED')",
            name="session_state",
        ),
        CheckConstraint("intervention_level BETWEEN 0 AND 5", name="intervention_level_range"),
        CheckConstraint("scheduled_end_at > scheduled_start_at", name="scheduled_interval"),
        CheckConstraint(
            "actual_end_at IS NULL OR actual_start_at IS NULL OR actual_end_at >= actual_start_at",
            name="actual_interval",
        ),
        Index("ix_execution_sessions_state_scheduled", "session_state", "scheduled_start_at"),
        Index("ix_execution_sessions_task_created", "task_id", "created_at"),
    )

    session_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("plan_versions.plan_version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    block_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("schedule_blocks.block_id", ondelete="RESTRICT"),
        nullable=False,
    )
    task_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("tasks.task_id", ondelete="RESTRICT")
    )
    device_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("devices.device_id", ondelete="RESTRICT"),
        nullable=False,
    )
    commitment_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    session_state: Mapped[str] = mapped_column(
        String(24), nullable=False, default="PLANNED", server_default="PLANNED"
    )
    scheduled_start_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    scheduled_end_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    actual_start_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    actual_end_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    intervention_level: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    preauthorization: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    emergency_released_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    override_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    override_reason: Mapped[str | None] = mapped_column(String(500))
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now()
    )


class DeviceRow(VersionedMixin, Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(
            "device_type IN ('WINDOWS','WEB','MOBILE','SERVER','OTHER')", name="device_type"
        ),
        CheckConstraint("status IN ('ONLINE','OFFLINE','DEGRADED','UNKNOWN')", name="status"),
        Index("ix_devices_status_heartbeat", "status", "last_heartbeat_at"),
    )

    device_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    device_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="OTHER", server_default="OTHER"
    )
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="UNKNOWN", server_default="UNKNOWN"
    )
    agent_version: Mapped[str | None] = mapped_column(String(32))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    latest_state_version: Mapped[int | None] = mapped_column(Integer)
    core_reachable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now()
    )


class ObservationRow(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_observations_idempotency_key"),
        CheckConstraint(
            "kind IN ('ACTIVITY_SAMPLE','LOCK_STATE','SESSION_STATE',"
            "'MANUAL_CHECK_IN','SENSOR_STATUS')",
            name="kind",
        ),
        Index("ix_observations_device_observed", "device_id", "observed_at"),
        Index("ix_observations_session_observed", "session_id", "observed_at"),
        Index("ix_observations_received", "received_at"),
    )

    observation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    schema_version: Mapped[str] = mapped_column(
        String(16), nullable=False, default="1.0", server_default="1.0"
    )
    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.device_id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("execution_sessions.session_id", ondelete="SET NULL"),
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class FeatureSnapshotRow(Base):
    __tablename__ = "feature_snapshots"
    __table_args__ = (
        CheckConstraint(
            "window_60_coverage_seconds BETWEEN 0 AND 60", name="window_60_coverage_range"
        ),
        CheckConstraint(
            "window_300_coverage_seconds BETWEEN 0 AND 300", name="window_300_coverage_range"
        ),
        CheckConstraint("allowed_app_ratio_60s BETWEEN 0 AND 1", name="allowed_ratio_range"),
        CheckConstraint("blocked_app_ratio_60s BETWEEN 0 AND 1", name="blocked_ratio_range"),
        CheckConstraint("blocked_continuous_seconds >= 0", name="blocked_continuous_nonnegative"),
        CheckConstraint("allowed_continuous_seconds >= 0", name="allowed_continuous_nonnegative"),
        CheckConstraint("idle_seconds IS NULL OR idle_seconds >= 0", name="idle_nonnegative"),
        Index("ix_feature_snapshots_device_computed", "device_id", "computed_at"),
        Index("ix_feature_snapshots_session_computed", "session_id", "computed_at"),
    )

    feature_snapshot_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.device_id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("execution_sessions.session_id", ondelete="SET NULL"),
    )
    computed_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    window_60_started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    window_300_started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    window_ended_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    window_60_coverage_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    window_300_coverage_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    allowed_app_ratio_60s: Mapped[float] = mapped_column(Float, nullable=False)
    blocked_app_ratio_60s: Mapped[float] = mapped_column(Float, nullable=False)
    blocked_continuous_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    allowed_continuous_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    idle_seconds: Mapped[int | None] = mapped_column(Integer)
    sensor_conflict: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    source_observation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class RuntimeStateRow(Base):
    __tablename__ = "runtime_states"
    __table_args__ = (
        UniqueConstraint(
            "device_id", "state_version", name="uq_runtime_states_device_state_version"
        ),
        CheckConstraint("state_version >= 1", name="state_version_positive"),
        CheckConstraint(
            "context IN ('FOCUS','CLASS','BREAK','MEAL','TRAVEL','FREE',"
            "'SLEEP','RECOVERY','EMERGENCY','UNPLANNED')",
            name="context",
        ),
        CheckConstraint("presence IN ('PRESENT','ABSENT','UNKNOWN')", name="presence"),
        CheckConstraint("engagement IN ('ON_TASK','OFF_TASK','IDLE','UNKNOWN')", name="engagement"),
        CheckConstraint(
            "session_state IN ('PLANNED','DUE','STARTING','RUNNING','PAUSED',"
            "'INTERRUPTED','RECOVERY','COMPLETED','ABORTED','MISSED')",
            name="session_state",
        ),
        CheckConstraint(
            "device_role IN ('PRIMARY_INTERACTION','PRIMARY_ENFORCEMENT','SENSOR',"
            "'NOTIFICATION_ONLY','AI_WORKER','STANDBY')",
            name="device_role",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("valid_until > estimated_at", name="valid_interval"),
        Index("ix_runtime_states_device_estimated", "device_id", "estimated_at"),
        Index("ix_runtime_states_session_estimated", "session_id", "estimated_at"),
    )

    state_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.device_id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("execution_sessions.session_id", ondelete="SET NULL"),
    )
    feature_snapshot_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("feature_snapshots.feature_snapshot_id", ondelete="SET NULL"),
    )
    estimated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    context: Mapped[str] = mapped_column(String(24), nullable=False)
    presence: Mapped[str] = mapped_column(String(16), nullable=False)
    engagement: Mapped[str] = mapped_column(String(16), nullable=False)
    session_state: Mapped[str] = mapped_column(String(24), nullable=False)
    device_role: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class RuntimeStateHeadRow(VersionedMixin, Base):
    __tablename__ = "runtime_state_heads"
    __table_args__ = (
        UniqueConstraint("device_id", name="uq_runtime_state_heads_device_id"),
        CheckConstraint("state_version >= 1", name="state_version_positive"),
    )

    runtime_state_head_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False
    )
    current_state_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("runtime_states.state_id", ondelete="RESTRICT"),
        nullable=False,
    )
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now()
    )


class DeviceRoleLeaseRow(VersionedMixin, Base):
    __tablename__ = "device_role_leases"
    __table_args__ = (
        CheckConstraint(
            "role IN ('PRIMARY_INTERACTION','PRIMARY_ENFORCEMENT','SENSOR',"
            "'NOTIFICATION_ONLY','AI_WORKER','STANDBY')",
            name="role",
        ),
        CheckConstraint("expires_at > issued_at", name="valid_interval"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= issued_at", name="revocation_after_issue"
        ),
        CheckConstraint("issued_for_state_version >= 1", name="state_version_positive"),
        Index("ix_device_role_leases_role_expiry", "role", "expires_at"),
        Index("ix_device_role_leases_device_expiry", "device_id", "expires_at"),
    )

    lease_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    issued_for_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class PolicyDecisionRow(Base):
    __tablename__ = "policy_decisions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_policy_decisions_idempotency_key"),
        CheckConstraint(
            "commitment_mode IN ('ADVISORY','STANDARD','STRICT')", name="commitment_mode"
        ),
        CheckConstraint("intervention_level BETWEEN 0 AND 5", name="intervention_level_range"),
        CheckConstraint("risk_level IN ('SAFE','HARD')", name="risk_level"),
        CheckConstraint("expires_at IS NULL OR expires_at > decided_at", name="valid_expiry"),
        Index("ix_policy_decisions_session_decided", "session_id", "decided_at"),
        Index("ix_policy_decisions_state_version", "state_version"),
    )

    decision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("execution_sessions.session_id", ondelete="RESTRICT"),
        nullable=False,
    )
    state_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runtime_states.state_id", ondelete="RESTRICT"), nullable=False
    )
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    commitment_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    intervention_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    decided_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class CommandRow(VersionedMixin, Base):
    __tablename__ = "commands"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_commands_idempotency_key"),
        CheckConstraint(
            "authorized_commitment_mode IN ('ADVISORY','STANDARD','STRICT')", name="commitment_mode"
        ),
        CheckConstraint(
            "command_type IN ('SHOW_NOTIFICATION','SHOW_CONFIRMATION','WOULD_BLOCK',"
            "'START_BLOCK','ENTER_RECOVERY','RELEASE_ALL')",
            name="command_type",
        ),
        CheckConstraint("risk_level IN ('SAFE','HARD')", name="risk_level"),
        CheckConstraint(
            "status IN ('PENDING','DELIVERED','ACKED','REJECTED','EXPIRED','CANCELLED')",
            name="status",
        ),
        CheckConstraint("expires_at > not_before AND not_before >= issued_at", name="valid_window"),
        CheckConstraint("required_state_version >= 1", name="state_version_positive"),
        CheckConstraint(
            "risk_level != 'HARD' OR role_lease_id IS NOT NULL", name="hard_requires_lease"
        ),
        CheckConstraint(
            "risk_level != 'HARD' OR authorized_commitment_mode IN ('STANDARD','STRICT')",
            name="hard_requires_authority",
        ),
        Index(
            "ix_commands_target_status_window",
            "target_device_id",
            "status",
            "not_before",
            "expires_at",
        ),
        Index("ix_commands_session_issued", "session_id", "issued_at"),
        Index("ix_commands_decision", "decision_id"),
    )

    command_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    target_device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.device_id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("execution_sessions.session_id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("policy_decisions.decision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    role_lease_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("device_role_leases.lease_id", ondelete="RESTRICT"),
    )
    authorized_commitment_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    command_type: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default="PENDING"
    )
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    not_before: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    required_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now()
    )


class CommandAckRow(Base):
    __tablename__ = "command_acks"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_command_acks_idempotency_key"),
        CheckConstraint(
            "status IN ('ACCEPTED','EXECUTED','REJECTED','EXPIRED','STALE','FAILED')", name="status"
        ),
        Index("ix_command_acks_command_acknowledged", "command_id", "acknowledged_at"),
        Index("ix_command_acks_device_acknowledged", "device_id", "acknowledged_at"),
    )

    ack_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    command_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("commands.command_id", ondelete="RESTRICT"), nullable=False
    )
    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.device_id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    observed_state_version: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class EventLedgerRow(Base):
    __tablename__ = "event_ledger"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_event_ledger_idempotency_key"),
        Index("ix_event_ledger_entity_received", "entity_type", "entity_id", "received_at"),
        Index("ix_event_ledger_type_occurred", "event_type", "occurred_at"),
        Index("ix_event_ledger_correlation", "correlation_id"),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    schema_version: Mapped[str] = mapped_column(
        String(16), nullable=False, default="1.0", server_default="1.0"
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    correlation_id: Mapped[UUID | None] = mapped_column(Uuid)
    causation_id: Mapped[UUID | None] = mapped_column(Uuid)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class OutboxRow(VersionedMixin, Base):
    __tablename__ = "outbox"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_outbox_event_id"),
        CheckConstraint("status IN ('PENDING','PUBLISHED','FAILED')", name="status"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        Index("ix_outbox_status_available", "status", "available_at"),
        Index("ix_outbox_locked", "locked_at"),
    )

    outbox_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("event_ledger.event_id", ondelete="CASCADE"),
        nullable=False,
    )
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default="PENDING"
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    available_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AIJobRow(VersionedMixin, Base):
    __tablename__ = "ai_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ai_jobs_idempotency_key"),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLED')", name="status"
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint("max_attempts BETWEEN 1 AND 100", name="max_attempts_range"),
        Index("ix_ai_jobs_status_available", "status", "available_at"),
        Index("ix_ai_jobs_provider_created", "provider", "created_at"),
    )

    job_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, default=uuid4)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default="PENDING"
    )
    schema_version: Mapped[str] = mapped_column(
        String(16), nullable=False, default="1.0", server_default="1.0"
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    available_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class DailySummaryRow(VersionedMixin, Base):
    __tablename__ = "daily_summaries"
    __table_args__ = (
        UniqueConstraint(
            "summary_date", "display_timezone", name="uq_daily_summaries_date_timezone"
        ),
        CheckConstraint(
            "source_plan_revision IS NULL OR source_plan_revision >= 1",
            name="source_revision_positive",
        ),
        Index("ix_daily_summaries_date", "summary_date"),
    )

    summary_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    summary_date: Mapped[date] = mapped_column(Date, nullable=False)
    display_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai"
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    narrative: Mapped[str | None] = mapped_column(Text)
    source_plan_version_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("plan_versions.plan_version_id", ondelete="SET NULL"),
    )
    source_plan_revision: Mapped[int | None] = mapped_column(Integer)
    generated_by: Mapped[str] = mapped_column(
        String(32), nullable=False, default="DETERMINISTIC", server_default="DETERMINISTIC"
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now()
    )


__all__ = [
    "AIJobRow",
    "Base",
    "CommandAckRow",
    "CommandRow",
    "DailySummaryRow",
    "DeviceRoleLeaseRow",
    "DeviceRow",
    "EventLedgerRow",
    "ExecutionSessionRow",
    "FeatureSnapshotRow",
    "FixedEventRow",
    "ObservationRow",
    "OutboxRow",
    "PlanHeadRow",
    "PlanVersionRow",
    "PolicyDecisionRow",
    "RuntimeStateHeadRow",
    "RuntimeStateRow",
    "ScheduleBlockRow",
    "TaskRow",
    "UTCDateTime",
    "utc_now",
]
