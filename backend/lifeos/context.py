from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from .schemas import AIPlanningRequest


def build_planning_context(
    *,
    now: datetime,
    runtime_state: dict[str, Any] | None,
    current_plan: dict[str, Any] | None,
    current_block_id: UUID | None,
    future_blocks: Sequence[dict[str, Any]],
    today_progress: dict[str, Any],
    unfinished_tasks: Sequence[dict[str, Any]],
    active_incident: dict[str, Any] | None,
    policy_constraints: dict[str, Any],
) -> AIPlanningRequest:
    """Build the always-on bounded context; no archive dependency is accepted."""

    return AIPlanningRequest(
        request_id=uuid4(),
        requested_at=now,
        current_time=now,
        runtime_state=runtime_state,
        current_plan=current_plan,
        current_block_id=current_block_id,
        future_blocks=list(future_blocks[:3]),
        today_progress=today_progress,
        unfinished_tasks=list(unfinished_tasks[:256]),
        active_incident=active_incident,
        policy_constraints=policy_constraints,
        reason_codes=["CONTEXT_DEFAULT_BOUNDED"],
    )
