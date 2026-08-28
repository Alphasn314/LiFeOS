# ADR-0004: transactional event orchestration and replay

- Status: Accepted
- Date: 2026-08-28

## Context

LifeOS needs external facts such as a late arrival to be both auditable and able
to trigger deterministic replanning. Appending the event and creating a plan in
separate transactions would permit a crash between them, while invoking the
planner again on a retry would create duplicate PlanVersions.

## Decision

`EventOrchestrator` recognizes only event types in the frozen `PlanTrigger`
allowlist. For a new event it appends EventLedger/Outbox rows, validates the event
payload as a `PlanRequest`, and persists the resulting PlanVersion within the
request transaction. The Plan creation audit event stores the trigger event UUID
as `causation_id`.

For a completed sequential replay, the unique external idempotency key returns the
existing event. Core queries `PLAN.VERSION_CREATED` by `causation_id` and returns
the original plan UUID without executing the planner again. Semantic comparison
excludes the caller's replacement `event_id` and Core-assigned `received_at`; the
remaining envelope semantics are compared. A key reused with different semantic
content is a conflict. Database uniqueness prevents a concurrent second
side effect, but the competing request may receive 409 instead of the original
outcome.

Direct CRUD endpoints do not silently synthesize these envelopes in V1. This keeps
cause, payload, and calendar horizon explicit until product semantics for task
progress and recurring schedule edits are decided.

## Consequences

- For a request that completes successfully, event append and deterministic replan
  commit atomically on the external trigger path.
- Completed sequential replays expose stable outcome IDs and do not duplicate plan
  or outbox rows; concurrent callers must tolerate a 409 serialization outcome.
- A trigger envelope must carry enough `PlanRequest` context, including
  `plan_date`; invalid payloads fail the whole transaction.
- Clients currently own some workflow orchestration after direct mutations. A
  future implicit-trigger feature must preserve the same event envelope,
  idempotency, causation, throttle, and transaction guarantees.
