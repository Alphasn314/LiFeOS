from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import Clock
from ..models import EventLedgerRow
from ..schemas import EventAccepted, EventEnvelopeIn, EventEnvelopeRead
from .audit import append_event


def event_read(row: EventLedgerRow) -> EventEnvelopeRead:
    return EventEnvelopeRead(
        schema_version="1.0",
        event_id=row.event_id,
        event_type=row.event_type,
        occurred_at=row.occurred_at,
        received_at=row.received_at,
        source=row.source,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        idempotency_key=row.idempotency_key,
        payload=row.payload,
        reason_codes=row.reason_codes,
    )


class EventService:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def ingest(self, db: Session, payload: EventEnvelopeIn) -> EventAccepted:
        received_at = payload.received_at or self.clock.now()
        row, created = append_event(
            db,
            event_id=payload.event_id,
            schema_version=payload.schema_version,
            event_type=payload.event_type,
            occurred_at=payload.occurred_at,
            received_at=received_at,
            source=payload.source,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            correlation_id=payload.correlation_id,
            causation_id=payload.causation_id,
            idempotency_key=payload.idempotency_key,
            payload=payload.payload,
            reason_codes=payload.reason_codes,
        )
        return EventAccepted(
            event_id=row.event_id,
            duplicate=not created,
            side_effect_ids=[],
            reason_codes=["EVENT_ACCEPTED" if created else "EVENT_DUPLICATE"],
        )

    def get(self, db: Session, event_id: UUID) -> EventEnvelopeRead:
        row = db.get(EventLedgerRow, event_id)
        if row is None:
            from ..errors import NotFoundError

            raise NotFoundError("Event", event_id)
        return event_read(row)

    def list(self, db: Session, *, limit: int = 200) -> list[EventEnvelopeRead]:
        rows = db.scalars(
            select(EventLedgerRow)
            .order_by(EventLedgerRow.received_at.desc(), EventLedgerRow.event_id)
            .limit(limit)
        ).all()
        return [event_read(row) for row in rows]
