# ADR-0005: NAS Core, Windows client, native iOS companion, and adaptive human state

- Status: Proposed for V2; does not change the frozen V1 contracts
- Date: 2026-08-29

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
resources, alert on readiness/backup/disk failure, and maintain an encrypted off-NAS
backup. Core liveness and readiness remain distinct.

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

The iOS client is a SwiftUI companion, not a wrapped PWA. Its small surfaces are
Today, Active Session, Check-in, Inbox, and Settings. It reads the current plan and
Session, submits start/pause/resume/complete/abort, break, ordinary override,
replan, explicit check-in, and Emergency intent, and displays freshness and dry-run
state. It never invents local success before Core commits.

The app contains a Keychain/Secure-Enclave-backed device identity, constrained SSH
client, typed codec, last-known-good read snapshot, durable user-intent outbox, sync
coordinator, and optional APNs installation. Cached plans and Sessions are visibly
stale and display-only. Only safe user-authored intents may queue; each carries an
idempotency key, creation/expiry, and version precondition. Conflicts stop replay and
require refresh/user resolution. Emergency queued offline is labeled **NOT
DELIVERED**; an iPhone cannot release a Windows restriction without reaching Core.

The phone is `PRIMARY_INTERACTION` or `NOTIFICATION_ONLY` at most. It is not a desktop
sensor, planner, lease issuer, command authority, or `PRIMARY_ENFORCEMENT`. iOS cannot
reliably run a 15-second heartbeat while suspended, so mobile liveness uses foreground
sync recency and push-installation state, not the Windows offline threshold.

APNs is optional but required for timely background alerts. Its payload contains only
an opaque wake/event identifier and expiry. The app subsequently opens SSH and pulls
current state. If communication is restricted to SSH alone, foreground and
opportunistic background sync are supported, but real-time suspended-app notification
is explicitly not guaranteed.

## Work semantics: complete without domain-specific sprawl

Do not hard-code a separate planner for every life area. A work item is described by
orthogonal semantics:

| Dimension | Values | Purpose |
|---|---|---|
| commitment | `FIXED`, `DEADLINE`, `FLEXIBLE` | calendar hardness |
| progress | `MILESTONE`, `QUANTITY`, `DURATION` | definition of progress |
| uncertainty | `LOW`, `MEDIUM`, `HIGH` | estimate range and buffer |
| interruptibility | `LOW`, `MEDIUM`, `HIGH` | chunk/freeze behavior |
| cognitive demand | `DEEP`, `NORMAL`, `LIGHT` | capacity matching |
| minimum viable dose | optional bounded unit | graceful daily floor |
| dependencies | explicit predecessor/waiting state | choose an executable next action |
| location/device needs | existing constraints | feasibility |

Examples:

- Research is usually `MILESTONE`, high uncertainty, low interruptibility, deep
  demand, and dependency-rich. A broad milestone must expose one executable next
  action such as read, implement, run, inspect, analyze, or write. Remote training
  may enter a waiting state while analysis or writing remains schedulable.
- English is `DURATION` or `QUANTITY`, flexible, divisible, and accumulation based.
  Comprehension is a noisy outcome sample, not a completion gate. The minimum viable
  dose may be minutes, items, or repetitions.
- Classes and exam sittings are `FIXED`; assignments and exam preparation are
  `DEADLINE`. Travel, preparation, and submission are explicit blocks/tasks rather
  than hidden estimates.

These are proposed V2 semantics. Adding persistence/API fields requires a separate
contract ADR, migration, and contract tests.

## Human state and emotion

### Evidence planes

Keep three planes separate:

1. **Observed execution:** existing context, presence, engagement, Session state,
   device role, confidence, freshness, and reasons.
2. **Self-reported human state:** felt capacity/emotion; the user is the source.
3. **Derived planning context:** deadline pressure, available time, interruption
   load, recent workload, environment fit, and dependency readiness.

A report always includes source, observed time, validity, confidence, and optional
reason. No value is silently carried forever.

### Minimal core ontology

The V1 execution axes remain core: planned context, Session phase, presence, and
behavioral engagement. Six additive V2 dimensions cover decisions that those axes
cannot make. `UNKNOWN` is separate from every scale.

| Dimension | Scale/source | Distinct decision | Safety rule |
|---|---|---|---|
| intent alignment | `ALIGNED`, `DELIBERATE_CHANGE`, `INVOLUNTARY_DIVERSION`, `UNKNOWN`; one tap after a mismatch | return versus pause/replan/end | nonresponse is `UNKNOWN`, never refusal |
| next-action readiness | `READY`, `BLOCKED_DEPENDENCY`, `BLOCKED_UNCLEAR`, `BLOCKED_RESOURCE`, `UNKNOWN` | run a ready sibling, unblock, or define the next action | blocker is not low ability/motivation |
| interaction availability | `AVAILABLE`, `LIMITED`, `DO_NOT_INTERRUPT`, `UNKNOWN`; explicit and time-boxed | normal, nonmodal/deferred, or suppressed delivery | contains no social identity/content |
| functional energy | self-report 0 depleted .. 4 high | shorten, switch demand, defer, recover | high energy never raises force |
| perceived cognitive demand | self-report 0 easy .. 4 overwhelming | decompose, buffer, switch, break | momentary demand, not ability |
| affective valence | self-report -2 unpleasant .. +2 pleasant | soften, suppress, break/replan/end | emotion can only de-escalate |

Every value has source device/type, observed time, expiry, confidence, and optional
reason. User report is authoritative for these dimensions; behavior may estimate
engagement only. The low-cost cadence is: energy+demand at Session start; blocker
only when work is ambiguous; intent only after a cooled-down mismatch; outcome and
burden at Session end; availability only when stale.

Emotion tags are optional, user-selected, limited to two, and explanatory rather
than policy-driving. Arousal, sleep sufficiency, coarse body constraint, recovery
quality, environmental workability, and English comprehension confidence are
experiment-only. Stress is likely redundant with demand+valence and is not core
until an experiment proves a distinct safe action.

Derived states are transparent and non-authoritative:

- `PROMPT_ELIGIBLE`: valid Session/context, present, available, fresh evidence, and
  remaining global prompt budget;
- `BLOCKED_WORK`: next action is not ready;
- `LOW_CAPACITY`: energy <= 1;
- `HIGH_DEMAND`: demand >= 3;
- `PLAN_AT_RISK`: a miss, overrun, blocker, or availability loss invalidates the
  remaining plan;
- `INTERVENTION_FATIGUE`: prompt budget exhausted or repeated dismiss/burden;
- `MINIMUM_VIABLE_DAY`: the feasible degraded remainder described below.

There is no composite productivity, wellness, discipline, or emotion score.
Motivation/willpower/laziness, named emotion taxonomies, personality, diagnosis,
wearable “stress”, exact location/social identity, camera/voice emotion inference,
message semantics, screenshots, keystrokes, clipboard, and content surveillance are
rejected. App switching may support engagement only, never intent or affect.

### Admission and simplification rule

The six dimensions above are the provisional V2 baseline selected by this
architecture. The admission test below applies to candidate dimensions beyond those
six; baseline dimensions remain removable/mergeable if later within-person evidence
shows excessive burden, redundancy, or no safe action benefit. Enable an additional
candidate only as an opt-in experiment and retain it only when all conditions hold
within this user:

1. eligible coverage >= 70%, median response <= 10 seconds, and every missing/stale
   case becomes `UNKNOWN`;
2. it changes a safe action and improves the relevant outcome by at least 10
   percentage points or 0.5 on a 0-4 scale;
3. it improves held-out decisions by >= 10% or selects a distinct beneficial action
   in >= 15% of opportunities;
4. it produces no DND violation, emotion-based escalation, duplicate prompt, or hard
   schedule-truth violation;
5. burden rises <= 0.5 and the effect direction repeats in >= 60% of matched pairs
   across at least three weekly blocks and two relevant domains/profiles.

If two dimensions have absolute within-person rank correlation >= 0.80 and action
agreement >= 80%, keep the lower-burden one unless discordant cases have a
prespecified benefit. Failed candidates are merged or deleted from collection,
policy, UI, and retention—not retained as unused telemetry.

### Experimental, not core by default

Sleep duration/quality, hunger, pain location, social load, loneliness, noise,
lighting, caffeine, exercise, time of day, interruption count, task interest,
self-efficacy, novelty, comprehension, and location comfort are candidate features.
Many are redundant, sensitive, costly, or only useful for one domain. They stay in
an experiment/profile namespace until evidence shows a stable decision benefit.
Medical symptoms, diagnoses, inferred personality, camera emotion recognition,
message sentiment, and content surveillance are rejected.

## Replanning as the anti-collapse loop

A replan follows this order:

1. read the latest committed plan, fixed commitments, Session, explicit human-state
   report, dependency state, and available interval;
2. preserve completed work and valid near-term frozen blocks, but release blocks
   made impossible by a changed hard fact;
3. place classes, exam sittings, hard deadlines, meals, travel, and recovery
   constraints;
4. select only dependency-ready work and match cognitive demand to capacity;
5. retain a small stability cost for still-valid old blocks;
6. build and audit a feasible remaining plan when possible;
7. if full completion is impossible, try a **minimum viable day**; if required work
   still cannot fit, return an `INFEASIBLE` conflict/tradeoff report rather than
   declaring the day abandoned or fabricating feasibility.

The initial minimum viable day order is: required course/exam commitments,
essential meal/travel/recovery, mandatory deadline work, the English minimum dose,
then one executable research progress/unblock action where capacity remains. This
is a policy to test and personalize, not a permanent universal rule. Carry-over is
explicit, bounded, and visible; optional work can be `PARTIAL` without moral
failure.

## Complete intervention loop

Intervention intensity and intervention purpose are separate. The purpose is one of
return, clarify next action, break, replan, recover, or end. The existing numeric
levels remain compatible:

| Level | Target behavior | Safety cap |
|---:|---|---|
| 0 | observe/log nothing disruptive | default for unknown/stale evidence |
| 1 | ambient cue | cooldown; no response required |
| 2 | explicit choice: return/break/replan/end | preserve user control |
| 3 | pre-authorized friction; V1 `WOULD_BLOCK` only | mode >= STANDARD, fresh state |
| 4 | bounded recovery workflow; V1 policy-only | STRICT plus complete guard |
| 5 | interrupt Session and replan | no coercive extension |

Every decision executes the same pipeline:

1. verify Session, target, state version, freshness, confidence, and sensor health;
2. determine need/purpose from execution evidence and user report;
3. cap intensity by immutable commitment mode and complete authorization;
4. de-escalate for distress, physical constraint, overload, uncertainty, recent
   response, and cooldown;
5. apply hysteresis and a per-Session prompt budget;
6. emit one typed expiring idempotent command or a replan intent;
7. collect delivery, display, choice, and execution as distinct outcomes;
8. update Session/replan only after Core commits; audit input and result;
9. evaluate whether the intervention helped before repeating.

Emotion never moves a decision upward. Ignoring a prompt is not proof of consent,
absence, or defiance. Escalation requires fresh behavioral evidence and cannot skip a
level solely because prompts were missed. Emergency Release is out-of-band, available
at every level, and never waits for ordinary OCC/policy. Windows must provide a local
offline release UI before any real restriction exists.

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

## Consented N-of-1 social experiments

No experiment has been run yet. These are opt-in, time-bounded, reversible design
hypotheses; none can authorize enforcement. Use a seven-day observation run-in,
randomized/counterbalanced within-person periods where safe, policy-version logging,
and domain/profile stratification. Never manufacture a miss or deny a requested
break.

| Experiment | Comparison | Primary graduation signal |
|---|---|---|
| check-in cadence | start/end only versus one event-triggered question | response >= 70%, median <= 10 s, burden increase <= 0.5 |
| intent alignment | intent tap versus neutral return notice at eligible mismatch | distinct action >= 15% and unhelpful prompts fall >= 10 points |
| energy/chunk | shorter user-selectable chunk versus profile default at energy 0-2 | goal outcome +10 points or energy decline improves 0.5 in >= 60% pairs |
| demand versus blocker | decompose/break versus dependency/resource/clarify question | blocker selects a distinct action >= 15% and helpfulness improves 0.5 |
| affect de-escalation | supportive single choice versus defer/silence at valence <= -1 | unhelpful prompts fall >= 10 points without worse goal outcome |
| cross-client availability | context-only versus explicit timed availability + NAS dedupe | bad-time prompts fall >= 50%, duplicate prompts = 0, entry <= 5 s |
| recovery timing | offer break now versus next natural boundary | next-period energy +0.5 or progress +10 points without more abort/burden |
| anti-collapse MVD | full replan versus full replan plus immediate minimum viable day | accepted feasible remainder within 5 min +20 points or abandoned-day rate -10 points |
| research next action | broad milestone versus one dependency-ready action | lower start latency and blocked-session rate |
| English dose | duration versus quantity/repetition target | adherence improves; comprehension remains an optional noisy sample |

Universal stop conditions are user withdrawal/emergency, privacy or SSH-boundary
violation, any DND prompt, unreliable delivery, two “made worse” ratings in one
week, burden >= 3 on two consecutive days, protected-course failure, or observed
sleep/recovery harm. Emergency, override, and real enforcement are never randomized.
Too few opportunities yields `INSUFFICIENT_EVIDENCE`; thresholds and safety rules
are not relaxed.

NAS owns experiment assignment, dedupe, global prompt budget, analysis, and audit.
Raw experiment features use shorter retention than business/audit facts. A suggested
initial budget is at most one spontaneous check-in per 30 minutes, two proactive
prompts per Session, and four per day across Windows and iOS, with none in
`DO_NOT_INTERRUPT`, `CLASS`, `TRAVEL`, `SLEEP`, or `EMERGENCY`.

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