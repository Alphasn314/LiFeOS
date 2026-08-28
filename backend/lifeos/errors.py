from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(slots=True)
class LifeOSError(Exception):
    error_code: str
    detail: str
    status_code: int = 400
    reason_codes: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    correlation_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.detail)
        if not self.reason_codes:
            self.reason_codes = [self.error_code]


class NotFoundError(LifeOSError):
    def __init__(self, entity: str, entity_id: object) -> None:
        super().__init__(
            "NOT_FOUND",
            f"{entity} {entity_id} was not found",
            404,
            [f"{entity.upper()}_NOT_FOUND"],
        )


class VersionConflictError(LifeOSError):
    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(
            "VERSION_CONFLICT",
            f"expected version {expected}, current version is {actual}",
            409,
            ["VERSION_CONFLICT"],
        )


class IdempotencyConflictError(LifeOSError):
    def __init__(self, key: str) -> None:
        super().__init__(
            "IDEMPOTENCY_CONFLICT",
            f"idempotency key {key!r} was already used for different input",
            409,
            ["IDEMPOTENCY_CONFLICT"],
        )
