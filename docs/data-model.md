# Data model

All timestamps below are UTC. JSON columns store arrays or provider-neutral
payloads; fields used for identity, ordering, authorization, and expiry are normal
columns and indexed.

| Entity | Purpose and principal fields |
|---|---|
| Task | UUID, title/description, status, priority 1-5, mandatory, deadline, estimated/remaining/minimum-chunk minutes, activity profile, location/device needs, allowed/blocked apps, idle tolerance, version |
| FixedEvent | UUID, title, UTC interval, location, activity profile, hardness, travel before/after, version; V1 API exposes one-off events, while the database `recurrence_rule` column is unused scaffold |
| PlanVersion | UUID, local date/timezone, monotonic revision, prior plan UUID, trigger, status, conflicts, parameters, reason codes, creation state version |
| ScheduleBlock | UUID, plan UUID, kind, interval, task/fixed-event link, source block, hardness, activity profile, app rules, reason codes |
| ExecutionSession | UUID, plan/block/task, commitment mode, state, scheduled/actual times, dry-run, intervention level, emergency/override details, version |
| Observation | UUID, device/session, kind, observed/received times, normalized payload, idempotency key, reason codes |
| FeatureSnapshot | UUID, device/session, 60/300-second window bounds, ratios/durations/freshness/conflict fields, algorithm version, reason codes; immutable |
| RuntimeState | UUID, device/session, context/presence/engagement/session/device-role axes, confidence, feature snapshot, valid-until, state version, reason codes |
| Device | UUID, name/type, capabilities, status, last heartbeat, version |
| DeviceRoleLease | UUID, device, role, issued/expiry/revoked times, state version, version |
| PolicyDecision | UUID, session/state version, commitment mode, level, action, dry-run, expiry, reason codes |
| Command | UUID, target, decision, type/risk/status, timing window, required state version, idempotency key, payload, dry-run, reason codes |
| CommandAck | UUID, command/device, status, acknowledged time, observed state version, idempotency key, details, reason codes |
| EventLedger | UUID, event envelope fields, entity/correlation/causation, schema version, payload, reason codes; immutable |
| Outbox | UUID, event UUID, topic, payload, availability/publication/attempt metadata |
| AIJob | UUID, provider/type/status, request/response, schema version, attempts/error, timing, idempotency key |
| DailySummary | UUID, local date/timezone, metrics, narrative, source plan revision, version |

## Relationships and lifecycle

A Task can appear in multiple blocks across immutable plan versions, while only
the current non-INFEASIBLE plan head is active (FEASIBLE or PARTIAL). One block can start many historical
sessions. V1 enforces one non-terminal session per device, not a cross-device
unique constraint per block; a second device could therefore start the same block
unless a later product rule closes that gap. Observations remain raw evidence.
RuntimeState rows are estimates derived from evidence. Each PolicyDecision
references the exact state version it evaluated; each Command references that
decision and version.

## Concurrency

Updates use `WHERE id=:id AND version=:expected_version`; a zero-row update returns
HTTP 409 with `VERSION_CONFLICT`. Append-only entities do not update. Unique
constraints cover event, observation, acknowledgement, heartbeat, and command
idempotency keys. Plan revision is unique per local date and timezone.

The Outbox is a durable transactional record in V1. A continuously running generic
publisher/dispatcher is not included; current in-process workflows and client
polling perform the relevant delivery. Treat external-bus publication and retry
operations as V2 work rather than assuming every pending row is automatically
drained.
