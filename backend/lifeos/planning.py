from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import floor
from typing import Literal
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from lifeos.schemas import (
    ActivityProfile,
    BlockKind,
    FixedEventRead,
    Hardness,
    PlanConflict,
    PlannerParameters,
    PlanRequest,
    PlanStatus,
    PlanTrigger,
    PlanVersionRead,
    ScheduleBlockRead,
    TaskRead,
    TaskStatus,
    utc,
)

ALGORITHM_VERSION = "deterministic-v1"
_PLAN_NAMESPACE = UUID("9f83b07d-53cf-4a98-8cd1-142d167f7b2d")
_MANUAL_TRIGGERS = {
    PlanTrigger.USER_REQUESTED_REPLAN,
    PlanTrigger.USER_REPORTED_EMERGENCY,
}


@dataclass(slots=True)
class _Interval:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return max(0, int((self.end - self.start).total_seconds() // 60))


@dataclass(frozen=True, slots=True)
class ReplanGate:
    accepted: bool
    reason_code: str


@dataclass(frozen=True, slots=True)
class ReplanResult:
    accepted: bool
    reason_codes: tuple[str, ...]
    plan: PlanVersionRead | None


def check_replan_gate(
    trigger: PlanTrigger,
    *,
    now: datetime,
    accepted_automatic_replans: Sequence[datetime],
    parameters: PlannerParameters,
) -> ReplanGate:
    """Apply the debounce and rolling-hour cap to automatic replan attempts."""
    now = utc(now)
    if trigger in _MANUAL_TRIGGERS:
        return ReplanGate(True, str(trigger))

    recent = sorted(
        utc(item)
        for item in accepted_automatic_replans
        if timedelta(0) <= now - utc(item) < timedelta(hours=1)
    )
    if recent and (now - recent[-1]).total_seconds() < parameters.replan_debounce_seconds:
        return ReplanGate(False, "REPLAN_DEBOUNCED")
    if len(recent) >= parameters.maximum_automatic_replans_per_hour:
        return ReplanGate(False, "REPLAN_RATE_LIMITED")
    return ReplanGate(True, str(trigger))


def plan_day(
    request: PlanRequest,
    tasks: Sequence[TaskRead],
    fixed_events: Sequence[FixedEventRead],
    *,
    revision: int = 1,
    based_on_plan_version_id: UUID | None = None,
    created_state_version: int | None = None,
    frozen_blocks: Sequence[ScheduleBlockRead] = (),
) -> PlanVersionRead:
    """Build one immutable deterministic plan attempt from frozen contract models."""
    if request.now is None:
        raise ValueError("PlanRequest.now is required at the deterministic planner boundary")
    if revision < 1:
        raise ValueError("revision must be positive")

    now = utc(request.now)
    day_start, day_end = _day_bounds(
        request.plan_date,
        request.display_timezone,
        request.available_start_local,
        request.available_end_local,
    )
    planning_start = max(day_start, now)
    plan_id = _plan_id(request, revision, based_on_plan_version_id, now)
    conflicts: list[PlanConflict] = []
    blocks: list[ScheduleBlockRead] = []

    fixed_blocks = _fixed_blocks(
        plan_id,
        fixed_events,
        day_start,
        planning_start,
        day_end,
        conflicts,
    )
    blocks.extend(fixed_blocks)
    blocks.extend(_clone_frozen_blocks(plan_id, frozen_blocks, planning_start, day_end))
    overlap = _first_overlap(blocks)
    if overlap is not None:
        left, right = overlap
        conflict_code = (
            "TRAVEL_OVERLAP"
            if BlockKind.TRAVEL in {left.kind, right.kind}
            else "HARD_EVENT_OVERLAP"
        )
        conflicts.append(
            _conflict(
                conflict_code,
                [identifier for identifier in _block_entities(left, right)],
                max(left.start_at, right.start_at),
                min(left.end_at, right.end_at),
                "Required schedule blocks overlap.",
            )
        )
        return _plan_result(
            request,
            plan_id,
            revision,
            based_on_plan_version_id,
            created_state_version,
            now,
            [],
            conflicts,
        )

    blocks.extend(_place_meals(plan_id, request, planning_start, day_end, blocks, conflicts))
    task_intervals, buffer_blocks = _reserve_buffer(
        plan_id,
        _free_intervals(planning_start, day_end, blocks),
        request.parameters.buffer_ratio,
    )
    blocks.extend(buffer_blocks)

    remaining = {task.task_id: task.remaining_minutes for task in tasks}
    for block in blocks:
        if block.kind == BlockKind.TASK and block.task_id in remaining:
            remaining[block.task_id] = max(
                0,
                remaining[block.task_id] - _minutes(block.start_at, block.end_at),
            )

    task_blocks, break_blocks = _place_tasks(
        plan_id,
        tasks,
        remaining,
        task_intervals,
        blocks,
        request,
        planning_start,
        day_end,
        conflicts,
    )
    blocks.extend(task_blocks)
    blocks.extend(break_blocks)
    blocks.sort(key=lambda block: (block.start_at, block.end_at, str(block.block_id)))

    final_overlap = _first_overlap(blocks)
    if final_overlap is not None:
        left, right = final_overlap
        conflicts.append(
            _conflict(
                "HARD_EVENT_OVERLAP",
                list(_block_entities(left, right)),
                max(left.start_at, right.start_at),
                min(left.end_at, right.end_at),
                "Planner produced overlapping blocks.",
            )
        )

    return _plan_result(
        request,
        plan_id,
        revision,
        based_on_plan_version_id,
        created_state_version,
        now,
        blocks,
        conflicts,
    )


def replan_day(
    request: PlanRequest,
    tasks: Sequence[TaskRead],
    fixed_events: Sequence[FixedEventRead],
    current_plan: PlanVersionRead,
    *,
    accepted_automatic_replans: Sequence[datetime] = (),
    created_state_version: int | None = None,
) -> ReplanResult:
    """Gate a replan and preserve still-possible near-horizon flexible blocks."""
    if request.now is None:
        raise ValueError("PlanRequest.now is required for replanning")
    now = utc(request.now)
    gate = check_replan_gate(
        request.trigger,
        now=now,
        accepted_automatic_replans=accepted_automatic_replans,
        parameters=request.parameters,
    )
    if not gate.accepted:
        return ReplanResult(False, (gate.reason_code,), None)

    frozen: list[ScheduleBlockRead] = []
    if request.trigger != PlanTrigger.USER_REPORTED_EMERGENCY:
        cutoff = now + timedelta(minutes=request.parameters.freeze_horizon_minutes)
        frozen = [
            block
            for block in current_plan.blocks
            if block.kind in {BlockKind.TASK, BlockKind.BREAK, BlockKind.BUFFER}
            and now <= block.start_at < cutoff
        ]

    plan = plan_day(
        request,
        tasks,
        fixed_events,
        revision=current_plan.revision + 1,
        based_on_plan_version_id=current_plan.plan_version_id,
        created_state_version=created_state_version,
        frozen_blocks=frozen,
    )
    return ReplanResult(True, (gate.reason_code,), plan)


def _day_bounds(
    plan_date: date,
    timezone_name: str,
    start_text: str,
    end_text: str,
) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone_name)
    start_local = datetime.combine(plan_date, time.fromisoformat(start_text), zone)
    end_local = datetime.combine(plan_date, time.fromisoformat(end_text), zone)
    if end_local <= start_local:
        raise ValueError("available_end_local must be after available_start_local")
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _plan_id(
    request: PlanRequest,
    revision: int,
    based_on: UUID | None,
    now: datetime,
) -> UUID:
    key = "|".join(
        (
            request.plan_date.isoformat(),
            request.display_timezone,
            str(revision),
            str(request.trigger),
            str(based_on),
            now.isoformat(),
        )
    )
    return uuid5(_PLAN_NAMESPACE, key)


def _fixed_blocks(
    plan_id: UUID,
    fixed_events: Sequence[FixedEventRead],
    day_start: datetime,
    planning_start: datetime,
    day_end: datetime,
    conflicts: list[PlanConflict],
) -> list[ScheduleBlockRead]:
    blocks: list[ScheduleBlockRead] = []
    for event in sorted(fixed_events, key=lambda item: (item.start_at, str(item.fixed_event_id))):
        start = utc(event.start_at)
        end = utc(event.end_at)
        if start < day_start or end > day_end:
            conflicts.append(
                _conflict(
                    "HARD_EVENT_OVERLAP",
                    [event.fixed_event_id],
                    start,
                    end,
                    "Hard fixed event falls outside the configured day horizon.",
                )
            )
            continue
        if end <= planning_start or start >= day_end:
            continue
        travel_start = start - timedelta(minutes=event.travel_before_minutes)
        travel_end = end + timedelta(minutes=event.travel_after_minutes)
        if travel_start < planning_start or travel_end > day_end:
            conflicts.append(
                _conflict(
                    "TRAVEL_OVERLAP" if event.travel_before_minutes else "HARD_EVENT_OVERLAP",
                    [event.fixed_event_id],
                    travel_start,
                    travel_end,
                    "Fixed event or required travel falls outside the remaining day horizon.",
                )
            )
            continue
        if event.travel_before_minutes:
            blocks.append(
                _make_block(
                    plan_id,
                    BlockKind.TRAVEL,
                    f"Travel to {event.title}",
                    travel_start,
                    start,
                    fixed_event_id=event.fixed_event_id,
                    hardness=Hardness.REQUIRED,
                    reason_codes=["TRAVEL_REQUIRED"],
                )
            )
        blocks.append(
            _make_block(
                plan_id,
                BlockKind.FIXED_EVENT,
                event.title,
                start,
                end,
                fixed_event_id=event.fixed_event_id,
                hardness=Hardness.HARD,
                activity_profile=event.activity_profile,
                reason_codes=["HARD_FIXED_EVENT"],
            )
        )
        if event.travel_after_minutes:
            blocks.append(
                _make_block(
                    plan_id,
                    BlockKind.TRAVEL,
                    f"Travel from {event.title}",
                    end,
                    travel_end,
                    fixed_event_id=event.fixed_event_id,
                    hardness=Hardness.REQUIRED,
                    reason_codes=["TRAVEL_REQUIRED"],
                )
            )
    return blocks


def _clone_frozen_blocks(
    plan_id: UUID,
    blocks: Sequence[ScheduleBlockRead],
    planning_start: datetime,
    day_end: datetime,
) -> list[ScheduleBlockRead]:
    return [
        _make_block(
            plan_id,
            block.kind,
            block.title,
            block.start_at,
            block.end_at,
            task_id=block.task_id,
            fixed_event_id=block.fixed_event_id,
            source_block_id=block.block_id,
            hardness=block.hardness,
            activity_profile=block.activity_profile,
            reason_codes=[*block.reason_codes, "FREEZE_HORIZON_PRESERVED"],
        )
        for block in blocks
        if planning_start <= block.start_at and block.end_at <= day_end
    ]


def _place_meals(
    plan_id: UUID,
    request: PlanRequest,
    planning_start: datetime,
    day_end: datetime,
    occupied: Sequence[ScheduleBlockRead],
    conflicts: list[PlanConflict],
) -> list[ScheduleBlockRead]:
    zone = ZoneInfo(request.display_timezone)
    meal_blocks: list[ScheduleBlockRead] = []
    horizon_blocks = list(occupied)
    duration = timedelta(minutes=30)
    for title, start_local, end_local in (
        ("Lunch", time(11, 30), time(13, 30)),
        ("Dinner", time(17, 30), time(19, 30)),
    ):
        window_start = datetime.combine(request.plan_date, start_local, zone).astimezone(UTC)
        window_end = datetime.combine(request.plan_date, end_local, zone).astimezone(UTC)
        if window_end <= planning_start or window_start >= day_end:
            continue
        slot = _first_slot(
            _free_intervals(planning_start, day_end, horizon_blocks),
            max(window_start, planning_start),
            min(window_end, day_end),
            duration,
        )
        if slot is None:
            conflicts.append(
                _conflict(
                    "MEAL_UNPLACEABLE",
                    [],
                    max(window_start, planning_start),
                    min(window_end, day_end),
                    f"{title} has no available 30-minute slot.",
                    required_minutes=30,
                    available_minutes=0,
                )
            )
            continue
        block = _make_block(
            plan_id,
            BlockKind.MEAL,
            title,
            slot,
            slot + duration,
            hardness=Hardness.REQUIRED,
            reason_codes=["MEAL_REQUIRED"],
        )
        meal_blocks.append(block)
        horizon_blocks.append(block)
    return meal_blocks


def _reserve_buffer(
    plan_id: UUID,
    intervals: Sequence[_Interval],
    ratio: float,
) -> tuple[list[_Interval], list[ScheduleBlockRead]]:
    total_minutes = sum(interval.minutes for interval in intervals)
    target = floor(total_minutes * ratio / 5) * 5
    allocations = [floor(interval.minutes * ratio / 5) * 5 for interval in intervals]
    remaining = target - sum(allocations)
    allocation_order = sorted(
        range(len(intervals)),
        key=lambda item: intervals[item].minutes,
        reverse=True,
    )
    for index in allocation_order:
        if remaining < 5:
            break
        if intervals[index].minutes - allocations[index] >= 10:
            allocations[index] += 5
            remaining -= 5

    task_intervals: list[_Interval] = []
    buffer_blocks: list[ScheduleBlockRead] = []
    for interval, buffer_minutes in zip(intervals, allocations, strict=True):
        buffer_start = interval.end - timedelta(minutes=buffer_minutes)
        if interval.start < buffer_start:
            task_intervals.append(_Interval(interval.start, buffer_start))
        if buffer_minutes:
            buffer_blocks.append(
                _make_block(
                    plan_id,
                    BlockKind.BUFFER,
                    "Buffer",
                    buffer_start,
                    interval.end,
                    hardness=Hardness.REQUIRED,
                    reason_codes=["BUFFER_RESERVED"],
                )
            )
    return task_intervals, buffer_blocks


def _place_tasks(
    plan_id: UUID,
    tasks: Sequence[TaskRead],
    remaining: dict[UUID, int],
    intervals: list[_Interval],
    resting_blocks: Sequence[ScheduleBlockRead],
    request: PlanRequest,
    planning_start: datetime,
    day_end: datetime,
    conflicts: list[PlanConflict],
) -> tuple[list[ScheduleBlockRead], list[ScheduleBlockRead]]:
    active = [
        task
        for task in tasks
        if task.status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}
        and remaining[task.task_id] > 0
    ]
    active.sort(key=lambda task: _task_rank(task, intervals, planning_start, day_end))
    task_blocks: list[ScheduleBlockRead] = []
    break_blocks: list[ScheduleBlockRead] = []

    for task in active:
        task_remaining = remaining[task.task_id]
        mismatch = _task_mismatch(task, request)
        if mismatch is not None:
            conflicts.append(
                _conflict(
                    mismatch,
                    [task.task_id],
                    planning_start,
                    day_end,
                    f"Task {task.title!r} is incompatible with available context.",
                    required_minutes=task_remaining,
                    available_minutes=0,
                    severity="ERROR" if task.mandatory or task.deadline else "WARNING",
                )
            )
            continue

        if task_remaining < task.minimum_chunk_minutes:
            conflicts.append(
                _conflict(
                    "MINIMUM_CHUNK_UNAVAILABLE",
                    [task.task_id],
                    planning_start,
                    min(task.deadline or day_end, day_end),
                    f"Remaining work for {task.title!r} is below its minimum chunk.",
                    required_minutes=task.minimum_chunk_minutes,
                    available_minutes=task_remaining,
                    severity="ERROR" if task.mandatory or task.deadline else "WARNING",
                )
            )
            continue

        for interval in intervals:
            while task_remaining >= task.minimum_chunk_minutes and interval.minutes:
                deadline = min(utc(task.deadline), day_end) if task.deadline else day_end
                if interval.start >= deadline:
                    break
                latest_task_end = min(interval.end, deadline)
                available_task_minutes = _minutes(interval.start, latest_task_end)
                if available_task_minutes < task.minimum_chunk_minutes:
                    break

                rest_supplied = _rest_follows(
                    interval.end, resting_blocks, request.parameters.break_minutes
                )
                capacity = available_task_minutes
                if not rest_supplied:
                    capacity = min(
                        capacity,
                        max(0, interval.minutes - request.parameters.break_minutes),
                    )
                chunk = _chunk_minutes(task, task_remaining, capacity, request.parameters)
                if chunk < task.minimum_chunk_minutes:
                    break

                task_end = interval.start + timedelta(minutes=chunk)
                task_blocks.append(
                    _make_block(
                        plan_id,
                        BlockKind.TASK,
                        task.title,
                        interval.start,
                        task_end,
                        task_id=task.task_id,
                        hardness=(
                            Hardness.REQUIRED
                            if task.mandatory or task.deadline is not None
                            else Hardness.SOFT
                        ),
                        activity_profile=task.activity_profile,
                        reason_codes=["TASK_PRIORITY_ORDER"],
                    )
                )
                task_remaining -= chunk
                interval.start = task_end

                if not _rest_follows(
                    interval.start, resting_blocks, request.parameters.break_minutes
                ):
                    break_end = interval.start + timedelta(minutes=request.parameters.break_minutes)
                    if break_end <= interval.end:
                        break_blocks.append(
                            _make_block(
                                plan_id,
                                BlockKind.BREAK,
                                "Break",
                                interval.start,
                                break_end,
                                hardness=Hardness.REQUIRED,
                                reason_codes=["BREAK_REQUIRED"],
                            )
                        )
                        interval.start = break_end
                if task_remaining == 0:
                    break
            if task_remaining == 0:
                break

        remaining[task.task_id] = task_remaining
        if task_remaining:
            required = task.mandatory or task.deadline is not None
            code = "DEADLINE_MISSED" if task.deadline else "MANDATORY_WORK_UNSCHEDULED"
            if not required:
                code = "OPTIONAL_WORK_UNSCHEDULED"
            conflicts.append(
                _conflict(
                    code,
                    [task.task_id],
                    planning_start,
                    min(utc(task.deadline), day_end) if task.deadline else day_end,
                    f"{task_remaining} minutes of {task.title!r} remain unscheduled.",
                    required_minutes=task_remaining,
                    available_minutes=0,
                    severity="ERROR" if required else "WARNING",
                )
            )
    return task_blocks, break_blocks


def _task_rank(
    task: TaskRead,
    intervals: Sequence[_Interval],
    planning_start: datetime,
    day_end: datetime,
) -> tuple[bool, bool, float, int, datetime, str]:
    deadline = utc(task.deadline) if task.deadline else day_end + timedelta(days=36500)
    has_deadline = task.deadline is not None
    overdue = has_deadline and deadline <= planning_start
    available = sum(
        _minutes(interval.start, min(interval.end, deadline))
        for interval in intervals
        if interval.start < deadline
    )
    pressure = task.remaining_minutes / max(available, 1)
    return (
        not (overdue or has_deadline),
        not task.mandatory,
        -pressure,
        -task.priority,
        deadline,
        str(task.task_id),
    )


def _task_mismatch(task: TaskRead, request: PlanRequest) -> str | None:
    if task.required_location and task.required_location != request.available_location:
        return "LOCATION_MISMATCH"
    available = set(request.available_device_capabilities)
    if not set(task.required_device_capabilities).issubset(available):
        return "DEVICE_MISMATCH"
    return None


def _chunk_minutes(
    task: TaskRead,
    remaining: int,
    capacity: int,
    parameters: PlannerParameters,
) -> int:
    capacity = min(capacity, parameters.max_focus_minutes)
    if remaining <= capacity:
        return remaining
    chunk = min(parameters.focus_minutes, capacity)
    residual = remaining - chunk
    if 0 < residual < task.minimum_chunk_minutes:
        chunk -= task.minimum_chunk_minutes - residual
    return max(0, chunk)


def _free_intervals(
    start: datetime,
    end: datetime,
    occupied: Sequence[ScheduleBlockRead],
) -> list[_Interval]:
    intervals: list[_Interval] = []
    cursor = start
    for block in sorted(occupied, key=lambda item: (item.start_at, item.end_at)):
        if block.end_at <= start or block.start_at >= end:
            continue
        block_start = max(start, block.start_at)
        block_end = min(end, block.end_at)
        if cursor < block_start:
            intervals.append(_Interval(cursor, block_start))
        cursor = max(cursor, block_end)
    if cursor < end:
        intervals.append(_Interval(cursor, end))
    return intervals


def _first_slot(
    intervals: Sequence[_Interval],
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
) -> datetime | None:
    for interval in intervals:
        start = max(interval.start, window_start)
        if start + duration <= min(interval.end, window_end):
            return start
    return None


def _rest_follows(
    at: datetime, blocks: Sequence[ScheduleBlockRead], required_minutes: int
) -> bool:
    return any(
        block.start_at == at
        and block.kind in {BlockKind.FIXED_EVENT, BlockKind.MEAL, BlockKind.BUFFER, BlockKind.BREAK}
        and _minutes(block.start_at, block.end_at) >= required_minutes
        for block in blocks
    )


def _make_block(
    plan_id: UUID,
    kind: BlockKind,
    title: str,
    start: datetime,
    end: datetime,
    *,
    task_id: UUID | None = None,
    fixed_event_id: UUID | None = None,
    source_block_id: UUID | None = None,
    hardness: Hardness = Hardness.SOFT,
    activity_profile: ActivityProfile = ActivityProfile.OTHER,
    reason_codes: Sequence[str],
) -> ScheduleBlockRead:
    source = task_id or fixed_event_id or source_block_id or "system"
    key = f"{kind}|{source}|{utc(start).isoformat()}|{utc(end).isoformat()}|{title}"
    return ScheduleBlockRead(
        block_id=uuid5(plan_id, key),
        kind=kind,
        title=title,
        start_at=utc(start),
        end_at=utc(end),
        task_id=task_id,
        fixed_event_id=fixed_event_id,
        source_block_id=source_block_id,
        hardness=hardness,
        activity_profile=activity_profile,
        reason_codes=list(dict.fromkeys(reason_codes)),
    )


def _first_overlap(
    blocks: Sequence[ScheduleBlockRead],
) -> tuple[ScheduleBlockRead, ScheduleBlockRead] | None:
    ordered = sorted(blocks, key=lambda item: (item.start_at, item.end_at))
    for left, right in zip(ordered, ordered[1:], strict=False):
        if right.start_at < left.end_at:
            return left, right
    return None


def _block_entities(*blocks: ScheduleBlockRead) -> Iterable[UUID]:
    seen: set[UUID] = set()
    for block in blocks:
        identifier = block.task_id or block.fixed_event_id or block.block_id
        if identifier not in seen:
            seen.add(identifier)
            yield identifier


def _conflict(
    code: str,
    entity_ids: Sequence[UUID],
    start: datetime | None,
    end: datetime | None,
    detail: str,
    *,
    required_minutes: int | None = None,
    available_minutes: int | None = None,
    severity: Literal["WARNING", "ERROR"] = "ERROR",
) -> PlanConflict:
    return PlanConflict(
        code=code,
        severity=severity,
        entity_ids=list(dict.fromkeys(entity_ids)),
        start_at=utc(start) if start else None,
        end_at=utc(end) if end else None,
        required_minutes=required_minutes,
        available_minutes=available_minutes,
        detail=detail,
    )


def _plan_result(
    request: PlanRequest,
    plan_id: UUID,
    revision: int,
    based_on: UUID | None,
    state_version: int | None,
    created_at: datetime,
    blocks: Sequence[ScheduleBlockRead],
    conflicts: Sequence[PlanConflict],
) -> PlanVersionRead:
    has_error = any(conflict.severity == "ERROR" for conflict in conflicts)
    has_warning = any(conflict.severity == "WARNING" for conflict in conflicts)
    if has_error:
        status = PlanStatus.INFEASIBLE
    elif has_warning:
        status = PlanStatus.PARTIAL
    else:
        status = PlanStatus.FEASIBLE
    reason = {
        PlanStatus.FEASIBLE: "PLAN_FEASIBLE",
        PlanStatus.PARTIAL: "PLAN_PARTIAL",
        PlanStatus.INFEASIBLE: "PLAN_INFEASIBLE",
    }[status]
    return PlanVersionRead(
        plan_version_id=plan_id,
        plan_date=request.plan_date,
        display_timezone=request.display_timezone,
        revision=revision,
        based_on_plan_version_id=based_on,
        trigger=request.trigger,
        status=status,
        algorithm_version=ALGORITHM_VERSION,
        created_at=created_at,
        created_state_version=state_version,
        parameters=request.parameters,
        blocks=list(blocks),
        conflicts=list(conflicts),
        reason_codes=[str(request.trigger), reason],
    )


def _minutes(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() // 60))
