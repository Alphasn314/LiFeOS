# Runtime and session state

RuntimeState is a product of independent axes, never one `WORKING` boolean.

- context: `FOCUS CLASS BREAK MEAL TRAVEL FREE SLEEP RECOVERY EMERGENCY UNPLANNED`
- presence: `PRESENT ABSENT UNKNOWN`
- engagement: `ON_TASK OFF_TASK IDLE UNKNOWN`
- session_state: `PLANNED DUE STARTING RUNNING PAUSED INTERRUPTED RECOVERY COMPLETED ABORTED MISSED`
- device_role: `PRIMARY_INTERACTION PRIMARY_ENFORCEMENT SENSOR NOTIFICATION_ONLY AI_WORKER STANDBY`

## Domain transition graph

```text
PLANNED -> DUE -> STARTING -> RUNNING -> COMPLETED
    |        |       |        |  \
    |        |       |        |   -> PAUSED -> RUNNING | INTERRUPTED | ABORTED
    |        |       |        -> INTERRUPTED -> RUNNING | RECOVERY | ABORTED
    |        |       |        -> RECOVERY -> RUNNING | INTERRUPTED | ABORTED
    |        |       -> ABORTED
    |        -> MISSED | ABORTED
    -> MISSED | ABORTED
```

Terminal states are `COMPLETED`, `ABORTED`, and `MISSED`. The pure transition
predicate implements the graph above. The V1 HTTP workflow exposes a smaller
operational subset: session creation starts directly in RUNNING; pause accepts
RUNNING/STARTING; resume accepts PAUSED/INTERRUPTED; complete accepts
RUNNING/PAUSED/INTERRUPTED; abort accepts PLANNED/DUE/STARTING/RUNNING/PAUSED/
INTERRUPTED. DUE, STARTING, MISSED, and RECOVERY are contract/domain states but do
not have autonomous schedulers in V1.

Emergency Release does not fabricate completion. When Core/database is reachable,
its transaction cancels the selected Session's pending enforcement before the
response, queues a five-minute `RELEASE_ALL`, changes that Session to
`INTERRUPTED` if it is non-terminal, and preserves it if terminal. Device-side
release is asynchronous.

## Observation reduction

Core derives a 60-second short window and 300-second medium window. A feature set
contains allowed/blocked app ratios, continuous foreground durations, latest idle
seconds, lock evidence, observation coverage, conflicts, and sensor freshness.

1. Locked means `presence=UNKNOWN`, `engagement=UNKNOWN`, and the derived
   RuntimeState's session axis is `INTERRUPTED`; V1 cannot prove physical absence.
2. Manual presence can set PRESENT/ABSENT for its validity window. ABSENT lasting
   90 seconds interrupts the session.
3. Insufficient coverage, conflicting sensors, initial zero-coverage session
   state, sensor failure, or confidence below 0.65 yields UNKNOWN. V1 has no
   separate persisted device-startup age feature.
4. Idle beyond the task profile tolerance yields IDLE unless lock/unknown wins.
5. OFF_TASK candidate: blocked foreground for 30 seconds or blocked ratio >=0.60.
6. ON_TASK candidate: allowed ratio >=0.75.
7. OFF_TASK is entered after two consecutive 60-second candidate estimates, or a
   blocked app is continuously foreground for 90 seconds.
8. OFF_TASK exits after an allowed app is continuously foreground for 30 seconds.

Precedence is safety/uncertainty -> interruption -> idle -> hysteresis engagement.
Each stored estimate increments `state_version` atomically.
When an observation belongs to a non-terminal session, an INTERRUPTED estimate is
also synchronized to the authoritative ExecutionSession row in the same ingest
transaction. Terminal Session rows are preserved.
