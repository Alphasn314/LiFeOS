# ADR-0006: self-evolution, LifeOS Windows integration, and focus sensing

- Status: Proposed for V2; amends ADR-0005
- Date: 2026-08-29
- Scope: learning-related LifeOS behavior only

## Context

LifeOS needs to learn this user's task durations and experienced pressure because a
single planned duration is often inaccurate. The user's daily schedule is still a
user-authored plan, but Core should compare it with personal history, explain obvious
mismatches, and propose a more feasible next-day arrangement.

The user's work is mostly research, English, and school. Research contains very
different actions (reading, implementation, training, debugging, analysis, writing)
and can remain productive through repeated failed attempts. English is generally
low pressure and accumulation-oriented. Mathematics/course work is often medium
pressure. These are cold-start priors, not permanent labels.

A mature local `self discipline controller V4.2` exists at
`C:/Users/Alpha.sn/Desktop/bilibili_controller`. It has a tray, autostart, a
transactional installer/recovery/uninstaller, hosts and Chrome/Edge HKLM policy
ownership, exact process termination, WeChat temporary access/relock, and a
60-second typed unlock gate. Its 115 isolated tests pass. It is a real enforcement
implementation, but it currently owns local timer/work-app policy and has no LifeOS
Session/lease/TTL authority or automatic break release.

The user wants one final `LifeOS Windows` application, Xcode direct installation on
an iPhone 17 using a free personal team, VPN-first remote NAS access, on-device
camera focus sensing, three core human-state dimensions, user-only replanning, a
03:00--07:00 maintenance window, permanent personal history, and local-NAS-only
backup.

This ADR designs those changes. It does not enable real enforcement, change frozen
V1 contracts, copy the external controller source, or claim that the iOS project is
implemented. Contract/persistence changes require their own migration and tests.

## Amendments to ADR-0005

ADR-0005 remains authoritative for the NAS/Windows/iOS topology, constrained SSH,
Core/PostgreSQL authority, and privacy boundary, except:

1. the provisional six human-state dimensions are replaced by three core learning
   dimensions: focus, fatigue, and current emotion;
2. sleep, body, and environment enter only through an explicit user report that they
   affect learning now;
3. no domain has a fixed minimum daily quota;
4. automatic plan revision is removed: an authenticated explicit user intent may
   create or accept an initial daily plan, and only an authenticated
   `REQUEST_REPLAN` may replace an existing authoritative PlanVersion;
5. iOS first delivery uses Xcode free signing and local scheduled notifications,
   not APNs;
6. LifeOS Windows incorporates bounded facilities from the local Self Discipline
   Controller, with real actions remaining unreachable until the full guard matrix
   passes;
7. V2 implements encrypted same-NAS snapshots/local copies as requested and labels
   disaster recovery incomplete; it does not claim an off-NAS backup exists.

## “Self-evolution” means parameter learning, not code mutation

Self-evolution updates versioned task profiles, duration distributions, pressure
models, prompt parameters, and schedule advice. It never rewrites Python/Swift/
Windows production source at runtime. Code evolution remains Git branch -> review ->
tests -> signed release -> rollback artifact.

AI output is a typed proposal only. A deterministic service validates feature names,
finite ranges, evidence provenance, confidence, version compatibility, sample
limits, and safety before storing a new model revision. Planner and Policy consume
an explicitly selected immutable revision; they never read a half-updated model.
Every revision can be compared, rejected, rolled back, and audited.

## Module shape inspired by OMP, but inside LifeOS

OMP extensions are unsandboxed in-process TS/JS factories. OMP skills and memory are
passive agent guidance and are not production state. LifeOS therefore uses a normal,
statically imported Core module rather than an OMP extension or self-writing skill:

```text
backend/lifeos/modules/
  base.py                 typed LifeOSModule protocol
  registry.py             explicit allowlisted built-in registry
  self_evolution/
    module.py             manifest + lifecycle
    features.py           bounded task feature extraction
    duration.py           online duration distribution
    pressure.py           experienced-pressure proposal/calibration
    feedback.py           feedback normalization
    advisor.py            next-day schedule advice
    service.py            transaction/orchestration boundary
```

A module manifest contains `module_id`, semantic version, input schema versions,
output schema versions, algorithm version, required tables, feature flags, and
rollback compatibility. Registry entries are explicit source imports reviewed with
the application. There is no arbitrary module directory, network download, runtime
`pip install`, dynamic shell hook, or client-provided code.

The production module may register only typed operations with Core services. It
cannot register commands, bypass policy, issue leases, mutate unrelated aggregates,
or execute shell/registry/firewall actions. OMP may expose a developer tool or skill
that reads learning summaries, but OMP memory remains heuristic engineering context,
not task profile, user approval, model revision, lease, or deployment truth.

## Persistence model

### `task_execution_feedback` (append-only)

One row represents user-confirmed or strongly bounded feedback for a task Session:

- feedback UUID and idempotency key;
- task, Session, PlanVersion and ScheduleBlock IDs;
- task fingerprint and structured action subtype;
- planned minutes;
- active minutes and wall-clock minutes;
- completion state or bounded progress units;
- productive-attempt count when no visible progress occurred;
- focus 0--4/UNKNOWN, fatigue 0--4/UNKNOWN, emotion -2..+2/UNKNOWN;
- experienced pressure 0--4/UNKNOWN;
- interruption count/duration and evidence quality;
- user correction/reason;
- source device, occurred/received time and schema version.

Passive evidence cannot claim completion, emotion, fatigue, experienced pressure, or
progress units. Those fields require explicit user/task-adapter evidence and record
provenance separately.

### `task_learning_profiles` (versioned current profile)

A profile is keyed by user scope plus a bounded task fingerprint hierarchy:

```text
global -> domain -> action subtype -> stable task -> optional context bucket
```

It stores duration posterior sufficient statistics, P50/P80, uncertainty,
experienced-pressure distribution, sample count, effective sample weight, last
update, model revision, cold-start source, and user overrides. It does not store a
free-form model prompt or executable code.

### `estimate_revisions` (immutable)

Each learning run writes the exact prior profile version, evidence IDs, normalized
feature vector, algorithm/version, new parameters, predictions, confidence,
validation decisions, and reason codes. The selected profile head moves only after
all revisions commit.

### `schedule_advice` (immutable proposal + outcome)

Stores the user's original next-day plan, profile revision, predicted P50/P80 per
block, pressure/fatigue findings, proposed changed blocks, feasibility/conflicts,
explanation, and `PENDING/ACCEPTED/REJECTED/EXPIRED`. Advice is not a PlanVersion.
Only user acceptance or an explicit plan-generation request creates an authoritative
plan.

### `learning_runs` and daily summaries

A run records input cursor, profile versions, AI provider/model (if used), validation,
output revisions, error, start/end time and audit causation. Existing
`daily_summaries` becomes the permanent readable memory layer; high-frequency
records remain date-partitioned evidence.

## GitHub-first engineering policy

Before implementing a capability:

1. check the operating-system/framework API first;
2. search GitHub and inspect source, license, exact tag/commit, path-level activity,
   dependencies, security advisories, and failure behavior;
3. record one disposition: `ADOPT`, `ADAPT`, `STUDY_ONLY`, or `REJECT`;
4. reject unlicensed snippets/gists and default-reject GPL/AGPL or unsuitable LGPL
   coupling without explicit legal review;
5. pin versions/hashes, retain notices, produce an SBOM, review upgrades, and keep a
   rollback artifact;
6. extract only the coherent minimum behind a LifeOS-owned typed interface;
7. delete demo credentials, accept-all trust, telemetry, generic shells and unused
   targets;
8. add denial/timeout/replay/rollback tests before enabling the result.

Reuse never weakens Core authority, user-only replan, frame privacy, or hard-action
guards.

### Source decisions for this design

| Candidate | License/status | Decision |
|---|---|---|
| River `BayesianLinearRegression` 0.26.1 @ `64285b9` | BSD-3-Clause, active | `ADAPT`: reproduce the bounded online predictive-distribution behavior; do not add the heavy NumPy/SciPy/Narwhals/Rust package |
| River adaptive Hoeffding tree | BSD-3-Clause | `STUDY_ONLY`: bounded-memory/drift pattern; pressure stays advisory and simpler first |
| local Self Discipline Controller V4.2 | user-confirmed original project; private LifeOS-use authorization selected; third-party notices present | `ADAPT`: repository owner authorizes copying, modifying and building inside their private LifeOS project; no public redistribution grant; preserve all MIT/BSD/HPND/LGPL/PyInstaller notices |
| H.NotifyIcon @ `61a5132` | MIT, active | adopt only if LifeOS Windows moves to WPF/WinUI; current Python tray already works |
| Velopack 1.2.0 | MIT, active | future signed installer/update channel; automatic apply stays off until rollback tests |
| Microsoft WFPSampler | MS-PL, driver sample | `STUDY_ONLY`; no custom kernel blocker |
| Windows Assigned Access / UserConsentVerifier | platform / MIT sample | study platform boundaries; not a replacement for LifeOS authorization |
| Apple `swift-nio-ssh` 0.15.0 @ `3ec2814` | Apache-2.0, active | `ADOPT` behind a typed NAS client with host-key pinning; never a generic shell |
| AVFoundation + Vision | Apple platform APIs | `ADOPT` directly for on-device inference |
| HandPoseDetection @ `cc8357c` | MIT, recent/small | `STUDY_ONLY/ADAPT` camera queue and Vision-request pattern only |
| UserNotifications | Apple platform API | `ADOPT` directly; no remote push dependency |
| NnReminderKit @ `f55a8d9` | MIT, active | study its adapter/tests; native wrapper is smaller |
| Shout | MIT but stale/macOS-only | `REJECT` |

## Duration estimation

### Observation target

The primary duration label is completed active time, not wall-clock time. Wall time,
interruptions and waiting are stored separately. Partial Sessions are censored
observations; they constrain a lower bound but do not pretend to reveal total
completion time. Repeated productive attempts count as focus evidence but not as
completed progress.

### Fixed feature schema

Keep a small, versioned feature vector:

- domain and action subtype;
- activity profile and cognitive mode;
- user-provided planned duration;
- task/dependency readiness and uncertainty bucket;
- time-of-day bucket;
- recent 2--3 day duration ratio summary;
- current focus/fatigue/emotion only when valid;
- prior interruptions and stable task identity where enough samples exist.

Titles/descriptions may be sent to AI only to propose allowlisted tags. Raw text is
not a numeric feature and is never embedded into an unbounded vector.

### Hierarchical online predictor

Use a bounded Bayesian linear/log-duration predictor inspired by River:

- cold start shrinks to `global -> domain -> subtype` priors;
- completed samples update the task/subtype posterior one at a time;
- use log duration or log actual/planned ratio and robustly reject/clamp impossible
  non-finite/outlier updates;
- optional smoothing handles gradual concept drift;
- expose P50, P80, evidence count, effective weight, confidence and reason codes;
- use P80 for high-uncertainty research and P50 for divisible low-pressure work, as
  selected by the user; always display both the selected and alternative quantiles;
- limit feature dimension because covariance update is quadratic;
- prequentially record forecast error before updating the model.

The user's estimate is always preserved and shown beside the learned estimate. User
correction can freeze a task estimate or reset a contaminated profile.

## Experienced-pressure learning

“Pressure” here means the user's experienced cognitive/emotional cost, not objective
deadline pressure. Use 0 effortless, 1 light, 2 medium, 3 high, 4 extreme, plus
`UNKNOWN`.

Initial priors may be English=1, mathematics/course=2 and research=3, but each action
subtype and stable task learns independently. A post-Session one-tap rating is the
highest-quality label. AI may propose the action subtype and a prior with an
explanation. It cannot label emotion/fatigue, authorize a block, or update the profile
without deterministic validation. Missing feedback remains `UNKNOWN`.

The first model is transparent weighted counts/EWMA with shrinkage to the hierarchy,
not an adaptive tree. Store calibration and disagreement with user ratings. Study
River's prequential/drift patterns only after enough personal samples justify the
complexity.

## Next-day schedule advice

The user submits a complete time-to-task plan. SelfEvolutionService:

1. snapshots the selected profile/model revisions;
2. predicts P50/P80 and pressure per block;
3. checks fixed events, dependencies, location/device, transitions, breaks and total
   available time;
4. detects under-allocation, excess allocation, pressure clustering and a fatigue
   mismatch;
5. simulates small changes while preserving the user's chosen tasks and fixed facts;
6. returns the smallest feasible `ScheduleAdvice` with old/new times, confidence and
   reasons;
7. waits for user acceptance/rejection and learns from that outcome.

Advice may say the user's plan is already reasonable. It never silently edits the
plan. After each day, accepted feedback updates profiles for the following day.
There is no fixed English/research/course minimum; any domain may receive zero time.

An authenticated `CREATE_DAILY_PLAN` or `ACCEPT_SCHEDULE_ADVICE` intent may create
the initial authoritative plan for a day when none exists. It cannot replace an
existing plan; replacement requires `REQUEST_REPLAN`.

Pressure affects ordering and recovery spacing, not moral priority. Avoid adjacent
high/extreme blocks when feasible, place higher-pressure work when fatigue is lower,
and use low-pressure/divisible work as transition or recovery. Hard course events
and user choices still outrank model preference.

## Severe deviation and user-only replanning

Core continuously computes a projection but does not automatically replan.

1. Compare elapsed/progress evidence with the current block's learned distribution.
2. Simulate recovery using allowed compression toward a safe lower quantile and
   removal/deferment of whole flexible blocks.
3. If the remaining plan is feasible, do not recommend replan; show status only.
4. If required/fixed work still conflicts, or projected shortfall crosses the
   configured severe threshold, append `REPLAN_RECOMMENDED` with shortfall,
   confidence, recovery attempts and tradeoffs.
5. Deduplicate and display that recommendation on Windows, iOS and Web.
6. Only a user-authenticated `REQUEST_REPLAN` that names the current plan ID and
   revision may invoke Planner to replace that immutable PlanVersion.

The V2 cutover removes all other revision producers. `EventOrchestrator.ingest`
converts non-user `PlanTrigger` values to status/recommendation events only.
`POST /api/v1/sessions/{session_id}/break` records the break and releases control but
does not call `PlanService.insert_break` or create a PlanVersion.
`POST /api/v1/plans/generate` is disabled for replacing an existing plan and rejects
AI, service, sensor, device-only, or non-user triggers. Initial plan creation and
accepted advice use the separate user-intent operations described above.

A device transport key proves only device identity. It is insufficient for a user
intent. Windows, iOS and Web use a separate interactive `HUMAN_INTENT` capability:
the user enters the dedicated UI action, completes OS user-presence confirmation
(Windows Hello, iOS LocalAuthentication/Secure Enclave, or the authenticated Web
equivalent), and the isolated UI signer creates a one-time envelope containing
`intent_id`, action, user/device IDs, plan ID/revision, nonce, issued/expiry times and
signature. Core consumes the nonce once, audits the presence method, and denies
telemetry, AI, service and ordinary device principals. AI cannot access this signer
or submit `REQUEST_REPLAN`.

The severe threshold remains an explicit unresolved policy (for example a
fixed-event collision or a bounded remaining shortfall), not a silently learned
setting.

## LifeOS Windows: one application

### Merge boundary

Use the existing `LifeOSWindowsAgent -> CommandProcessor -> capability adapter ->
durable ACK` flow as the host. Do not copy the standalone Controller's autonomous
decision loop wholesale. After provenance is recorded, transplant or clean-room
adapt only bounded facilities:

- transactional owned hosts/HKLM Chrome/Edge policy apply/remove;
- exact executable/path process safety and termination;
- immediate recovery/reconciliation;
- tray, single-instance, signed install/autostart/uninstall concepts;
- typed unlock normalization and UI, separated from authorization.

Do not merge Bilibili synchronization, standalone DeepSeek encouragement, local AI
policy, generic local blocked-rule authority, or the controller's completion-held
blocking behavior into NAS authority.

### One process and authority order

```text
immediate local Emergency Release
  > authoritative NAS rest/release/terminal state
  > valid fully guarded NAS restriction command
  > visible standalone advisory/dry-run fallback
  > ordinary notification
```

A NAS message is not enough. A real command must pass target device, current
nonterminal Session, commitment preauthorization, command-row `dry_run=false`, fresh
state version, TTL/not-before, idempotency, exact blocklist membership, bounded
duration, online Core/device, current unrevoked `PRIMARY_ENFORCEMENT` lease, local
capability, rollback readiness and audit checks.

`BREAK`, `PAUSED`, `MEAL`, `TRAVEL`, `RECOVERY`, `EMERGENCY`, terminal/no Session,
expired command/lease, stale Core or user override causes synchronous removal of
every NAS-owned restriction. A watched work application cannot re-lock during those
states. Restrictions have monotonic local expiry and restart reconciliation.

### Safe standalone fallback

When no fresh authoritative NAS assignment exists, the user may explicitly enable a
local timer/work-app fallback inspired by V4.2, but it is advisory/dry-run only. It
may show the focus UI, timer, reminders and `WOULD_BLOCK`; it cannot change hosts,
browser policy, processes or applications because the mandatory online Core,
Session, lease and preauthorization guards cannot pass. When NAS authority returns,
a valid NAS restriction becomes reachable only after every guard passes. The
fallback is visible in tray/UI and can be disabled permanently.

### One UI and installation identity

Final branding and resources are `LifeOS Windows`, one tray icon, one mutex, one
ProgramData root, one user credential store, one machine policy manifest, one
scheduled task/autostart entry, one signed installer, one Recovery tool, and one
uninstaller. Existing V4.2 installer rollback, direct-child path safety, health/UI
smoke and recovery behavior are useful patterns. A future Velopack feed may update
signed builds, but update and policy synchronization remain separate.

### Lock, unlock, friction and Recovery

“Lock” means bounded application/site restriction and focus UI, not Windows account
lock or an irreversible kiosk. Existing V4.2 serious actions are sufficient for the
first real adapter; no kernel driver is planned.

Unlock choices become typed LifeOS intents:

- return to current task (keep restriction);
- request a Core-committed break (release after ACK);
- ordinary override with reason;
- request replan (user command only);
- end/abort Session;
- immediate local Emergency Release (no phrase/network requirement).

The selected first-release friction is F3: the existing 60-second random typed
phrase plus configured site/process restriction. F3 is not independent authority:
the restriction remains unreachable until every NAS hard-action guard passes. The
phrase cannot delay Emergency, and typed text alone cannot authorize a NAS state
change.

The selected first-release Recovery is R1: synchronously and unconditionally release
all restrictions, including when hard-action authority is stale or unavailable.
When Core is reachable, best-effort commit and schedule a 10-minute restorative
break, then ask the user to return, request replan, or end the Session. Replan still
requires the separate `HUMAN_INTENT` path.

F1 notification/choice, F2 short delay/reason, F4 F3 plus Windows Hello, R2
user-confirmed 15-minute allowlist, and R3 no automated Recovery remain documented
alternatives, not active first-release policy. No friction/Recovery arm is randomized
with real enforcement.

## iOS direct-install design

### Provisioning

Create a SwiftUI Xcode project targeting the user's latest iOS on iPhone 17. Use a
free Personal Team and automatic signing for direct device development. Xcode reads
the device identifier and installs over cable/local pairing. Provisioning expiry
means periodic rebuild/reinstall; this is not a stable unattended distribution
channel. Mac app/Catalyst follows only after iOS/Windows/NAS are stable.

### Networking and reminders

Use Apple `swift-nio-ssh` behind `NASAuthorityClient`, with a paired device key in
Keychain, pinned SongNAS host key, typed LifeOS subsystem only, output/time limits,
and no shell/forwarding. VPN is the normal remote path.

Without a paid Developer Program, do not depend on APNs. Each accepted plan sync
replaces local `UNUserNotificationCenter` requests by stable opaque IDs. Notification
text is generic on the lock screen. Dynamic NAS changes are fetched when iOS receives
background time or the user opens the app; immediate remote delivery is not
guaranteed. Windows receives NAS commands independently and remains the reminder
fallback when the phone is absent or suspended.

### Camera focus evidence

Camera use is explicit and foreground-only during a focus Session. AVFoundation
provides a local preview and throttled sample buffers; Vision/Core ML processes them
on a private queue. Buffers are immediately discarded. No frame, thumbnail, video,
embedding, face identity, emotion, or crash attachment is stored or uploaded.

Allowed outputs for a bounded interval are presence, facing/work-orientation class,
continuous-away duration, sample coverage, model confidence, validity and reason
codes. Camera denial, background suspension, occlusion, phone removal, model failure
or low confidence is `UNKNOWN`, never low focus or noncompliance.

The phone uploads only coarse evidence to NAS. NAS combines it with Windows
engagement and task-progress adapters; it may create a typed reminder decision, which
Windows independently validates/displays/executes. No phone message directly locks
the computer.

## Three core current-state dimensions

### Focus 0--4 + `UNKNOWN`

Focus represents sustained task-directed progress or serious task-directed attempts,
not mere camera presence and not only artifact output.

- 0: valid evidence of absence or sustained unrelated engagement;
- 1: fragmented, mostly unrelated engagement;
- 2: intermittent task attempts with substantial switching;
- 3: sustained task-related attempts or steady progress;
- 4: deep, continuous task work with steady progress or repeated meaningful attempts.

The NAS AI harness receives only allowlisted summaries: Windows engagement,
on-device camera aggregate, user/task-adapter progress events, attempt events and
Session context. Task adapters report counts/state transitions, not document/code
content. No-progress repeated experiments/debug attempts can support 3/4 when their
structured attempt evidence is valid. AI returns a score proposal, confidence and
reason codes; deterministic fusion validates coverage/conflict/freshness.

### Fatigue 0--4 + `UNKNOWN`

- 0: fresh;
- 1: mild cost, normal work possible;
- 2: noticeable fatigue, shorter/lighter block useful;
- 3: high fatigue, sustained work unreliable;
- 4: functionally unable to continue this learning block.

User report is authoritative. Performance decay may trigger a check-in but cannot
assign fatigue. Fatigue can shorten/defer/release/recommend rest; it cannot increase
force.

### Current emotion -2..+2 + `UNKNOWN`

- -2: very angry/sad/unwilling now;
- -1: negative/reluctant;
- 0: neutral;
- +1: positive/willing;
- +2: passionate/strong willingness.

Emotion is current and self-reported. It is not inferred from camera, text, app use
or productivity and does not create long-term subject-confidence/enthusiasm models.
It may soften/release/recommend rest or change wording; it cannot increase force.

Blocker/dependency, schedule feasibility and device availability remain task/system
facts rather than extra human-state dimensions. Sleep, body and environment enter as
an explicit, expiring user-reported auxiliary reason only when the user says they
affect learning now.

## Experiments and AI autonomy

The user's broad permission authorizes safe advisory experiments, not unbounded
surveillance or hard-action randomization. Every experiment still has a manifest,
hypothesis, fields, retention, arms, duration, stop conditions, rollback, policy
version and result. Emergency, real block, denial of break, credential handling,
camera retention/upload and user-only replan are never randomized.

NAS AI may adapt check-in timing, advisory estimates, pressure priors, reminder
wording and safe recommendation thresholds within configured bounds. It cannot
change code, schemas, permissions, leases, commitment, blocklists, retention,
Emergency behavior or submit replan. Global prompt/check-in caps remain a deterministic
safety ceiling even when AI chooses fewer or differently timed prompts.

## Retention, VPN, maintenance and backup

- trusted remote VPN is the normal network boundary; no public SSH/Core exposure;
- SongNAS pairing uses the already known NAS identity plus a verified VPN hostname or
  address that still must be recorded during implementation;
- maintenance runs only in the user window 03:00--07:00 local and never interrupts an
  active Session without an explicit maintenance transition;
- decision context reads the latest 72 hours of detailed state by default, then
  long-term summaries/profiles as needed;
- personal-history summaries, daily summaries, task profiles, model revisions,
  plan/session and audit history are retained permanently per user instruction and
  sorted/partitioned by date;
- camera frames never exist as retained personal data;
- test/fixture data is deleted after the formal release is frozen;
- high-frequency raw evidence is retained indefinitely by explicit user selection.
  It must be encrypted, date-partitioned, growth-monitored, capacity-alerted,
  exportable/deletable by the user, excluded from ordinary prompts, and never include
  camera frames, video, embeddings, keystrokes, clipboard, screenshots, microphone
  or content surveillance;
- same-NAS snapshots/local copies are implemented as requested but remain one failure
  domain. They protect against some deletion/rollback events, not NAS theft, fire,
  filesystem corruption or total device loss. The product must label disaster
  recovery as incomplete until an off-NAS copy exists.

## Implementation order

1. Freeze ADR/contracts and record controller provenance/licenses.
2. Add self-evolution tables, migration, schemas and contract tests.
3. Implement deterministic online duration/pressure profiles and advice, then AI
   feature proposals.
4. Add user feedback, separate human-intent signing, and explicit
   replan-recommendation/command flows; retire every automatic PlanVersion producer.
5. Merge one non-destructive LifeOS Windows tray/installer/transport application.
6. Adapt controller backends behind a disabled real-enforcement capability and build
   the complete guard/failure suite.
7. Build the Xcode iOS client with SSH, local notifications and coarse camera
   evidence; complete direct-device smoke.
8. Add VPN production profile, retention partitions, local backup/snapshot and
   maintenance jobs.
9. Implement the selected F3 friction and R1 Recovery only after the guard/failure
   suite passes; keep real enforcement feature-flagged off until then.

## Remaining explicit decisions

- confirm the VPN hostname/MagicDNS name reachable from iPhone/Windows;
- choose the initial severe-deviation recommendation threshold.

Selected on 2026-08-30: F3 friction; R1 Recovery; P80 high-uncertainty research and
P50 divisible low-pressure scheduling; experiment, code, paper-reading and research-
writing progress adapters; indefinite raw-evidence retention under the safeguards
above; and private LifeOS-only authorization for the user's original Controller
source. These choices do not enable real enforcement by themselves.

## Consequences

The design becomes more adaptive without making AI sovereign. It reuses the existing
serious Windows controller instead of rebuilding it, while placing real actions
behind the existing LifeOS command boundary. It supports free-signing iOS constraints
honestly and treats camera output as transient on-device evidence. The cost is new
persistence, indefinite raw-evidence capacity/privacy governance, migrations, model
governance, a substantial Windows merge, an Xcode client, and explicit VPN/severe-
threshold decisions.