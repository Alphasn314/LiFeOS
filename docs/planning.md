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

## Target life-domain semantics (V2 design)

Research, English, and school should not use one percent-complete model or three
separate planners. Describe work with orthogonal semantics:

| Dimension | Values |
|---|---|
| commitment | `FIXED`, `DEADLINE`, `FLEXIBLE` |
| progress | `MILESTONE`, `QUANTITY`, `DURATION` |
| uncertainty | `LOW`, `MEDIUM`, `HIGH` |
| interruptibility | `LOW`, `MEDIUM`, `HIGH` |
| cognitive demand | `DEEP`, `NORMAL`, `LIGHT` |
| minimum viable dose | optional bounded unit |
| dependencies | explicit predecessor/waiting/ready graph |

Research is normally milestone/dependency driven, high-uncertainty, and deep. A
broad milestone must expose one executable next action: read, implement, run,
inspect, analyze, write, or unblock. A running remote experiment may wait while
another ready analysis/writing action is scheduled.

English is accumulation driven. Completion is the configured duration, quantity,
or repetition dose. A comprehension report is a noisy optional outcome used to
select future modality; it does not retroactively fail completed practice.

Classes and exam sittings are fixed events. Assignments and exam preparation are
deadline work. Travel, preparation, and submission are explicit instead of hidden
scheduling costs.

### Anti-collapse replan

Replanning is a primary loop. Starting from Core `now`, preserve completed history,
hard course/travel/meal/recovery facts, and still-valid near-term blocks; release
flexible blocks made impossible by a changed hard fact with an audit reason. Select
only dependency-ready work, match cognitive demand to explicit capacity, and keep a
small stability cost for valid old blocks.

Try the full feasible remainder first. If it is impossible, return an auditable
`PARTIAL` minimum viable day rather than abandon the day: protected course
commitments, essential meal/travel/recovery, mandatory deadline work, configured
minimum English dose, then one ready research progress/unblock action where
capacity remains. If even required work is infeasible, expose explicit tradeoffs;
never mark an impossible plan feasible or fabricate completion.

These semantics require a later contract ADR, migration, and contract tests before
implementation. ADR-0005 defines the target and N-of-1 personalization.
