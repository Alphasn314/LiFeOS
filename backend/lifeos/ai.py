from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from pydantic import ValidationError

from .clock import Clock, SystemClock
from .schemas import AIPlanningRequest, AIPlanningResponse


class AIProviderError(RuntimeError):
    """Provider is unavailable or returned an invalid structured result."""


class AIProvider(Protocol):
    name: str

    def plan(self, request: AIPlanningRequest) -> AIPlanningResponse: ...


class MockAIProvider:
    """Deterministic contract test provider; it is not an intelligent planner."""

    name = "mock"

    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or SystemClock()

    def plan(self, request: AIPlanningRequest) -> AIPlanningResponse:
        return AIPlanningResponse(
            request_id=request.request_id,
            response_id=uuid4(),
            provider=self.name,
            created_at=self.clock.now(),
            recommendation={
                "action": "USE_DETERMINISTIC_PLAN",
                "note": "Mock provider intentionally makes no scheduling change.",
            },
            conflict_explanations=[],
            reason_codes=["AI_MOCK_RESPONSE"],
        )


class OfflineAIProvider:
    name = "offline"

    def plan(self, request: AIPlanningRequest) -> AIPlanningResponse:
        del request
        raise AIProviderError("AI provider is offline")


class ValidatingAIProvider:
    """Validates provider output again before Core may inspect it."""

    def __init__(self, inner: AIProvider) -> None:
        self.inner = inner
        self.name = inner.name

    def plan(self, request: AIPlanningRequest) -> AIPlanningResponse:
        try:
            raw = self.inner.plan(request)
            return AIPlanningResponse.model_validate(raw, strict=True)
        except (ValidationError, ValueError, TypeError) as exc:
            raise AIProviderError("AI response failed schema validation") from exc
