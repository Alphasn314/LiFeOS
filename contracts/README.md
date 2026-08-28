# Frozen V1 transport contracts

These Draft 2020-12 schemas are the language-neutral client boundary. The frozen
set is Event Envelope, Observation, RuntimeState, Command, PlanVersion, Task,
Device Heartbeat, Role Lease, AI Planning Request/Response, and Error Response.
`common.schema.json` only holds referenced scalar definitions.

V1 code may add internal database fields but may not change required transport
semantics without an ADR, schema-version decision, migration review where needed,
and updated contract fixtures/tests.

## Planning-trigger event payload

When an Event Envelope's `event_type` is one of the frozen PlanTrigger values, its
`payload` is interpreted as a `PlanRequest`: at minimum it contains `plan_date`,
and it may contain timezone, availability, device/location, state version, and
planner parameters. Core overwrites any payload `trigger` with the envelope type
and uses `occurred_at` as the planning `now`. The event and resulting immutable
PlanVersion are committed atomically. A replay with the same idempotency key must
return the same side-effect PlanVersion ID and create neither a second plan nor a
second outbox row.

Non-trigger event types are append-only audit facts and have no implicit planning
side effect.
