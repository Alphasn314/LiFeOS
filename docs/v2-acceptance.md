# V2 acceptance gates

V2 is documented now but is not part of the V1 implementation claim.

| ID | Gate |
|---|---|
| V2-01 | NAS profile starts private PostgreSQL, performs exactly one serialized migration, then marks one Core/learning scheduler ready; DB/migration failure prevents readiness |
| V2-02 | VPN is the normal remote boundary; Web uses approved TLS and Windows/iOS reach only a pinned-key forced SSH subsystem; PostgreSQL has no client port |
| V2-03 | Operator pairing binds one client-generated public key to one scoped device and rejects self-enrollment, shell, PTY, SFTP, forwarding, arbitrary command and database access |
| V2-04 | Self-evolution is an allowlisted static Core module with immutable manifests/revisions, deterministic validation, audit and rollback; runtime source mutation/download/install is impossible |
| V2-05 | Task feedback stores planned/active/wall time, partial/completed progress, meaningful attempts, experienced pressure and current-state provenance with idempotency |
| V2-06 | Duration prediction supplies hierarchical cold start, online update, P50/P80/confidence/evidence count, censored partial handling, pre-update error and rollback without silently replacing user estimates |
| V2-07 | Experienced pressure 0-4 learns from user feedback and bounded AI proposals, remains distinct from deadline pressure, and affects ordering/recovery spacing only |
| V2-08 | Next-day advice preserves the submitted plan, explains minimal changes and waits for user acceptance; an explicit authenticated `CREATE_DAILY_PLAN`/`ACCEPT_SCHEDULE_ADVICE` may create an initial plan only; any domain may receive zero time |
| V2-09 | Only severe deviation that remains infeasible after permitted compression/deferment creates a deduplicated recommendation; only authenticated `REQUEST_REPLAN` may replace the named current revision, and tests show EventOrchestrator, the Session break route and generic/non-user generation cannot create a replacement PlanVersion |
| V2-10 | Core human state is exactly focus 0-4, fatigue 0-4 and current emotion -2..+2 plus `UNKNOWN`; sleep/body/environment enter only through explicit expiring impact reports |
| V2-11 | Focus recognizes sustained progress or meaningful repeated attempts and fuses bounded task adapters, Windows evidence and coarse iOS evidence with coverage/conflict/freshness guards |
| V2-12 | Fatigue and emotion are user-authoritative, current-only and never inferred from camera/text/app use or used to increase force |
| V2-13 | Xcode free-personal-team iOS installs on the user's iPhone, pins SongNAS SSH, schedules accepted-plan local notifications and documents provisioning expiry/no APNs guarantee |
| V2-14 | iOS camera is explicit foreground-only and uploads no frame/video/embedding/identity/emotion; denial/suspension/occlusion/removal/failure becomes `UNKNOWN` |
| V2-15 | Phone evidence reaches NAS, Core decides, and Windows independently validates/reminds; Windows remains functional when the phone is missing |
| V2-16 | One signed LifeOS Windows app merges tray, sensor, encrypted bounded queue, transport, choice UI, advisory/dry-run local fallback, Recovery tool, installer/autostart/update/uninstaller and exact owned-policy reconciliation |
| V2-17 | NAS real restrictions remain unadvertised until Session preauthorization, command dry-run off, state/TTL/idempotency, exact blocklist/duration, online Core/device, fresh lease, rollback/audit and full guard tests pass |
| V2-18 | `BREAK/PAUSED/MEAL/TRAVEL/RECOVERY/EMERGENCY`, terminal/no Session, stale/expired authority, override and local Emergency synchronously release restrictions and watched apps cannot re-lock |
| V2-19 | Without fresh NAS authority the visible optional standalone fallback is limited to timer/focus UI/reminders/`WOULD_BLOCK`; it cannot change hosts, browser policy, processes or applications |
| V2-20 | Friction and Recovery are selected from documented F1-F4/R1-R3 options before real enablement; Emergency, real block, break denial and replan are never randomized |
| V2-21 | NAS AI proposes bounded features/estimates/pressure/check-in/reminder choices only; deterministic ceilings and guards own execution |
| V2-22 | Safe experiments have manifests, stop/rollback/retention rules and cannot alter code, credentials, hard guards, Emergency, camera retention or user-only replan |
| V2-23 | Detailed context reads the latest 72 hours by default; permanent summaries/profiles/revisions are encrypted/date-partitioned/exportable, camera frames never persist, frozen-release test data is deleted, and no gate assumes a raw-evidence retention period before user selection |
| V2-24 | Maintenance runs only 03:00-07:00 local and never interrupts an active Session without an explicit transition |
| V2-25 | Same-NAS snapshots/local backup are tested and explicitly labelled one failure domain; disaster recovery remains incomplete until off-NAS backup exists |
| V2-26 | A reviewed API/source allowlist plus instrumented storage, network, camera-lifecycle and command-adapter tests cover every enumerated success/failure path and reject keystroke, clipboard, screenshot, microphone, frame/video/embedding, camera emotion/identity, content-surveillance, medical/personality, generic-shell and AI-enforcement payloads/actions |
| V2-27 | Plan creation/revision requires a fresh one-time interactive `HUMAN_INTENT` envelope with expected plan revision; tests accept OS-confirmed user action and deny stale/replayed/wrong-revision envelopes plus AI, service, sensor and ordinary device principals |

