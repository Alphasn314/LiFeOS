from __future__ import annotations

from datetime import date, datetime, time, timedelta
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..clock import Clock
from ..errors import LifeOSError, NotFoundError
from ..models import (
    FixedEventRow,
    PlanHeadRow,
    PlanVersionRow,
    ScheduleBlockRow,
    TaskRow,
)
from ..planning import check_replan_gate, plan_day, replan_day
from ..schemas import (
    ActivityProfile,
    BlockKind,
    Hardness,
    PlanConflict,
    PlannerParameters,
    PlanRequest,
    PlanStatus,
    PlanTrigger,
    PlanVersionRead,
    ScheduleBlockRead,
    TaskRead,
)
from .audit import append_event
from .tasks import fixed_event_read, task_read

MANUAL_TRIGGERS = {"USER_REQUESTED_REPLAN", "USER_REPORTED_EMERGENCY"}


def plan_read(db: Session, row: PlanVersionRow) -> PlanVersionRead:
    blocks = db.scalars(
        select(ScheduleBlockRow)
        .where(ScheduleBlockRow.plan_version_id == row.plan_version_id)
        .order_by(ScheduleBlockRow.start_at, ScheduleBlockRow.block_id)
    ).all()
    return PlanVersionRead(
        plan_version_id=row.plan_version_id,
        plan_date=row.plan_date,
        display_timezone=row.display_timezone,
        revision=row.revision,
        based_on_plan_version_id=row.based_on_plan_version_id,
        trigger=PlanTrigger(row.trigger),
        status=PlanStatus(row.status),
        algorithm_version=row.algorithm_version,
        created_at=row.created_at,
        created_state_version=row.created_state_version,
        parameters=PlannerParameters.model_validate(row.parameters),
        blocks=[
            ScheduleBlockRead(
                block_id=block.block_id,
                kind=BlockKind(block.kind),
                title=block.title,
                start_at=block.start_at,
                end_at=block.end_at,
                task_id=block.task_id,
                fixed_event_id=block.fixed_event_id,
                source_block_id=block.source_block_id,
                hardness=Hardness(block.hardness),
                activity_profile=ActivityProfile(block.activity_profile),
                reason_codes=block.reason_codes,
            )
            for block in blocks
        ],
        conflicts=[PlanConflict.model_validate(conflict) for conflict in row.conflicts],
        reason_codes=row.reason_codes,
    )


class PlanService:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def generate(
        self,
        db: Session,
        request: PlanRequest,
        *,
        causation_id: UUID | None = None,
    ) -> PlanVersionRead:
        now = self.clock.now() if request.now is None else request.now
        request = request.model_copy(update={"now": now})
        head = db.scalar(
            select(PlanHeadRow)
            .where(
                PlanHeadRow.plan_date == request.plan_date,
                PlanHeadRow.display_timezone == request.display_timezone,
            )
            .with_for_update()
        )
        latest_revision = db.scalar(
            select(func.max(PlanVersionRow.revision)).where(
                PlanVersionRow.plan_date == request.plan_date,
                PlanVersionRow.display_timezone == request.display_timezone,
            )
        )
        current = None
        if head is not None:
            current_row = db.get(PlanVersionRow, head.current_plan_version_id)
            if current_row is None:
                raise NotFoundError("PlanVersion", head.current_plan_version_id)
            current = plan_read(db, current_row)
        tasks = [
            task_read(row)
            for row in db.scalars(
                select(TaskRow).where(TaskRow.status.not_in(["COMPLETED", "CANCELLED"]))
            ).all()
        ]
        day_start, day_end = self._day_horizon(request)
        fixed = [
            fixed_event_read(row)
            for row in db.scalars(
                select(FixedEventRow)
                .where(FixedEventRow.end_at > day_start, FixedEventRow.start_at < day_end)
                .order_by(FixedEventRow.start_at, FixedEventRow.fixed_event_id)
            ).all()
        ]

        if current is None:
            result = plan_day(request, tasks, fixed, revision=(latest_revision or 0) + 1)
        else:
            accepted_times = [
                value
                for value in db.scalars(
                    select(PlanVersionRow.created_at).where(
                        PlanVersionRow.plan_date == request.plan_date,
                        PlanVersionRow.display_timezone == request.display_timezone,
                        PlanVersionRow.created_at >= now - timedelta(hours=1),
                        PlanVersionRow.trigger.not_in(MANUAL_TRIGGERS),
                    )
                ).all()
            ]
            revision_base = current.model_copy(
                update={"revision": max(current.revision, latest_revision or 0)}
            )
            replanned = replan_day(
                request,
                tasks,
                fixed,
                revision_base,
                accepted_automatic_replans=accepted_times,
            )
            if not replanned.accepted or replanned.plan is None:
                reason = replanned.reason_codes[0]
                raise LifeOSError(
                    reason,
                    "automatic replan was rejected by the persistent safety gate",
                    429,
                    list(replanned.reason_codes),
                )
            result = replanned.plan
        return self._persist(db, result, tasks, head, causation_id=causation_id)

    def current(self, db: Session, plan_date: date, display_timezone: str) -> PlanVersionRead:
        head = db.scalar(
            select(PlanHeadRow).where(
                PlanHeadRow.plan_date == plan_date,
                PlanHeadRow.display_timezone == display_timezone,
            )
        )
        if head is None:
            raise NotFoundError("CurrentPlan", f"{plan_date}/{display_timezone}")
        row = db.get(PlanVersionRow, head.current_plan_version_id)
        if row is None:
            raise NotFoundError("PlanVersion", head.current_plan_version_id)
        return plan_read(db, row)

    def history(self, db: Session, plan_date: date, display_timezone: str) -> list[PlanVersionRead]:
        rows = db.scalars(
            select(PlanVersionRow)
            .where(
                PlanVersionRow.plan_date == plan_date,
                PlanVersionRow.display_timezone == display_timezone,
            )
            .order_by(PlanVersionRow.revision)
        ).all()
        return [plan_read(db, row) for row in rows]

    def insert_break(
        self, db: Session, session_id: UUID, *, duration_minutes: int
    ) -> PlanVersionRead:
        from ..models import ExecutionSessionRow

        session = db.get(ExecutionSessionRow, session_id)
        if session is None:
            raise NotFoundError("ExecutionSession", session_id)
        current_row = db.get(PlanVersionRow, session.plan_version_id)
        if current_row is None:
            raise NotFoundError("PlanVersion", session.plan_version_id)
        head = db.scalar(
            select(PlanHeadRow)
            .where(
                PlanHeadRow.plan_date == current_row.plan_date,
                PlanHeadRow.display_timezone == current_row.display_timezone,
            )
            .with_for_update()
        )
        if head is None or head.current_plan_version_id != current_row.plan_version_id:
            raise LifeOSError(
                "PLAN_VERSION_STALE",
                "session is not attached to the current plan version",
                409,
                ["PLAN_VERSION_STALE"],
            )
        current = plan_read(db, current_row)
        now = self.clock.now()
        request = PlanRequest(
            plan_date=current.plan_date,
            display_timezone=current.display_timezone,
            trigger=PlanTrigger.USER_REPORTED_FATIGUE,
            now=now,
            parameters=current.parameters,
        )
        accepted_times = db.scalars(
            select(PlanVersionRow.created_at).where(
                PlanVersionRow.plan_date == current.plan_date,
                PlanVersionRow.display_timezone == current.display_timezone,
                PlanVersionRow.created_at >= now - timedelta(hours=1),
                PlanVersionRow.trigger.not_in(MANUAL_TRIGGERS),
            )
        ).all()
        gate = check_replan_gate(
            request.trigger,
            now=now,
            accepted_automatic_replans=accepted_times,
            parameters=request.parameters,
        )
        if not gate.accepted:
            raise LifeOSError(
                gate.reason_code,
                "break-triggered replan was rejected by the persistent safety gate",
                429,
                [gate.reason_code],
            )
        tasks = [
            task_read(row)
            for row in db.scalars(
                select(TaskRow).where(TaskRow.status.not_in(["COMPLETED", "CANCELLED"]))
            ).all()
        ]
        day_start, day_end = self._day_horizon(request)
        fixed = [
            fixed_event_read(row)
            for row in db.scalars(
                select(FixedEventRow).where(
                    FixedEventRow.end_at > day_start,
                    FixedEventRow.start_at < day_end,
                )
            ).all()
        ]
        break_block = ScheduleBlockRead(
            block_id=uuid5(current.plan_version_id, f"break:{now.isoformat()}"),
            kind=BlockKind.BREAK,
            title=f"User break ({duration_minutes} min)",
            start_at=now,
            end_at=now + timedelta(minutes=duration_minutes),
            task_id=None,
            fixed_event_id=None,
            source_block_id=None,
            hardness=Hardness.REQUIRED,
            activity_profile=ActivityProfile.OTHER,
            reason_codes=["USER_REPORTED_FATIGUE", "BREAK_REQUIRED"],
        )
        latest_revision = db.scalar(
            select(func.max(PlanVersionRow.revision)).where(
                PlanVersionRow.plan_date == current.plan_date,
                PlanVersionRow.display_timezone == current.display_timezone,
            )
        )
        plan = plan_day(
            request,
            tasks,
            fixed,
            revision=(latest_revision or current.revision) + 1,
            based_on_plan_version_id=current.plan_version_id,
            frozen_blocks=[break_block],
        )
        plan = plan.model_copy(
            update={
                "blocks": [
                    block.model_copy(update={"source_block_id": None})
                    if "USER_REPORTED_FATIGUE" in block.reason_codes
                    else block
                    for block in plan.blocks
                ]
            }
        )
        return self._persist(db, plan, tasks, head)

    def _persist(
        self,
        db: Session,
        plan: PlanVersionRead,
        tasks: list[TaskRead],
        head: PlanHeadRow | None,
        *,
        causation_id: UUID | None = None,
    ) -> PlanVersionRead:
        row = PlanVersionRow(
            plan_version_id=plan.plan_version_id,
            plan_date=plan.plan_date,
            display_timezone=plan.display_timezone,
            revision=plan.revision,
            based_on_plan_version_id=plan.based_on_plan_version_id,
            trigger=plan.trigger,
            status=plan.status,
            algorithm_version=plan.algorithm_version,
            created_at=plan.created_at,
            created_state_version=plan.created_state_version,
            parameters=plan.parameters.model_dump(mode="json"),
            conflicts=[conflict.model_dump(mode="json") for conflict in plan.conflicts],
            reason_codes=plan.reason_codes,
        )
        db.add(row)
        db.flush()
        app_rules = {item.task_id: (item.allowed_apps, item.blocked_apps) for item in tasks}
        for block in plan.blocks:
            allowed, blocked = (
                app_rules.get(block.task_id, ([], [])) if block.task_id is not None else ([], [])
            )
            db.add(
                ScheduleBlockRow(
                    block_id=block.block_id,
                    plan_version_id=row.plan_version_id,
                    kind=block.kind,
                    title=block.title,
                    start_at=block.start_at,
                    end_at=block.end_at,
                    task_id=block.task_id,
                    fixed_event_id=block.fixed_event_id,
                    source_block_id=block.source_block_id,
                    hardness=block.hardness,
                    activity_profile=block.activity_profile,
                    allowed_apps=allowed,
                    blocked_apps=blocked,
                    reason_codes=block.reason_codes,
                )
            )
        if plan.status != "INFEASIBLE":
            if head is None:
                db.add(
                    PlanHeadRow(
                        plan_date=plan.plan_date,
                        display_timezone=plan.display_timezone,
                        current_plan_version_id=plan.plan_version_id,
                        revision=plan.revision,
                        updated_at=plan.created_at,
                    )
                )
            else:
                head.current_plan_version_id = plan.plan_version_id
                head.revision = plan.revision
                head.updated_at = plan.created_at
        db.flush()
        append_event(
            db,
            event_type="PLAN.VERSION_CREATED",
            occurred_at=plan.created_at,
            received_at=plan.created_at,
            source="core",
            entity_type="PlanVersion",
            entity_id=plan.plan_version_id,
            causation_id=causation_id,
            idempotency_key=f"plan:create:{plan.plan_version_id}",
            payload={
                "revision": plan.revision,
                "trigger": plan.trigger,
                "status": plan.status,
                "based_on_plan_version_id": str(plan.based_on_plan_version_id)
                if plan.based_on_plan_version_id
                else None,
            },
            reason_codes=plan.reason_codes,
        )
        return plan_read(db, row)

    @staticmethod
    def _day_horizon(request: PlanRequest) -> tuple[datetime, datetime]:
        zone = ZoneInfo(request.display_timezone)
        start = datetime.combine(
            request.plan_date, time.fromisoformat(request.available_start_local), zone
        )
        end = datetime.combine(
            request.plan_date, time.fromisoformat(request.available_end_local), zone
        )
        return start, end
