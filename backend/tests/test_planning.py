from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from lifeos.planning import check_replan_gate, plan_day, replan_day
from lifeos.schemas import (
    ActivityProfile,
    FixedEventRead,
    PlanRequest,
    PlanTrigger,
    TaskRead,
    TaskStatus,
)

PLAN_DATE = date(2026, 8, 29)
ZONE = ZoneInfo("Asia/Shanghai")


def local_time(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 29, hour, minute, tzinfo=ZONE).astimezone(UTC)


def fixed_event(identifier: int, title: str, start: int, end: int) -> FixedEventRead:
    created = local_time(6)
    return FixedEventRead(
        fixed_event_id=UUID(int=identifier),
        title=title,
        start_at=local_time(start),
        end_at=local_time(end),
        activity_profile=ActivityProfile.CLASS,
        created_at=created,
        updated_at=created,
        version=1,
    )


def task(identifier: int, title: str, minutes: int, priority: int) -> TaskRead:
    created = local_time(6)
    return TaskRead(
        task_id=UUID(int=identifier),
        title=title,
        status=TaskStatus.READY,
        priority=priority,
        mandatory=True,
        estimated_minutes=minutes,
        remaining_minutes=minutes,
        minimum_chunk_minutes=30,
        activity_profile=ActivityProfile.READING,
        created_at=created,
        updated_at=created,
        version=1,
    )


def request(
    trigger: PlanTrigger = PlanTrigger.DAY_STARTED,
    now: datetime | None = None,
) -> PlanRequest:
    return PlanRequest(
        plan_date=PLAN_DATE,
        display_timezone="Asia/Shanghai",
        trigger=trigger,
        now=now or local_time(7),
    )


def test_three_classes_and_two_tasks_make_deterministic_non_overlapping_plan() -> None:
    classes = [
        fixed_event(101, "Class A", 8, 9),
        fixed_event(102, "Class B", 10, 11),
        fixed_event(103, "Class C", 14, 15),
    ]
    tasks = [task(201, "English", 60, 4), task(202, "Research", 90, 5)]

    first = plan_day(request(), tasks, classes)
    second = plan_day(request(), tasks, classes)

    assert first.status == "FEASIBLE"
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    ordered = sorted(first.blocks, key=lambda block: block.start_at)
    assert all(
        left.end_at <= right.start_at for left, right in zip(ordered, ordered[1:], strict=False)
    )
    assert {block.title for block in first.blocks if block.kind == "TASK"} == {
        "English",
        "Research",
    }
    assert {block.title for block in first.blocks if block.kind == "MEAL"} == {
        "Lunch",
        "Dinner",
    }
    assert all(block.start_at.tzinfo is not None for block in first.blocks)


def test_overlapping_hard_events_create_infeasibility_report() -> None:
    plan = plan_day(
        request(),
        [],
        [fixed_event(301, "Overlap A", 8, 10), fixed_event(302, "Overlap B", 9, 11)],
    )

    assert plan.status == "INFEASIBLE"
    assert plan.blocks == []
    assert plan.conflicts[0].code == "HARD_EVENT_OVERLAP"
    assert plan.conflicts[0].severity == "ERROR"
    assert plan.reason_codes[-1] == "PLAN_INFEASIBLE"


def test_replan_creates_new_revision_and_gate_limits_automatic_attempts() -> None:
    tasks = [task(401, "English", 60, 4)]
    initial = plan_day(request(), tasks, [])
    late_request = request(PlanTrigger.BLOCK_MISSED, local_time(9, 5))

    result = replan_day(late_request, tasks, [], initial)

    assert result.accepted is True
    assert result.plan is not None
    assert result.plan.revision == initial.revision + 1
    assert result.plan.based_on_plan_version_id == initial.plan_version_id
    assert result.plan.plan_version_id != initial.plan_version_id
    assert initial.revision == 1

    debounced = check_replan_gate(
        PlanTrigger.BLOCK_MISSED,
        now=local_time(9, 5),
        accepted_automatic_replans=[local_time(9, 4)],
        parameters=late_request.parameters,
    )
    assert debounced.accepted is False
    assert debounced.reason_code == "REPLAN_DEBOUNCED"

    manual = check_replan_gate(
        PlanTrigger.USER_REQUESTED_REPLAN,
        now=local_time(9, 5),
        accepted_automatic_replans=[local_time(9, 5) - timedelta(seconds=1)] * 3,
        parameters=late_request.parameters,
    )
    assert manual.accepted is True
