from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import Clock
from ..errors import NotFoundError, VersionConflictError
from ..models import FixedEventRow, TaskRow
from ..schemas import (
    ActivityProfile,
    FixedEventCreate,
    FixedEventRead,
    FixedEventUpdate,
    TaskCreate,
    TaskRead,
    TaskStatus,
    TaskUpdate,
)
from .audit import append_event


def task_read(row: TaskRow) -> TaskRead:
    return TaskRead(
        task_id=row.task_id,
        title=row.title,
        description=row.description,
        status=TaskStatus(row.status),
        priority=row.priority,
        mandatory=row.mandatory,
        deadline=row.deadline,
        estimated_minutes=row.estimated_minutes,
        remaining_minutes=row.remaining_minutes,
        minimum_chunk_minutes=row.minimum_chunk_minutes,
        activity_profile=ActivityProfile(row.activity_profile),
        required_location=row.required_location,
        required_device_capabilities=row.required_device_capabilities,
        allowed_apps=row.allowed_apps,
        blocked_apps=row.blocked_apps,
        idle_tolerance_seconds=row.idle_tolerance_seconds,
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
    )


def fixed_event_read(row: FixedEventRow) -> FixedEventRead:
    return FixedEventRead(
        fixed_event_id=row.fixed_event_id,
        title=row.title,
        start_at=row.start_at,
        end_at=row.end_at,
        location=row.location,
        activity_profile=ActivityProfile(row.activity_profile),
        travel_before_minutes=row.travel_before_minutes,
        travel_after_minutes=row.travel_after_minutes,
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
    )


class TaskService:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def create(self, db: Session, payload: TaskCreate) -> TaskRead:
        now = self.clock.now()
        values = payload.model_dump(mode="python")
        row = TaskRow(**values, created_at=now, updated_at=now)
        db.add(row)
        db.flush()
        append_event(
            db,
            event_type="TASK.CREATED",
            occurred_at=now,
            received_at=now,
            source="core",
            entity_type="Task",
            entity_id=row.task_id,
            idempotency_key=f"task:create:{row.task_id}",
            payload={"version": row.version, "title": row.title},
            reason_codes=["EVENT_ACCEPTED"],
        )
        return task_read(row)

    def list(self, db: Session, *, include_terminal: bool = False) -> list[TaskRead]:
        statement = select(TaskRow)
        if not include_terminal:
            statement = statement.where(TaskRow.status.not_in(["COMPLETED", "CANCELLED"]))
        rows = db.scalars(statement.order_by(TaskRow.deadline, TaskRow.task_id)).all()
        return [task_read(row) for row in rows]

    def get_row(self, db: Session, task_id: UUID) -> TaskRow:
        row = db.get(TaskRow, task_id)
        if row is None:
            raise NotFoundError("Task", task_id)
        return row

    def get(self, db: Session, task_id: UUID) -> TaskRead:
        return task_read(self.get_row(db, task_id))

    def update(self, db: Session, task_id: UUID, payload: TaskUpdate) -> TaskRead:
        row = self.get_row(db, task_id)
        if row.version != payload.expected_version:
            raise VersionConflictError(payload.expected_version, row.version)
        fields = payload.model_dump(mode="python", exclude={"expected_version"}, exclude_unset=True)
        if fields.get("allowed_apps") is not None:
            fields["allowed_apps"] = sorted({app.lower() for app in fields["allowed_apps"]})
        if fields.get("blocked_apps") is not None:
            fields["blocked_apps"] = sorted({app.lower() for app in fields["blocked_apps"]})
        allowed = set(fields.get("allowed_apps", row.allowed_apps))
        blocked = set(fields.get("blocked_apps", row.blocked_apps))
        if allowed & blocked:
            raise ValueError("an application cannot be both allowed and blocked")
        estimated = fields.get("estimated_minutes", row.estimated_minutes)
        minimum = fields.get("minimum_chunk_minutes", row.minimum_chunk_minutes)
        if minimum > estimated:
            raise ValueError("minimum_chunk_minutes cannot exceed estimated_minutes")
        for name, value in fields.items():
            setattr(row, name, value)
        row.updated_at = self.clock.now()
        db.flush()
        append_event(
            db,
            event_type="TASK.UPDATED",
            occurred_at=row.updated_at,
            received_at=row.updated_at,
            source="core",
            entity_type="Task",
            entity_id=row.task_id,
            idempotency_key=f"task:update:{row.task_id}:{row.version}",
            payload={"version": row.version, "fields": sorted(fields)},
            reason_codes=["EVENT_ACCEPTED"],
        )
        return task_read(row)

    def delete(self, db: Session, task_id: UUID, expected_version: int) -> TaskRead:
        return self.update(
            db,
            task_id,
            TaskUpdate(expected_version=expected_version, status=TaskStatus.CANCELLED),
        )


class FixedEventService:
    def __init__(self, clock: Clock, display_timezone: str = "Asia/Shanghai") -> None:
        self.clock = clock
        self.display_timezone = display_timezone

    def create(self, db: Session, payload: FixedEventCreate) -> FixedEventRead:
        now = self.clock.now()
        row = FixedEventRow(
            **payload.model_dump(mode="python"),
            hardness="HARD",
            display_timezone=self.display_timezone,
            reason_codes=["HARD_FIXED_EVENT"],
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        append_event(
            db,
            event_type="FIXED_EVENT.CREATED",
            occurred_at=now,
            received_at=now,
            source="core",
            entity_type="FixedEvent",
            entity_id=row.fixed_event_id,
            idempotency_key=f"fixed-event:create:{row.fixed_event_id}",
            payload={"version": row.version, "start_at": row.start_at},
            reason_codes=["FIXED_EVENT_CHANGED"],
        )
        return fixed_event_read(row)

    def list(self, db: Session, start_at: datetime, end_at: datetime) -> list[FixedEventRead]:
        rows = db.scalars(
            select(FixedEventRow)
            .where(FixedEventRow.end_at > start_at, FixedEventRow.start_at < end_at)
            .order_by(FixedEventRow.start_at, FixedEventRow.fixed_event_id)
        ).all()
        return [fixed_event_read(row) for row in rows]

    def get_row(self, db: Session, fixed_event_id: UUID) -> FixedEventRow:
        row = db.get(FixedEventRow, fixed_event_id)
        if row is None:
            raise NotFoundError("FixedEvent", fixed_event_id)
        return row

    def get(self, db: Session, fixed_event_id: UUID) -> FixedEventRead:
        return fixed_event_read(self.get_row(db, fixed_event_id))

    def update(
        self, db: Session, fixed_event_id: UUID, payload: FixedEventUpdate
    ) -> FixedEventRead:
        row = self.get_row(db, fixed_event_id)
        if row.version != payload.expected_version:
            raise VersionConflictError(payload.expected_version, row.version)
        fields = payload.model_dump(mode="python", exclude={"expected_version"}, exclude_unset=True)
        start_at = fields.get("start_at", row.start_at)
        end_at = fields.get("end_at", row.end_at)
        if end_at <= start_at:
            raise ValueError("end_at must be after start_at")
        for name, value in fields.items():
            setattr(row, name, value)
        now = self.clock.now()
        row.updated_at = now
        db.flush()
        append_event(
            db,
            event_type="FIXED_EVENT.UPDATED",
            occurred_at=now,
            received_at=now,
            source="core",
            entity_type="FixedEvent",
            entity_id=row.fixed_event_id,
            idempotency_key=f"fixed-event:update:{row.fixed_event_id}:{row.version}",
            payload={"version": row.version, "fields": sorted(fields)},
            reason_codes=["FIXED_EVENT_CHANGED"],
        )
        return fixed_event_read(row)

    def delete(self, db: Session, fixed_event_id: UUID, expected_version: int) -> None:
        row = self.get_row(db, fixed_event_id)
        if row.version != expected_version:
            raise VersionConflictError(expected_version, row.version)
        now = self.clock.now()
        append_event(
            db,
            event_type="FIXED_EVENT.DELETED",
            occurred_at=now,
            received_at=now,
            source="core",
            entity_type="FixedEvent",
            entity_id=row.fixed_event_id,
            idempotency_key=f"fixed-event:delete:{row.fixed_event_id}:{row.version}",
            payload={"version": row.version},
            reason_codes=["FIXED_EVENT_CHANGED"],
        )
        db.delete(row)
        db.flush()
