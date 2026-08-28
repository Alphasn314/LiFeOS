# ADR-0001: SQLAlchemy 2 + Alembic + PostgreSQL

- Status: Accepted for V1 contract freeze
- Date: 2026-08-28

## Context

LifeOS needs explicit migrations, optimistic concurrency, JSON payloads, durable
transactions, unique idempotency constraints, and a PostgreSQL production path
while keeping local tests fast.

## Decision

Use synchronous SQLAlchemy 2 ORM, Alembic migrations, psycopg 3, and PostgreSQL 16.
FastAPI's database dependency uses one transaction per HTTP request; several
service operations may participate in that unit of work. Core SQLite is permitted
only for isolated/fast tests, while the Windows Agent intentionally uses its own
production SQLite store-and-forward queue. PostgreSQL integration remains a Core
acceptance gate.

## Consequences

The approach is mature and inspectable, and avoids framework lock-in. Synchronous
database calls cap per-process concurrency compared with async drivers, but V1 is
a single-user system and can scale with bounded worker threads. SQLite differences
mean constraints and migrations must also be tested against PostgreSQL. Migrating
to async SQLAlchemy later is localized to database/session and service boundaries,
but is not cost-free.
