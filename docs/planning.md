# Deterministic planning and replanning

## Inputs and defaults

The planner receives a local date, timezone, tasks, fixed events, optional current
plan, current time, and availability changes. Defaults are:

| Parameter | Default |
|---|---:|
| focus_minutes | 50 |
| break_minutes | 10 |
| max_focus_minutes | 90 |
| buffer_ratio | 0.10 |
| freeze_horizon_minutes | 15 |
| replan_debounce_seconds | 120 |
| maximum_automatic_replans_per_hour | 3 |
| day window | 07:00-23:00 local |
| meal duration/windows | 30 min within 11:30-13:30 and 17:30-19:30 |

Day bounds represent the usable planning horizon; time outside is reserved for
sleep. Fixed events can narrow the horizon but cannot silently extend it. Travel
is explicitly supplied as `travel_before_minutes`/`travel_after_minutes` on a
fixed event. V1 does not infer travel from maps.

## Planning algorithm

1. Normalize local calendar input to UTC and reject overlapping HARD fixed events
   with a conflict.
2. Place HARD fixed events and their required travel.
3. Place the two required meal blocks in the earliest compatible point in their
   windows. If no point exists, report a required-constraint conflict.
4. Derive free intervals inside the day bounds.
5. Reserve ten percent of flexible time as buffer, rounded down to five minutes,
   placed at interval ends so it can absorb overrun.
6. Rank tasks lexicographically: overdue/hard-deadline first, mandatory first,
   larger deadline pressure first, higher priority first, earlier deadline, then
   UUID for stable ties. A task incompatible with the interval location/device is
   skipped and later reported if unscheduled.
7. Fill intervals with chunks no smaller than `minimum_chunk_minutes`, normally
   `focus_minutes` and never longer than `max_focus_minutes`.
8. Insert a break after each focus chunk unless a fixed/meal/buffer block already
   supplies at least the break duration.
9. Verify all HARD constraints, mandatory/deadline work, non-overlap, minimum chunk,
   and horizon bounds. Emit remaining work and conflicts.

`deadline_pressure = remaining_minutes / max(available_minutes_before_deadline, 1)`.
The plan can be returned with `PARTIAL` status for optional work left over,
including an optional remainder below its minimum chunk. It is `INFEASIBLE` if
any HARD, mandatory, deadline, meal, or travel constraint cannot be met, including
a minimum-chunk failure that prevents mandatory/deadline work from being placed.

## Replanning

Allowed triggers only:

`DAY_STARTED`, `USER_REQUESTED_REPLAN`, `TASK_COMPLETED_EARLY`, `TASK_OVERRUN`,
`BLOCK_MISSED`, `FIXED_EVENT_CHANGED`, `USER_REPORTED_FATIGUE`,
`USER_REPORTED_EMERGENCY`, `SESSION_ABORTED`, `AVAILABLE_TIME_CHANGED`.

For non-emergency replans, TASK/BREAK/BUFFER blocks whose start falls in
`[now, now + freeze_horizon)` are passed to the planner as frozen blocks. Emergency
replans freeze none. V1 does not yet detect every explicitly changed/now-impossible
frozen block, and it has no jitter cost for blocks outside the horizon; those are
recreated by the deterministic planner. Automatic triggers are debounced for 120
seconds and capped at three per rolling hour. User-requested and emergency replans
are audited but exempt from throttling. Every accepted attempt creates a new
immutable PlanVersion, including infeasible attempts.

## Conflict report

Each conflict has `code`, `severity`, affected task/event IDs, interval, required
minutes, available minutes, and human-readable detail. Codes include
`HARD_EVENT_OVERLAP`, `TRAVEL_OVERLAP`, `MEAL_UNPLACEABLE`,
`MANDATORY_WORK_UNSCHEDULED`, `DEADLINE_MISSED`, `MINIMUM_CHUNK_UNAVAILABLE`,
`LOCATION_MISMATCH`, and `DEVICE_MISMATCH`.

## Target self-evolving planning (V2 design)

Research, English and school use one planner with orthogonal task semantics rather
than one percent-complete model or separate planners:

| Dimension | Values |
|---|---|
| commitment | `FIXED`, `DEADLINE`, `FLEXIBLE` |
| progress | `MILESTONE`, `QUANTITY`, `DURATION` |
| uncertainty | `LOW`, `MEDIUM`, `HIGH` |
| interruptibility | `LOW`, `MEDIUM`, `HIGH` |
| cognitive demand | `DEEP`, `NORMAL`, `LIGHT` |
| dependencies | explicit predecessor/waiting/ready graph |
| learned duration | P50/P80, confidence and immutable model revision |
| experienced pressure | 0 effortless .. 4 extreme plus `UNKNOWN` |

No domain has a fixed daily minimum. A valid day may contain no research, English
or course work if that is the user's choice and hard facts allow it.

Research is milestone/dependency driven and exposes one executable action such as
read, implement, run, inspect, analyze, write or unblock. Repeated valid attempts
can be productive without visible progress. English is duration/quantity/repetition
accumulation; comprehension is optional noisy feedback, not completion. Classes and
exam sittings are fixed; assignments and exam preparation are deadline work.

### Next-day schedule advice

The user submits a complete time-to-task plan. The self-evolution module snapshots
the selected learning revision, predicts duration distribution and pressure,
checks hard facts/dependencies/total time, detects under-allocation or pressure
clustering, and returns the smallest explained `ScheduleAdvice`. It preserves both
the user's estimate and learned P50/P80. Advice may say the plan is reasonable and
never silently changes it. A user-authenticated `CREATE_DAILY_PLAN` or
`ACCEPT_SCHEDULE_ADVICE` may create the first authoritative plan for a day; neither
operation may replace an existing plan.

The duration model learns from completed active minutes, wall time, interruptions,
partial/censored Sessions and explicit progress/attempt feedback. It shrinks cold
starts through global -> domain -> action subtype -> task profiles and records
pre-update error. Experienced pressure is learned separately from objective
deadline pressure and affects ordering/recovery spacing, not moral priority.

The selected scheduling policy uses P80 for high-uncertainty research and P50 for
divisible low-pressure work, while displaying alternatives. Initial research
progress adapters cover experiment execution, code development, paper reading and
research writing; they record typed progress and meaningful attempts, not content.

### Severe-deviation recommendation; user-only replan

Core may project progress continuously but cannot automatically replan:

1. compare elapsed/progress evidence with the learned block distribution;
2. simulate recovery through permitted compression and whole flexible-block
   deferment/removal;
3. if the remainder is feasible, do not recommend replan;
4. if fixed/required conflicts remain or the explicit severe threshold is crossed,
   append a deduplicated `REPLAN_RECOMMENDED` explanation to Windows/iOS/Web;
5. only a user-authenticated `REQUEST_REPLAN` naming the current plan ID/revision
   invokes Planner to replace that immutable PlanVersion.

The V2 cutover is explicit: non-user `EventOrchestrator.ingest` triggers produce
status/recommendation only; the break endpoint records the break and release without
calling `PlanService.insert_break`; and `/api/v1/plans/generate` cannot replace an
existing plan or accept AI/service/sensor/device-only triggers. Each plan-creation or
revision command requires the separate one-time `HUMAN_INTENT` envelope defined in
ADR-0006; a device transport key alone is insufficient. AI, Windows background
services and iOS background work cannot submit replan on the user's behalf. An
infeasible remainder produces explicit conflicts/tradeoffs; it never fabricates
completion.
See ADR-0006 for estimator, advice, pressure and learning governance.
