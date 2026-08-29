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

## Target complete intervention loop (V2 design)

Intervention purpose and intensity are separate. Purpose is return, clarify next
action, break, replan, recover, or end. The existing levels remain the compatible
intensity axis: 0 observe, 1 ambient cue, 2 explicit choice, 3 pre-authorized
friction (`WOULD_BLOCK` in V1), 4 bounded recovery, and 5 interrupt/replan.
Emergency Release is out-of-band at every level.

Each decision must:

1. verify authoritative Session/target, state version, freshness, confidence,
   sensor health, interaction availability, and global prompt budget;
2. distinguish aligned involuntary diversion, deliberate goal change, and a
   blocked/unclear/resource-limited next action;
3. choose purpose before intensity;
4. cap intensity by immutable commitment mode and complete authorization;
5. de-escalate for low energy, high demand, unpleasant valence, physical limits,
   uncertainty, recent response, `DO_NOT_INTERRUPT`, cooldown, and burden;
6. apply hysteresis and deduplicate Windows/iOS prompts at NAS;
7. emit one typed, expiring, idempotent command or replan event;
8. record delivery, display, user choice, execution, Session change, and usefulness
   as distinct outcomes;
9. re-evaluate benefit before repeating.

No new human-state dimension may be combined with `max()` to raise force.
Nonresponse is not consent, absence, refusal, or defiance. Objective urgency cannot
override DND/capacity guards. A suggested initial budget is one spontaneous
check-in per 30 minutes, two proactive prompts per Session, and four per day across
clients, with none in CLASS/TRAVEL/SLEEP/EMERGENCY or explicit
`DO_NOT_INTERRUPT`.

Constrained SSH transports typed user intent and command results; it does not
transport client-selected shell commands. Windows retains the only future desktop
adapter and must have a local offline Emergency UI before any real restriction.
iOS offline Emergency remains visibly **NOT DELIVERED** until Core commits.
Experiments may compare safe wording/timing/branch choices, but never Emergency,
override, denial of a requested break, or real enforcement.
