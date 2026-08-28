from __future__ import annotations

from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import AIProvider, AIProviderError, ValidatingAIProvider
from ..clock import Clock
from ..errors import IdempotencyConflictError
from ..models import AIJobRow
from ..schemas import AIJobRead, AIJobSubmit
from .audit import append_event


def ai_job_read(row: AIJobRow) -> AIJobRead:
    return AIJobRead(
        job_id=row.job_id,
        request_id=row.request_id,
        provider=row.provider,
        job_type=row.job_type,
        status=cast(
            Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"],
            row.status,
        ),
        schema_version=row.schema_version,
        request_payload=row.request_payload,
        response_payload=row.response_payload,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        last_error=row.last_error,
        idempotency_key=row.idempotency_key,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        fallback_used=row.status == "FAILED",
    )


class AIJobService:
    def __init__(self, clock: Clock, provider: AIProvider) -> None:
        self.clock = clock
        self.provider = ValidatingAIProvider(provider)

    def submit_and_run(self, db: Session, payload: AIJobSubmit) -> AIJobRead:
        request_payload = payload.request.model_dump(mode="json")
        existing = db.scalar(
            select(AIJobRow).where(AIJobRow.idempotency_key == payload.idempotency_key)
        )
        if existing is not None:
            if existing.request_payload != request_payload:
                raise IdempotencyConflictError(payload.idempotency_key)
            return ai_job_read(existing)

        now = self.clock.now()
        row = AIJobRow(
            request_id=payload.request.request_id,
            provider=self.provider.name,
            job_type="PLANNING_ADVICE",
            status="RUNNING",
            schema_version="1.0",
            request_payload=request_payload,
            response_payload=None,
            attempts=1,
            max_attempts=1,
            idempotency_key=payload.idempotency_key,
            created_at=now,
            available_at=now,
            started_at=now,
        )
        db.add(row)
        db.flush()
        reason_codes: list[str]
        try:
            response = self.provider.plan(payload.request)
            row.response_payload = response.model_dump(mode="json")
            row.status = "SUCCEEDED"
            reason_codes = response.reason_codes
        except AIProviderError as exc:
            row.status = "FAILED"
            row.last_error = str(exc)[:2000]
            reason_codes = ["AI_PROVIDER_OFFLINE", "DETERMINISTIC_FALLBACK"]
        row.completed_at = self.clock.now()
        db.flush()
        append_event(
            db,
            event_type=f"AI_JOB.{row.status}",
            occurred_at=row.completed_at,
            received_at=row.completed_at,
            source="core",
            entity_type="AIJob",
            entity_id=row.job_id,
            idempotency_key=f"ai-job:audit:{payload.idempotency_key}",
            payload={"provider": row.provider, "fallback_used": row.status == "FAILED"},
            reason_codes=reason_codes,
        )
        return ai_job_read(row)
