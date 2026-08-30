# Intervention policy

Commitment authority is chosen when a session starts and is immutable:

- `ADVISORY`: notify and suggest only.
- `STANDARD`: notify and display a topmost information surface. V1's Windows
  surface is an OK-only MessageBox that does not auto-close with Command TTL;
  follow-up choices are separate Web/API actions. Blocklist behavior remains dry-run.
- `STRICT`: STANDARD plus pre-authorized entertainment-process close/restart block
  and Recovery Mode (both feature-flagged off until V2).

## Levels

| Level | Evidence | Result |
|---|---|---|
| 0 | normal/unknown | no disturbance |
| 1 | continuous OFF_TASK 30-90 s | desktop notification |
| 2 | 90-180 s | topmost information box listing return/break/replan/end; no native choice result in V1 |
| 3 | >180 s and mode >= STANDARD | 10-minute blocklist; V1 emits `WOULD_BLOCK` |
| 4 | `ignored_prompts>=2` and STRICT | Recovery `WOULD_BLOCK`, 15 minutes in pure policy only |
| 5 | `ignored_prompts>=3` | interrupt/replan notification in pure policy only |

Unknown/low-confidence evidence cannot escalate. A decision records its input state
version, commitment authority, dry-run state, action, expiry, and reason codes.
For V1 Level 2, the Agent ACK has status `EXECUTED`; the informational outcome is
recorded as `details.outcome=CONFIRMATION_SHOWN`, not as an ACK status or a user choice.
Repeated evaluation at the same state/level uses the same semantic idempotency key.
The V1 RuntimeService currently supplies `ignored_prompts=0`, so levels 4 and 5
are covered as pure policy behavior but are not operational state transitions.

## Safety Guard

V1 policy constructs SAFE `WOULD_BLOCK` directly; it does not construct a hard
command and then transform it. Polling verifies target association, expiry and
current state version for ordinary commands. If a future row is marked HARD, the
current Core additionally requires real enforcement enabled, the global Core
dry-run setting disabled, the stored device status online/reachable, and a current
matching `PRIMARY_ENFORCEMENT` lease. It does not inspect that Command row's own
`dry_run` value or refresh heartbeat freshness during poll.
The schema caps payload duration at 30 minutes.

Active-session lookup, stored session preauthorization, and task blocklists exist,
but the current hard-row polling branch does not re-check all three. Therefore
real enforcement must remain disabled until V2 adds those checks plus Command-row
dry-run, heartbeat freshness, blocklist membership, payload duration, lease-state
authorization, and failure-injection tests. Rejections that the current guard does
detect are audited.

## Overrides

When Core/database is reachable, Emergency Release has no ordinary-policy or OCC
precondition: its transaction cancels pending enforcement, queues a bounded
`RELEASE_ALL`, preserves a terminal state or marks a non-terminal session
INTERRUPTED, and appends an audit event. Device-side delivery is asynchronous;
V1 has no user-facing offline Agent button. Ordinary Override requires a non-empty reason, cancels pending
enforcement, issues `RELEASE_ALL`, and sets the session to PAUSED. A later resume,
complete, abort, or replan is a separate explicit action.

## Target LifeOS Windows intervention loop (V2 design)

LifeOS Windows merges the existing Agent with bounded facilities from Self
Discipline Controller V4.2. Purpose and intensity remain separate:

| Level | LifeOS Windows surface |
|---:|---|
| 0 | observe; no disturbance |
| 1 | tray/native light reminder |
| 2 | native choice: return, break, override, request replan, end |
| 3 | optional friction using typed delay plus bounded site/process restriction |
| 4 | selected R1: fail-open full release, then 10-minute restorative break |
| 5 | explicit severe-deviation/replan recommendation; never automatic replan |

NAS AI may choose check-in/reminder timing only within deterministic configurable
ceilings; no daily count is fixed yet. It cannot authorize enforcement or replan.

### Authority and automatic release

```text
immediate local Emergency Release
  > authoritative NAS rest/release/terminal state
  > valid fully guarded NAS restriction command
  > visible local standalone advisory/dry-run fallback
  > ordinary notification
```

A NAS message is insufficient. A real restriction requires correct target, current
Session, commitment preauthorization, command-row `dry_run=false`, fresh state/TTL,
idempotency, exact blocklist and bounded duration, online Core/device, current
unrevoked `PRIMARY_ENFORCEMENT` lease, local capability, rollback readiness and
audit. Real enforcement remains unadvertised/unreachable until the complete test
matrix passes.

`BREAK`, `PAUSED`, `MEAL`, `TRAVEL`, `RECOVERY`, `EMERGENCY`, terminal/no Session,
expired command/lease, stale Core, override, and local Emergency synchronously
remove every NAS-owned restriction. A watched work program cannot re-lock during
those states. Restrictions also have monotonic local expiry and restart
reconciliation.

When NAS has no fresh authoritative assignment, an explicitly enabled, clearly
labelled local fallback may run only timers, focus UI, reminders and `WOULD_BLOCK`
dry-run evaluation. It cannot change hosts, browser policy, processes or applications
because online Core, Session, lease and preauthorization are mandatory for a hard
action. It never extends stale NAS restrictions; NAS rest/release wins when authority
returns.

### Selected first-release friction and Recovery

The user selected F3: the existing 60-second typed phrase plus configured site/process
restriction. F3 remains inert unless the complete NAS guard matrix passes, never
delays Emergency, and cannot authorize Core state by typed text alone.

The user selected R1: release all restrictions synchronously and unconditionally,
even when Core/Session/lease freshness checks fail. If Core is reachable, best-effort
commit and schedule a 10-minute restorative break, then offer return/replan/end.
Replan still requires the dedicated user-presence intent. F1/F2/F4 and R2/R3 remain
documented alternatives. Emergency, real blocking, break denial and user-only replan
are never randomized.
