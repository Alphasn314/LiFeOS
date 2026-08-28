from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import IdempotencyConflictError
from ..models import EventLedgerRow, OutboxRow


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def append_event(
    db: Session,
    *,
    event_type: str,
    occurred_at: datetime,
    received_at: datetime,
    source: str,
    entity_type: str,
    entity_id: UUID,
    idempotency_key: str,
    payload: dict[str, Any],
    reason_codes: list[str],
    event_id: UUID | None = None,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
    schema_version: str = "1.0",
    compare_occurred_at: bool = True,
) -> tuple[EventLedgerRow, bool]:
    """Append audit + outbox atomically, returning the original row on replay."""

    normalized_payload = _jsonable(payload)
    existing = db.scalar(
        select(EventLedgerRow).where(EventLedgerRow.idempotency_key == idempotency_key)
    )
    if existing is not None:
        same_input = (
            existing.schema_version == schema_version
            and existing.event_type == event_type
            and existing.source == source
            and existing.entity_type == entity_type
            and existing.entity_id == entity_id
            and existing.correlation_id == correlation_id
            and existing.causation_id == causation_id
            and (not compare_occurred_at or existing.occurred_at == occurred_at)
            and existing.payload == normalized_payload
            and existing.reason_codes == reason_codes
        )
        if not same_input:
            raise IdempotencyConflictError(idempotency_key)
        return existing, False

    row = EventLedgerRow(
        event_id=event_id or uuid4(),
        schema_version=schema_version,
        event_type=event_type,
        occurred_at=occurred_at,
        received_at=received_at,
        source=source,
        entity_type=entity_type,
        entity_id=entity_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        idempotency_key=idempotency_key,
        payload=normalized_payload,
        reason_codes=reason_codes,
    )
    db.add(row)
    db.flush()
    db.add(
        OutboxRow(
            event_id=row.event_id,
            topic=event_type,
            payload={
                "event_id": str(row.event_id),
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": str(entity_id),
            },
            available_at=received_at,
        )
    )
    db.flush()
    return row, True
