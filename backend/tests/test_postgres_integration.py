from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from lifeos.api import create_app
from lifeos.clock import FixedClock
from lifeos.config import Settings
from lifeos.db import Database

REQUIRED_TABLES = {
    "ai_jobs",
    "command_acks",
    "commands",
    "daily_summaries",
    "device_role_leases",
    "devices",
    "event_ledger",
    "execution_sessions",
    "feature_snapshots",
    "fixed_events",
    "observations",
    "outbox",
    "plan_heads",
    "plan_versions",
    "policy_decisions",
    "runtime_state_heads",
    "runtime_states",
    "schedule_blocks",
    "tasks",
}


def test_online_postgresql_migration_and_restart_smoke() -> None:
    database_url = os.environ.get("LIFEOS_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("set LIFEOS_TEST_POSTGRES_URL to run the online PostgreSQL gate")

    settings = Settings(
        database_url=database_url,
        dev_auth_token="postgres-test-token",
        dry_run=True,
        real_enforcement_enabled=False,
    )
    headers = {"Authorization": "Bearer postgres-test-token"}
    clock = FixedClock(datetime(2026, 8, 28, 23, 0, tzinfo=UTC))
    database = Database(database_url)
    assert database.engine.dialect.name == "postgresql"
    assert set(inspect(database.engine).get_table_names()) >= REQUIRED_TABLES
    with database.engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0001_core_schema"
        )

    task_title = f"PostgreSQL restart smoke {uuid4()}"
    event_id = uuid4()
    event_body = {
        "event_id": str(event_id),
        "event_type": "VALIDATION.POSTGRES_SMOKE",
        "occurred_at": clock.now().isoformat(),
        "source": "postgres-integration-test",
        "entity_type": "ValidationRun",
        "entity_id": str(uuid4()),
        "idempotency_key": f"postgres-smoke:{event_id}",
        "payload": {"phase": "before-restart"},
        "reason_codes": ["POSTGRES_ONLINE_VALIDATION"],
    }
    client = TestClient(create_app(settings=settings, database=database, clock=clock))
    created = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": task_title, "estimated_minutes": 25},
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["task_id"]
    accepted = client.post("/api/v1/events", headers=headers, json=event_body)
    assert accepted.status_code == 202
    client.close()
    database.dispose()

    restarted_database = Database(database_url)
    restarted_client = TestClient(
        create_app(settings=settings, database=restarted_database, clock=clock)
    )
    try:
        recovered = restarted_client.get(f"/api/v1/tasks/{task_id}", headers=headers)
        assert recovered.status_code == 200
        assert recovered.json()["title"] == task_title
        replay = restarted_client.post("/api/v1/events", headers=headers, json=event_body)
        assert replay.status_code == 202
        assert replay.json()["duplicate"] is True
    finally:
        restarted_client.close()
        restarted_database.dispose()
