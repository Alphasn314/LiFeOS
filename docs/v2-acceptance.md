# V2 acceptance gates

V2 is documented now but is not part of the V1 implementation claim.

| ID | Gate |
|---|---|
| V2-01 | NAS profile starts private PostgreSQL, performs exactly one successful migration, then marks one Core ready; DB/migration failure prevents readiness |
| V2-02 | PostgreSQL has no client-reachable port; Web has approved TLS ingress; Windows/iOS reach only the constrained SSH subsystem over trusted LAN/VPN |
| V2-03 | Operator-authorized one-time pairing verifies the NAS host fingerprint, binds a client-generated public key to one scoped device, and installs only a forced subsystem; unauthenticated self-enrollment and shell/PTY/SFTP/forwarding/database access are rejected |
| V2-04 | The SSH NDJSON bridge rejects wrong device/version/sequence, oversized/extra-field payloads, replay conflicts, invalid time, and non-allowlisted operations |
| V2-05 | Core-issued role leases expire/revoke/handoff; iOS can never receive `PRIMARY_ENFORCEMENT`; no client self-promotes |
| V2-06 | Windows signed installation provides approved evidence, encrypted bounded outbox, active-session sync, command validation/ACK, prompt dedupe, and local offline Emergency |
| V2-07 | After operator-authorized pairing, native SwiftUI iOS syncs over its pinned device SSH identity, displays authoritative freshness, and performs online plan/Session/check-in/break/replan/override/Emergency intents without local success fabrication |
| V2-08 | iOS stale snapshot is display-only; safe intent replay preserves idempotency/expiry/version and stops for user-visible OCC conflict |
| V2-09 | APNs carries only an opaque expiring wake hint; loss/delay causes no state loss and authoritative data is fetched over SSH |
| V2-10 | Human-state reports preserve source/time/expiry/confidence/UNKNOWN and implement only intent, blocker, availability, energy, cognitive demand, and valence as core additions |
| V2-11 | Emotion, low capacity, overload, and uncertainty can only de-escalate/suppress/break/replan; missing/nonresponse never increases intervention |
| V2-12 | Research milestone/dependency, English dose, and course fixed/deadline semantics share one planner and never collapse into one percent-complete score |
| V2-13 | A miss/block/overrun produces a feasible remainder, an explicit minimum viable day, or an `INFEASIBLE` conflict/tradeoff report within five minutes when Core/PostgreSQL are ready, or within five minutes after authoritative connectivity returns; fixed facts never move, hard obligations never disappear, and completion is never fabricated |
| V2-14 | The complete intervention loop enforces freshness, commitment cap, cooldown/hysteresis, NAS-wide dedupe, prompt budget, typed outcomes, and usefulness feedback |
| V2-15 | Candidate dimensions beyond the V2-10 provisional core six are opt-in, time-bounded, removable, retention-bounded, and graduate only through the ADR-0005 observable/actionable/nonredundant/safe/low-cost criteria |
| V2-16 | Real blocklist remains off by default and cannot enable until session preauthorization, fresh lease, online Core/device, blocklist/duration authorization, local release, and complete guard/failure tests pass |
| V2-17 | Recovery Mode automatically expires within 15 minutes; Emergency Release works during every phase and terminal Sessions never revive |
| V2-18 | AI queue/worker and optional Codex adapter remain schema-bound data providers and degrade without changing deterministic planning, intervention, or Emergency |
| V2-19 | Encrypted logical PostgreSQL backup is retained outside live PGDATA and off-NAS; isolated restore reaches migration head and representative plan/session/event/command relations |
| V2-20 | NAS reboot, Core/DB/SSH/VPN loss, disk full, migration failure, stale command, clock skew, credential revocation, backup-target loss, APNs provider submission/rejection error, and missing post-push sync/ACK by a bounded deadline fail closed and generate operator-visible evidence |
| V2-21 | Whole-tree and runtime inspection prove no keystrokes, clipboard, screenshots, microphone, video, camera emotion, content surveillance, medical/personality inference, or emotion-based coercion |

