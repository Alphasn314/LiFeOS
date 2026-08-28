# Incidents and degraded operation

| Incident | Detection | Safe behavior | Recovery evidence |
|---|---|---|---|
| PostgreSQL unavailable | readiness query or transaction failure | `/ready` returns structured 503; other DB failures may surface through framework/driver handling; agents queue outbound evidence | DB health and migration head |
| Core/network unavailable | heartbeat/request timeout | Agent store-and-forward for observations/acks; Web shows offline and has no durable cached plan; no new command can be obtained | successful health + command sync |
| AI/provider unavailable | provider exception or invalid schema | mark synchronous AIJob failed; deterministic planner continues | a later explicitly submitted job succeeds |
| Device heartbeat missing >=45 s | comparison when devices are read/listed or explicitly marked stale | report/mark device offline lazily; command polling does not refresh this status and V1 does not proactively revoke leases | fresh idempotent heartbeat |
| Device clock ahead | heartbeat more than 5 minutes ahead of Core | reject with `HEARTBEAT_FROM_FUTURE`; do not move liveness head | corrected device clock/new heartbeat |
| Lease expired | hard-row poll sees `expires_at <= now` | reject and audit that row; lease issuance/recovery is V2 scaffold | future lease lifecycle issues a replacement |
| Stale/expired command | Core poll and Agent local validation | Core rejects/audits before delivery; Agent rejects and sends an ACK if it receives an invalid command | new matching command if still needed |
| Sensor conflict/failure | feature reducer | UNKNOWN, no escalation | sufficient consistent fresh window |
| Observation idempotency conflict | same key with different semantic input | HTTP 409; no new state | caller retries the original envelope or uses a new key for a new fact |
| Core restart | process start | read persisted heads/state; commands are revalidated during poll, not swept at startup | readiness and recovery test |
| Sequential event replay | unique idempotency key | return original outcome, no duplicate plan/outbox | audit lookup; DB unique prevents concurrent duplicate side effects, but a racing request may receive 409 |
| Planner infeasible | constraint verifier | persist INFEASIBLE PlanVersion + conflicts | changed inputs/new plan version |

External envelopes support correlation and causation IDs; many internal audit
events leave them null unless a causal event is known. Incident responses do not
delete ledger evidence. Web exposes Emergency Release; the Agent has an internal
local release method but no user-facing tray/hotkey in V1. V1 intentionally has no
automatic startup or machine-level recovery modification.
