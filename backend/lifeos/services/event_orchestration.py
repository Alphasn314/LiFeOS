from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import LifeOSError
from ..models import EventLedgerRow
from ..schemas import EventAccepted, EventEnvelopeIn, PlanRequest, PlanTrigger
from .events import EventService
from .plans import PlanService


class EventOrchestrator:
    """Apply deterministic Core side effects to accepted external events.

    The event append and its side effect share the caller's database transaction.
    A replay discovers the already-created plan through its causation link and
    therefore never invokes the planner a second time.
    """

    replan_event_types = frozenset(trigger.value for trigger in PlanTrigger)

    def __init__(
        self,
        events: EventService,
        plans: PlanService,
        default_timezone: str = "Asia/Shanghai",
    ) -> None:
        self.events = events
        self.plans = plans
        self.default_timezone = default_timezone

    def ingest(self, db: Session, payload: EventEnvelopeIn) -> EventAccepted:
        accepted = self.events.ingest(db, payload)
        if payload.event_type not in self.replan_event_types:
            return accepted

        if accepted.duplicate:
            return accepted.model_copy(
                update={
                    "side_effect_ids": self._plan_effect_ids(db, accepted.event_id),
                    "reason_codes": ["EVENT_DUPLICATE", "REPLAN_ALREADY_APPLIED"],
                }
            )

        request_data = dict(payload.payload)
        request_data["trigger"] = payload.event_type
        request_data["now"] = payload.occurred_at
        request_data.setdefault("display_timezone", self.default_timezone)
        try:
            request = PlanRequest.model_validate(request_data)
        except ValidationError as exc:
            raise LifeOSError(
                "REPLAN_EVENT_INVALID",
                "a planning trigger event requires a valid PlanRequest payload",
                422,
                ["REPLAN_EVENT_INVALID"],
                [
                    {
                        "path": ".".join(str(part) for part in item["loc"]),
                        "message": item["msg"],
                    }
                    for item in exc.errors()
                ],
            ) from exc

        plan = self.plans.generate(db, request, causation_id=accepted.event_id)
        return accepted.model_copy(
            update={
                "side_effect_ids": [plan.plan_version_id],
                "reason_codes": ["EVENT_ACCEPTED", "REPLAN_CREATED"],
            }
        )

    @staticmethod
    def _plan_effect_ids(db: Session, event_id: UUID) -> list[UUID]:
        return list(
            db.scalars(
                select(EventLedgerRow.entity_id).where(
                    EventLedgerRow.causation_id == event_id,
                    EventLedgerRow.event_type == "PLAN.VERSION_CREATED",
                )
            ).all()
        )
