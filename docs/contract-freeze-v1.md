# V1 contract freeze

- Frozen: 2026-08-28
- Schema version: 1.0
- Scope: all JSON files in `contracts/` except the shared scalar library

The contracts were frozen before parallel implementation. The following ambiguity
decisions are binding for V1:

1. Command TTL, required state version, idempotency, typed payloads, audit rejection,
   and Emergency Release are V1 safety gates. V2 extends them to real enforcement
   and multi-device handoff.
2. DeviceRoleLease has a V1 contract/table so a hard command can never omit the
   concept. Lease election and real hard-action use remain V2. V1 emits no real
   hard command.
3. Offline store-and-forward exists in the Windows Agent for V1 observations and
   acknowledgements. V2 generalizes it to multi-endpoint handoff.
4. DailySummary and Context Builder have V1 entity/provider scaffolding only; their
   scheduled production workflow is V2.
5. FixedEvent is the editable schedule source. ScheduleBlock is an immutable result
   inside one PlanVersion.
6. FeatureSnapshot is an internal persisted boundary between raw Observation and
   RuntimeState even though no separate public schema was requested.
7. One RuntimeState belongs to one device/session scope, so its singular
   `device_role` is well-defined. Cross-device active roles are derived from leases.
8. V1 is one local profile. Multi-user authentication and profile tenancy are not
   silently implied.
9. Any external event whose `event_type` exactly matches a frozen `PlanTrigger`
   must carry a payload valid as `PlanRequest` (the orchestrator supplies
   `trigger` and uses `occurred_at` as `now`). Event append and plan creation are
   one transaction; replay returns the original plan ID through `side_effect_ids`.
10. `PUT /api/v1/devices/{device_id}` is the idempotent Agent enrollment boundary.
    `GET /api/v1/devices/{device_id}/active-session` returns the authoritative
    non-terminal session or HTTP 204. These endpoints extend the HTTP surface but
    do not change a frozen JSON schema.
11. Direct CRUD calls are not contractually equivalent to external trigger
    envelopes. Automatic trigger synthesis is workflow behavior and requires a
    separate product decision before it is made implicit.

Any change requires an ADR and relevant contract/migration tests before merge.
