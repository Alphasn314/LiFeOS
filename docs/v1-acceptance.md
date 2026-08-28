# V1 acceptance gates

No item is complete without a passing recorded test or a clearly identified manual
check. The authoritative executable mapping is the concrete test file or check in
the Evidence column below; V1 does not use a separate `tests/acceptance/` folder.

| ID | Gate | Evidence |
|---|---|---|
| V1-01 | migrations create every required entity in PostgreSQL | `backend/tests/test_postgres_integration.py`; Alembic online upgrade and table inspection |
| V1-02 | Task and FixedEvent CRUD, UTC conversion, optimistic concurrency | `backend/tests/test_api_services.py`, `test_persistence.py` |
| V1-03 | schemas reject missing IDs, reason codes, TTL/state binding | `backend/tests/test_contracts.py` positive and negative matrix |
| V1-04 | three fixed classes + English/Research generate a non-overlapping plan | `backend/tests/test_planning.py`, `test_v1_scenario.py` |
| V1-05 | simulated late start creates a new revision and preserves old plan | `backend/tests/test_v1_scenario.py` |
| V1-06 | infeasible hard constraints produce structured conflicts | `backend/tests/test_planning.py` |
| V1-07 | session starts with immutable commitment/dry-run authority | `backend/tests/test_v1_scenario.py`, `test_api_services.py` |
| V1-08 | cs2 observations satisfy hysteresis and become OFF_TASK | `backend/tests/test_runtime.py`, `test_v1_scenario.py` |
| V1-09 | policy emits reminder, prompt, and audited WOULD_BLOCK only | `backend/tests/test_policy.py`, `test_v1_scenario.py` |
| V1-10 | 10-minute break can be inserted and triggers replan | `backend/tests/test_v1_scenario.py` |
| V1-11 | heartbeat online/offline threshold, ordering, and idempotency | `backend/tests/test_api_services.py` |
| V1-12 | expired/stale commands reject; sequential duplicates return cached/existing outcomes | `backend/tests/test_command_safety.py`, Agent command tests |
| V1-13 | reachable Core transaction cancels enforcement and queues release before response; device execution is asynchronous | `backend/tests/test_command_safety.py`, `test_v1_scenario.py` |
| V1-14 | restart preserves current plan/session/events and does not replay action | named scenario restart plus online PostgreSQL process-restart smoke |
| V1-15 | AI offline/invalid job fails closed; deterministic planner/current plan are unaffected | `backend/tests/test_ai_context.py`, `test_v1_scenario.py` |
| V1-16 | sequential duplicate external event has one ledger row/side effect/outbox row | `backend/tests/test_api_services.py`, `test_v1_scenario.py` |
| V1-17 | Windows Agent collects only approved fields and queues offline | `windows-agent/tests/`, including SQLite reopen recovery |
| V1-18 | Web UI builds and exposes plan/task/session/emergency views | Vitest/build plus desktop/mobile browser smoke against a real Core |
| V1-19 | no camera/Codex/real blocking/autostart/system mutation path ships | limited Python-source token/import assertions in `backend/tests/test_v1_security_boundary.py`, Agent capability tests, and manual whole-tree review |

The full named scenario is one end-to-end scenario test function: seed three classes and the two tasks,
plan, arrive late, replan, start, submit timed `cs2.exe` evidence, observe OFF_TASK,
create notifications and WOULD_BLOCK, request a ten-minute break, restart Core,
disable AI, replay the triggering event, and assert immutable/audited/idempotent
state throughout.

## Recorded V1 validation (2026-08-28)

All gates above passed in the final local validation. The PostgreSQL online gate
used PostgreSQL 18.3 in an isolated user-space WSL cluster because the host Docker
daemon was unavailable. Docker Compose remains pinned to PostgreSQL 16; its
configuration rendered successfully, but container image build/start was not
executed on this host. This distinction is deployment evidence, not a claim that
the PostgreSQL 16 image was run.

The acceptance set proves the frozen V1 scenario and safety invariants. It does
not imply that every direct CRUD mutation automatically emits a replan trigger:
external trigger envelopes and the break workflow are orchestrated, while some
task/fixed-event/session workflows remain explicit API calls. Those boundaries
are catalogued in `LiFeOS_V1_REPORT.md` for product-level tuning.

The manual real-process Agent smoke covered enrollment, active assignment,
heartbeat, and observation against Core/PostgreSQL. Agent command escalation and
ACK were covered by the automated named scenario and Agent tests, not by that
manual smoke run.
