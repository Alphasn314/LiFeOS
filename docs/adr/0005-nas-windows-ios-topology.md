# ADR-0005: NAS Core, Windows client, native iOS companion, and adaptive human state

- Status: Proposed for V2; amended by ADR-0006 for learning, state, intervention,
  Windows integration, iOS camera/free signing, retention, and replan authority
- Date: 2026-08-29

> Amendment: ADR-0006 supersedes this document's human-state dimensions, fixed
> domain minimums, replan authority, Windows enforcement integration, iOS
> camera/free-signing notification path, retention, and self-evolution details.

## Context

LifeOS is not three peer applications. It is one authoritative system hosted on the
NAS and two device-specific clients:

1. the LifeOS Core and PostgreSQL on the NAS;
2. Windows software for desktop evidence, interaction, and command adaptation;
3. a native iOS companion for mobile interaction and notification.

The user's current life is dominated by research, English accumulation, and school
courses. Research is uncertain and dependency/milestone driven. English is a dose-
and repetition-driven practice whose immediate comprehension is probabilistic.
Courses combine fixed attendance with hard assignment and exam deadlines. A missed
block must therefore trigger a usable remaining plan rather than invalidate the day.
Replanning is a primary loop, not an exceptional recovery feature.

V1 already has a deterministic planner, immutable plan revisions, Session,
Observation, RuntimeState, PolicyDecision, typed Command, EventLedger, outbox, a
Windows Agent, and a responsive Web PWA. Native iOS, device identity, role-election,
mobile notification delivery, the NAS production profile, and the human-state model
below are not implemented. This ADR records the target without claiming those
features or modifying `backend/lifeos/schemas.py` or `contracts/*.schema.json`.

## Decision principles

- PostgreSQL commits made by Core are the only business truth.
- SSH is a transport and identity boundary, never a general client shell or database
  tunnel.
- Clients submit evidence and user intent. They do not calculate authoritative plans,
  RuntimeState, PolicyDecision, leases, or commands.
- Human state is multi-axis. There is no moralized productivity score.
- User self-report is authoritative for felt emotion. Desktop evidence can estimate
  engagement but cannot infer emotion.
- Missing, stale, or conflicting evidence becomes `UNKNOWN` and cannot increase
  intervention.
- Emotion, illness, pain, and overload may reduce intervention or choose break/replan;
  they never independently authorize more coercion.
- Replanning degrades gracefully to a minimum viable day.
- The core model stays small. Candidate dimensions enter through consented N-of-1
  experiments and graduate only when they change decisions reliably.
- V1 remains `dry_run=true` and `real_enforcement_enabled=false`.

## Target topology

```text
                       trusted LAN / authenticated VPN

 Windows software ---- SSH forced subsystem ----┐
                                                 v
 native iOS app ------ SSH forced subsystem --> NAS lifeos-bridge
       ^                                         |
       | optional APNs wake hint                 | authenticated typed request
       | (no private state)                      v
       +------------------------------------ FastAPI Core
                                                 |
                     Web/PWA -- HTTPS ---------->|
                                                 v
                                            PostgreSQL
                                      plans / sessions / state
                                      policy / commands / audit
```

Only the NAS exposes a controlled ingress. PostgreSQL stays on a private container
network and is never a client endpoint. `lifeos-bridge` maps an authenticated SSH
principal to one enrolled device and invokes Core through a loopback/internal typed
API. It does not execute a requested shell command, interpret payload text as code,
or grant filesystem access.

Device bootstrap is an operator-authorized out-of-band pairing ceremony, not an
unauthenticated bridge operation. The user authenticates to the NAS Web/QTS
administration surface, verifies the NAS SSH host-key fingerprint through that
independent channel, and approves a one-time pairing request containing a
client-generated public key and requested capabilities. Core creates/binds the
device identity and least-privilege scope; the operator installs an
`authorized_keys` forced-command entry or signs a short-lived SSH device
certificate. The client pins the verified host key before its first SSH sync.
Pairing codes are single-use, short-lived, rate-limited, and never grant a shell.
Self-enrollment before this ceremony is forbidden.

The initial NAS deployment uses one Core replica. The current API entrypoint runs
Alembic on startup and there is no scheduler/outbox leader election. Horizontal
scaling is forbidden until migration becomes a serialized one-shot deployment step
and singleton job ownership exists. RAID, snapshots, and automatic container restart
are not high availability or backup.

## Responsibility matrix

| Concern | NAS Core | Windows software | iOS companion |
|---|---|---|---|
| Business truth | Owns every committed aggregate | Never | Never |
| Planning/replanning | Deterministic creation, verification, revision history | Requests/reports triggers | Requests/reports triggers |
| Session state | OCC/idempotent transition authority | Displays assignment; submits intent | Displays snapshot; submits intent |
| Desktop evidence | Validates, stores, reduces | Approved collector and outbound queue | Never |
| Felt state/emotion | Stores explicit reports and provenance | Optional user check-in UI | Primary quick check-in UI |
| Policy/commands | Decides, expires, targets, audits | Polls, revalidates, adapts, ACKs | Notification/interaction only |
| Enforcement role | Issues/revokes future leases | Never self-assigns; V1 has no hard adapter | Never `PRIMARY_ENFORCEMENT` |
| Emergency | Commits release and queues `RELEASE_ALL` | Local fail-open release plus Core request | Core request; offline shows not delivered |
| Offline data | Authoritative DB and outbox | Evidence/ACK outbox only | Stale read snapshot + safe intent outbox |
| AI | Optional schema-validated, fail-closed provider | None | None |
| Recovery | Migration, readiness, backup/restore | Reconcile from Core | Reconcile from Core |

### NAS-hosted LifeOS

The NAS owns Core, PostgreSQL, migrations, durable volumes, audit/outbox, backup,
restore, health, time authority, and controlled ingress. It must provide TLS for Web
and host-key-pinned SSH for device clients. Access is limited to trusted LAN or an
authenticated VPN; no direct Internet port-forward is part of the design.

A production profile must reject empty/default credentials, bind every device key to
one device identity and permission scope, keep PostgreSQL private, restrict CORS to
the real Web origin, redact secrets from logs, supervise containers, bound logs and
resources, and alert on readiness/backup/disk failure. Per ADR-0006, V2 implements
encrypted same-NAS snapshots/local copies and must label disaster recovery incomplete;
it must not claim an off-NAS backup exists.

### Windows software

Windows keeps the existing narrow evidence surface: foreground process basename,
optionally redacted/truncated title, idle duration, lock state, sensor health,
Session metadata, and heartbeat. It never records keystrokes, clipboard, screenshots,
microphone, or video. Failure produces unknown evidence rather than activity.

The Windows app has six internal modules: constrained SSH transport, enrollment and
Session sync, collector, encrypted/bounded outbound outbox, command validator/ledger,
and tray interaction/Emergency UI. It may hold `SENSOR`, `NOTIFICATION_ONLY`, or a
Core-issued interaction lease. It cannot issue or extend a lease. V1 execution stays
notification, information prompt, `WOULD_BLOCK`, and simulated `RELEASE_ALL`.

The queue stores original idempotency keys and captured Session context, distinguishes
retryable transport/5xx from terminal 4xx, has size/age limits and dead-letter review,
and never stores an offline command inbox. No new command can be obtained when NAS is
unreachable. Installation and update packages must be signed; the device private key
is protected by Windows CNG/DPAPI and is independently revocable.

### Native iOS companion

ADR-0006 selects an Xcode-direct-installed SwiftUI app using the user's free
Personal Team. It reads plans/Sessions, submits typed user intents, stores only a
stale read snapshot and safe intent outbox, and never invents success before Core.
It is `PRIMARY_INTERACTION`/`NOTIFICATION_ONLY` at most and never desktop sensor,
planner, lease issuer, command authority or `PRIMARY_ENFORCEMENT`.

The app uses pinned-key constrained SSH over the user's VPN and schedules accepted
plan reminders locally with `UserNotifications`; APNs is not a required or
guaranteed channel. Foreground camera Sessions process AVFoundation/Vision buffers
on-device and discard them immediately. Only bounded coarse focus evidence may be
uploaded. No frame/video/identity/emotion leaves the device.

## Work semantics: complete without domain-specific sprawl

One planner uses commitment, progress, uncertainty, interruptibility, cognitive
demand, dependencies, learned duration P50/P80 and experienced pressure. Research
is milestone/dependency driven; English is divisible accumulation with optional
noisy comprehension feedback; classes/exam sittings are fixed and assignments/exam
preparation are deadlines.

No domain has a fixed daily minimum. Any domain may receive zero time by user
choice. Self-evolution preserves the user's estimate and returns versioned schedule
advice; it never silently replaces the plan. Persistence/API changes require ADR,
migration and contract tests. ADR-0006 is normative for learning details.

## Human state and emotion

ADR-0006 replaces the provisional six dimensions with exactly three current,
learning-only dimensions: focus 0--4, fatigue 0--4 and emotion -2..+2, each plus
`UNKNOWN`, provenance, confidence and validity. Focus recognizes sustained progress
or meaningful repeated attempts. Fatigue/emotion are user-authoritative and are
never inferred from camera/text/app use. Sleep/body/environment enter only through
an explicit expiring report that they affect learning now.

Task blockers, feasibility and device availability remain system facts rather than
human-state dimensions. No motivation/discipline/personality/medical/composite score
is created.

## Replanning as an explained user-only action

Core may project progress but never automatically replan. It first simulates
permitted compression and whole flexible-block deferment/removal. If the remainder
is feasible, it does not recommend replan. Only severe unrecoverable deviation
creates a deduplicated `REPLAN_RECOMMENDED` explanation on Windows/iOS/Web. An
authenticated explicit human intent may create the initial daily plan; only
`REQUEST_REPLAN` with the separate ADR-0006 `HUMAN_INTENT` proof may replace it.
AI, services, sensors and ordinary device principals cannot submit either action.

## Complete intervention loop

LifeOS Windows owns light reminder, native choice and future friction surfaces.
NAS AI may propose timing/wording only within deterministic ceilings. Existing Self
Discipline Controller facilities supply bounded hosts/HKLM/process backends after
the full guard matrix passes.

Authority is local Emergency > NAS rest/release/terminal > fully guarded NAS
restriction > optional advisory/dry-run local fallback. BREAK/PAUSED/MEAL/TRAVEL/RECOVERY/
EMERGENCY, terminal/no Session, stale authority, override and local Emergency
synchronously release all owned restrictions. A watched work application cannot
re-lock during rest.

ADR-0006 selects F3 friction and R1 Recovery for the first integrated release.
Emergency, real block, break denial and user-only replan are never randomized.

## SSH constrained protocol

### Account and channel

Each enrolled device has an independent Ed25519 key. Windows protects it with
CNG/DPAPI; iOS uses Keychain/Secure Enclave where supported. The client pins the NAS
host key. Rotation and revocation are per device.

`authorized_keys` (or an SSH certificate principal) binds the key to a forced command:

```text
restrict,command="/usr/local/bin/lifeos-bridge --device <uuid>" ssh-ed25519 ...
```

The account has no PTY, shell, SFTP, agent/X11 forwarding, port forwarding, or
filesystem permission. Password login is not an application protocol. The bridge
accepts typed messages on stdin and writes typed responses on stdout.

### NDJSON envelope

UTF-8 NDJSON is used because there are no allowed binary sensors and operational
clarity is worth more than marginal CBOR savings. One line is one message, maximum
64 KiB, with bounded nesting/lists. Newline inside strings is JSON-escaped. Every
wire timestamp is an RFC 3339 UTC instant with a `Z` suffix.

```json
{"v":2,"id":"uuid","type":"request","op":"sync.push","device_id":"uuid","seq":42,"sent_at":"2026-08-29T12:00:00Z","idempotency_key":"stable-key","if_version":7,"body":{}}
```

A response echoes `id` and supplies Core time and authoritative versions:

```json
{"v":2,"id":"uuid","type":"response","ok":true,"server_at":"2026-08-29T12:00:01Z","state_version":81,"sync_cursor":"opaque","body":{}}
```

Errors are typed and retry-explicit:

```json
{"v":2,"id":"uuid","type":"response","ok":false,"error":{"code":"VERSION_CONFLICT","retryable":false}}
```

Required envelope fields are version, message ID, type, operation, authenticated
`device_id`, monotonic connection sequence, UTC client time, and body. Mutations also
require idempotency; aggregate changes require expected version. The bridge rejects
unknown operation/version, mismatched device ID, duplicate sequence with different
content, oversize line, excessive batch, invalid timestamp/skew, and extra fields on
safety messages.

Windows maintains a long-lived connection with keepalive and reconnect backoff. iOS
opens short sync sessions when foreground/background time is granted. `hello`
negotiates protocol version, server time, limits, capabilities, and last sync cursor.
`sync.push` batches bounded observations/intents; `sync.pull` returns changes after an
opaque Core cursor. A Windows observation batch carries full provenance and captured
Session ID per sample or homogeneous batch; compactness comes from batching, not
ambiguous positional arrays. Commands remain individual, expiring, state-bound
messages and are never stored as a client offline inbox.

SSH ordering is transport ordering, not business authority. Core transactions,
idempotency keys, expected versions, state versions, and immutable plan revisions
remain the consistency mechanism. Web may continue HTTPS; all three clients converge
on the same Core services.

## Failure behavior

| Failure | Required behavior |
|---|---|
| NAS/Core/DB unavailable | clients show unavailable/stale; no new plan, lease, policy, or command |
| SSH disconnect | reconnect with backoff; replay only allowed outbox rows with original keys |
| Windows offline | queue evidence/ACK; local Emergency release remains available |
| iOS suspended | no continuous heartbeat claim; APNs may wake, otherwise sync later |
| APNs missing/fails | no state loss; notification delayed until SSH/foreground refresh |
| OCC conflict | stop intent replay, fetch Core, show conflict; never last-write-wins silently |
| stale command | reject and ACK/audit; do not execute after reconnect |
| clock skew | Core time wins; reject unsafe command windows and flag device clock |
| emotion/check-in missing | `UNKNOWN`; do not intensify |
| experiment service fails | base deterministic planner/policy continue unchanged |

Recovery order is PostgreSQL, migration head, Core readiness, bridge, then clients.
Clients replace stale snapshots from Core and drain allowed outbound rows. No cache is
promoted during recovery.

## Consented N-of-1 experiments

The user's broad permission covers safe advisory experiments only. Every experiment
has a manifest, fields, duration, retention, bounded arms, deterministic ceilings,
stop conditions and rollback. Experiments may tune advisory estimates, pressure
priors, check-in timing and reminder wording; they cannot alter code, credentials,
schemas, leases, hard guards, retention, camera frame handling, Emergency behavior
or user-only replan. ADR-0006 is normative.

## Consequences and non-goals

This topology is intentionally boring: one NAS authority, one desktop specialist,
one mobile specialist, one protocol bridge, one state ontology, and one intervention
pipeline. It avoids client-specific planners, peer-to-peer synchronization, generic
remote shells, hidden emotion inference, and a field for every possible life detail.

Costs are a new constrained SSH bridge, device key lifecycle, native iOS app, mobile
sync/notification contracts, human-state persistence, production NAS profile, and
backup/restore operations. Each is V2 work with tests. This ADR does not enable real
enforcement, camera sensing, medical inference, direct database access, or claim that
APNs/SSH/background execution is implemented.