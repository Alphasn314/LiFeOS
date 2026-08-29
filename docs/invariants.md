# System invariants

1. PostgreSQL state committed by Core is authoritative. Client cache is never
   promoted to truth.
2. Every important entity has a UUID. Every mutable aggregate has an integer
   `version`, changed with optimistic concurrency.
3. External events, observations, and command acknowledgements have a unique
   idempotency key. Sequential replays return the existing outcome and cause no
   second side effect. Database uniques prevent duplicate concurrent side effects,
   but a competing same-key request may receive 409 rather than the original outcome.
4. Every accepted replan inserts a new `PlanVersion`; throttled/rejected requests
   do not. Earlier rows and blocks are immutable.
5. An infeasible request produces a structured conflict report and never a plan
   marked feasible.
6. Stored timestamps are timezone-aware UTC. Calendar input/output declares an
   IANA timezone; the default display timezone is `Asia/Shanghai`.
7. Observation, derived features, state estimate, policy decision, and command are
   separate records/concepts. A client observation is never accepted as policy.
8. Every state estimate has `confidence`, `reason_codes`, `valid_until`, and a
   monotonically increasing per-device `state_version`. Session-scope changes
   clear hysteresis input but do not reset the device counter.
9. Missing or conflicting evidence and confidence below 0.65 yield `UNKNOWN`, not
   `OFF_TASK`. V1 has no camera; any future camera failure may only contribute
   `UNKNOWN`.
10. Every command has `command_id`, `expires_at`, `required_state_version`,
    `idempotency_key`, and `reason_codes`.
11. V1 emits no real hard command. Ordinary commands reject expired/stale/wrong-
    device input and Agent execution is idempotent. Full hard authorization and
    lease validation are mandatory V2 gates and are not claimed complete in V1.
12. Commitment mode is fixed at session start. Later escalation cannot grant new
    authority.
13. `dry_run=true` is the default. In V1, block behavior records `WOULD_BLOCK`; no
    process, registry, firewall, startup, or administrator setting is changed.
14. A Core-accepted Emergency Release cancels pending enforcement in its
    transaction and queues release commands without ordinary-policy/OCC gating.
    Agent receipt is asynchronous; local user-triggered offline release UI is V2.
15. Typed restriction payloads are bounded to 30 minutes, and V1 creates no real
    restriction at all.
16. Core/network loss prevents the Agent from obtaining a new command. V1 also
    rejects all real hard action locally; complete lease expiry behavior is V2.
17. The automatic Windows collector is limited to foreground process/title, idle,
    and lock evidence plus session/heartbeat metadata. Manual check-in exists in
    the transport model but has no Agent UI. It never captures input content,
    clipboard, screenshots, microphone, or video.
18. AI output must validate against a contract. Invalid/offline AI has no effect on
    deterministic planning, reminders, state, or emergency release.
19. Replan triggers are limited to the allowlist in `docs/planning.md`.
20. EventLedger is append-only by application-service/API convention. V1 does not
    install a database immutability trigger or restricted writer role.

## Target V2 invariants

21. The NAS-hosted Core/PostgreSQL remains the only authority. Windows and iOS
    caches, SSH ordering, APNs delivery, and experiment output never become truth.
22. Device SSH keys enter an allowlisted forced subsystem only. No application key
    provides shell, PTY, SFTP, forwarding, arbitrary command, or database access.
23. Client identity comes from the enrolled SSH principal, never a claimed
    `device_id`; only Core issues/revokes domain role leases and iOS can never hold
    `PRIMARY_ENFORCEMENT`.
24. User report is authoritative for intent, availability, energy, perceived
    demand, and valence. Behavioral evidence estimates engagement only.
25. Human-state/emotion/experiment input may suppress, delay, soften, break, or
    replan; it never increases intervention intensity. Nonresponse is `UNKNOWN`.
26. Replanning preserves committed facts and history, then degrades scope to an
    explicit `PARTIAL`/minimum viable day. It never degrades truth, drops a hard
    obligation silently, or fabricates completion.
