# ADR-0003: Separate contracts, audit ledger, and derived state

- Status: Accepted for V1 contract freeze
- Date: 2026-08-28

## Decision

Transport JSON/Pydantic models, SQLAlchemy ORM rows, and pure planning/runtime
domain values remain distinct. EventLedger is an append-only audit ledger, not an
event-sourced database. Events create an Outbox row in the same transaction. V1
does not include a generic publisher or external consumer, so this is durable
outbox storage rather than a completed at-least-once delivery subsystem.

Observation, FeatureSnapshot, RuntimeState, PolicyDecision, Command, and CommandAck
are separately inspectable. Immutable plan/state history uses an explicit current
head rather than rewriting historical rows.

## Consequences

There is some mapping code, but persistence changes cannot accidentally redefine
the external safety contract, and every enforcement conclusion is auditable back
to raw evidence and derived features. Breaking contract changes require a schema
version/ADR; persistence changes require Alembic.

A later publisher may provide at-least-once delivery only after consumer
idempotency, locking, retry/backoff, poison-event handling, and operational tests
are implemented. No distributed exactly-once behavior is claimed.
