# LifeOS V1 architecture

## Decision summary

LifeOS V1 is a monorepo and a modular monolith. The Core HTTP process owns the
authoritative PostgreSQL state and calls in-process planning, runtime-reduction,
policy, command, and AI-provider ports. PostgreSQL tables plus an outbox replace an
external message bus. A TypeScript PWA and a Python Windows Agent are clients of
the Core; neither is authoritative.

```text
Web PWA ───────┐
               v
Windows Agent -> FastAPI Core -> PostgreSQL
                    |  |  |
                    |  |  +-> outbox / command queue
                    |  +----> event orchestrator + deterministic planner
                    |         + state reducer + policy guard
                    +-------> AI Provider interface (Mock in V1, optional)
```

## Technology

- Python 3.12, FastAPI, Pydantic v2
- SQLAlchemy 2.0 and Alembic; psycopg 3 for PostgreSQL
- PostgreSQL 16 in Docker Compose
- TypeScript 5 and Vite, shipped as an installable PWA
- Python Windows Agent using `ctypes` behind a capability adapter, `httpx`, and a
  local SQLite store-and-forward queue
- pytest, Ruff, MyPy, Vitest

SQLAlchemy/Alembic was selected because it gives explicit migrations, mature
PostgreSQL support, portable SQLite test execution, and optimistic concurrency
without a framework-specific persistence layer. See ADR-0001.

## Module boundaries

- API validates transport contracts and calls application services. FastAPI's
  database dependency provides the per-request commit/rollback unit of work.
- Application services own idempotency and orchestration and use SQLAlchemy ORM
  directly; V1 does not add a separate repository abstraction.
- The event orchestrator recognizes only the frozen `PlanTrigger` allowlist. It
  appends an external event and creates its PlanVersion in one transaction;
  duplicate envelopes recover the original side-effect IDs by causation link.
- ORM models own persistence shape, not planner/runtime/policy decisions.
- Planning produces immutable `PlanVersion` aggregates and infeasibility reports.
- Runtime converts Observation -> FeatureSet -> RuntimeState.
- Policy converts RuntimeState -> PolicyDecision -> guarded Command.
- V1 Command Guard validates TTL/state/target for ordinary commands and keeps real
  enforcement disabled. Its partial hard-row checks are not a complete V2
  authorization guard; active session/preauthorization/blocklist/duration and
  lease-state checks remain required before any real enforcement.
- AI is an optional provider returning schema-validated data. Provider failure
  fails closed and leaves deterministic Core behavior/current plans unaffected.

## Availability and recovery

The Windows Agent persists unsent observations and acknowledgements locally,
preserves their original idempotency keys, and retries oldest-first. It has no
offline command inbox and cannot obtain or execute a new action while Core is
unavailable. On restart, Core reads persisted heads and rows from PostgreSQL;
command polling revalidates TTL/state instead of relying on a startup sweep. Earlier
plan versions are never overwritten.

The Agent derives a stable local device UUID, enrolls it idempotently, and asks
Core for the device's active non-terminal session before each activity sample. A
200 response updates the assignment, an authoritative 204 clears it, and a network
failure preserves the last assignment so queued observations retain their
original context. Neither enrollment nor the cached assignment makes the Agent
authoritative.

## Dependency order

Contracts -> persistence/migrations -> application services -> planner/runtime ->
policy/commands -> API -> Windows Agent/Web -> scenario and failure tests.

## Explicit V1 exclusions

No camera, native iOS, real phone calls, NAS hardware integration, Codex runtime,
vector database, real process termination, registry/firewall modification, or
permanent/autostart installation is present.

## Deliberate V1 workflow boundary

The external `POST /api/v1/events` trigger path and the session-break endpoint
perform replanning atomically. Direct Task/FixedEvent CRUD and every session
transition do not yet all synthesize trigger envelopes automatically. Integrators
must explicitly submit the corresponding frozen event or call plan generation.
Progress accounting from a completed session into `Task.remaining_minutes` is
also an explicit product decision, not an inferred side effect in V1.
