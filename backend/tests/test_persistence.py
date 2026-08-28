from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.schema import CreateTable

from lifeos.config import Settings
from lifeos.db import Database, create_db
from lifeos.models import (
    AIJobRow,
    Base,
    CommandRow,
    DeviceRow,
    EventLedgerRow,
    ExecutionSessionRow,
    ObservationRow,
    PlanVersionRow,
    PolicyDecisionRow,
    RuntimeStateRow,
    ScheduleBlockRow,
    TaskRow,
)

EXPECTED_TABLES = {
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


@pytest.fixture
def database() -> Database:
    db = Database("sqlite+pysqlite:///:memory:")
    db.create_schema()
    try:
        yield db
    finally:
        db.dispose()


def _task(title: str = "Research") -> TaskRow:
    return TaskRow(
        title=title,
        status="READY",
        priority=5,
        mandatory=True,
        estimated_minutes=50,
        remaining_minutes=50,
        minimum_chunk_minutes=25,
        activity_profile="CODING",
        required_device_capabilities=["foreground_process"],
        allowed_apps=["code.exe"],
        blocked_apps=["cs2.exe"],
    )


def _seed_policy_graph(
    database: Database,
) -> tuple[DeviceRow, ExecutionSessionRow, PolicyDecisionRow]:
    now = datetime.now(UTC)
    with database.session() as session:
        device = DeviceRow(
            name="Windows workstation",
            device_type="WINDOWS",
            capabilities=["foreground_process", "idle_seconds"],
            status="ONLINE",
        )
        task = _task()
        plan = PlanVersionRow(
            plan_date=date.today(),
            display_timezone="Asia/Shanghai",
            revision=1,
            trigger="DAY_STARTED",
            status="FEASIBLE",
            algorithm_version="deterministic-v1",
            parameters={"focus_minutes": 50},
            conflicts=[],
            reason_codes=["DAY_STARTED", "PLAN_FEASIBLE"],
        )
        session.add_all([device, task, plan])
        session.flush()
        block = ScheduleBlockRow(
            plan_version_id=plan.plan_version_id,
            kind="TASK",
            title=task.title,
            start_at=now,
            end_at=now + timedelta(minutes=50),
            task_id=task.task_id,
            hardness="REQUIRED",
            activity_profile="CODING",
            allowed_apps=["code.exe"],
            blocked_apps=["cs2.exe"],
            reason_codes=["TASK_PRIORITY_ORDER"],
        )
        session.add(block)
        session.flush()
        execution = ExecutionSessionRow(
            plan_version_id=plan.plan_version_id,
            block_id=block.block_id,
            task_id=task.task_id,
            device_id=device.device_id,
            commitment_mode="ADVISORY",
            session_state="RUNNING",
            scheduled_start_at=now,
            scheduled_end_at=now + timedelta(minutes=50),
            dry_run=True,
            reason_codes=["SESSION_STARTED"],
        )
        session.add(execution)
        session.flush()
        state = RuntimeStateRow(
            device_id=device.device_id,
            session_id=execution.session_id,
            estimated_at=now,
            context="FOCUS",
            presence="PRESENT",
            engagement="OFF_TASK",
            session_state="RUNNING",
            device_role="PRIMARY_INTERACTION",
            confidence=0.9,
            reason_codes=["BLOCKED_APP_THRESHOLD"],
            valid_until=now + timedelta(seconds=30),
            state_version=1,
            features={"blocked_app_ratio_60s": 0.8},
        )
        session.add(state)
        session.flush()
        decision = PolicyDecisionRow(
            session_id=execution.session_id,
            state_id=state.state_id,
            state_version=1,
            commitment_mode="ADVISORY",
            intervention_level=1,
            action="SHOW_NOTIFICATION",
            risk_level="SAFE",
            dry_run=True,
            expires_at=now + timedelta(minutes=1),
            idempotency_key="decision-state-1-level-1",
            reason_codes=["OFF_TASK_LEVEL_1"],
        )
        session.add(decision)

    return device, execution, decision


def test_complete_v1_metadata_and_safe_settings(database: Database) -> None:
    assert set(inspect(database.engine).get_table_names()) == EXPECTED_TABLES
    settings = Settings(_env_file=None)
    assert settings.dry_run is True
    assert settings.real_enforcement_enabled is False
    assert settings.display_timezone == "Asia/Shanghai"
    assert create_db("sqlite+pysqlite:///:memory:").engine.dialect.name == "sqlite"


def test_uuid_json_utc_and_transaction_rollback(database: Database) -> None:
    deadline = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    with database.session() as session:
        task = _task()
        task.deadline = deadline
        session.add(task)

    with database.session() as session:
        stored = session.get(TaskRow, task.task_id)
        assert stored is not None
        assert stored.task_id.version == 4
        assert stored.allowed_apps == ["code.exe"]
        assert stored.deadline == deadline
        assert stored.deadline.tzinfo is UTC

    with pytest.raises(RuntimeError, match="rollback sentinel"):
        with database.session() as session:
            session.add(_task("Must roll back"))
            raise RuntimeError("rollback sentinel")

    with database.session() as session:
        assert session.query(TaskRow).filter_by(title="Must roll back").count() == 0


def test_naive_timestamp_is_rejected(database: Database) -> None:
    with pytest.raises(StatementError, match="timezone-aware"):
        with database.session() as session:
            task = _task()
            task.deadline = datetime(2026, 8, 29, 12, 0)
            session.add(task)


def test_optimistic_concurrency_detects_stale_update(database: Database) -> None:
    with database.session() as session:
        task = _task()
        session.add(task)
    task_id = task.task_id

    left = database.session_factory()
    right = database.session_factory()
    try:
        left_task = left.get(TaskRow, task_id)
        right_task = right.get(TaskRow, task_id)
        assert left_task is not None and right_task is not None

        left_task.remaining_minutes = 25
        left.commit()
        assert left_task.version == 2

        right_task.remaining_minutes = 10
        with pytest.raises(StaleDataError):
            right.commit()
        right.rollback()
    finally:
        left.close()
        right.close()


def test_external_idempotency_keys_are_unique(database: Database) -> None:
    now = datetime.now(UTC)
    with database.session() as session:
        device = DeviceRow(name="Agent", device_type="WINDOWS")
        session.add(device)
    device_id = device.device_id

    with database.session() as session:
        session.add(
            ObservationRow(
                device_id=device_id,
                kind="ACTIVITY_SAMPLE",
                observed_at=now,
                idempotency_key="observation-replay-key",
                payload={"foreground_process": "code.exe"},
                reason_codes=["SENSOR_SAMPLE"],
            )
        )

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                ObservationRow(
                    device_id=device_id,
                    kind="ACTIVITY_SAMPLE",
                    observed_at=now,
                    idempotency_key="observation-replay-key",
                    payload={"foreground_process": "cs2.exe"},
                    reason_codes=["SENSOR_SAMPLE"],
                )
            )

    event_key = "event-replay-key"
    entity_id = uuid4()
    with database.session() as session:
        session.add(
            EventLedgerRow(
                event_type="TASK.CREATED",
                occurred_at=now,
                source="core",
                entity_type="Task",
                entity_id=entity_id,
                idempotency_key=event_key,
                payload={},
                reason_codes=["TASK_CREATED"],
            )
        )
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                EventLedgerRow(
                    event_type="TASK.CREATED",
                    occurred_at=now,
                    source="core",
                    entity_type="Task",
                    entity_id=entity_id,
                    idempotency_key=event_key,
                    payload={},
                    reason_codes=["TASK_CREATED"],
                )
            )


def test_command_window_and_hard_authority_are_database_invariants(database: Database) -> None:
    device, execution, decision = _seed_policy_graph(database)
    now = datetime.now(UTC)
    with database.session() as session:
        safe = CommandRow(
            target_device_id=device.device_id,
            session_id=execution.session_id,
            decision_id=decision.decision_id,
            authorized_commitment_mode="ADVISORY",
            command_type="SHOW_NOTIFICATION",
            risk_level="SAFE",
            issued_at=now,
            not_before=now,
            expires_at=now + timedelta(minutes=1),
            required_state_version=1,
            idempotency_key="safe-command-state-1",
            payload={"message": "Return to task"},
            reason_codes=["OFF_TASK_LEVEL_1"],
        )
        session.add(safe)
    assert safe.dry_run is True

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                CommandRow(
                    target_device_id=device.device_id,
                    session_id=execution.session_id,
                    decision_id=decision.decision_id,
                    authorized_commitment_mode="STANDARD",
                    command_type="START_BLOCK",
                    risk_level="HARD",
                    role_lease_id=None,
                    issued_at=now,
                    not_before=now,
                    expires_at=now + timedelta(minutes=10),
                    required_state_version=1,
                    idempotency_key="hard-command-no-lease",
                    payload={"duration_seconds": 600},
                    dry_run=True,
                    reason_codes=["LEASE_REQUIRED"],
                )
            )

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                CommandRow(
                    target_device_id=device.device_id,
                    session_id=execution.session_id,
                    decision_id=decision.decision_id,
                    authorized_commitment_mode="ADVISORY",
                    command_type="SHOW_NOTIFICATION",
                    risk_level="SAFE",
                    issued_at=now,
                    not_before=now,
                    expires_at=now,
                    required_state_version=1,
                    idempotency_key="expired-at-issue-command",
                    payload={},
                    reason_codes=["INVALID_COMMAND_WINDOW"],
                )
            )


def test_ai_jobs_are_occ_protected(database: Database) -> None:
    with database.session() as session:
        job = AIJobRow(
            provider="mock",
            job_type="PLANNING",
            request_payload={"message_type": "AI_PLANNING_REQUEST"},
            idempotency_key="ai-job-request-key",
        )
        session.add(job)
    with database.session() as session:
        stored = session.get(AIJobRow, job.job_id)
        assert stored is not None
        stored.status = "RUNNING"
    assert stored.version == 2


def test_initial_migration_round_trip_matches_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.sqlite"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")
    migrated = Database(f"sqlite+pysqlite:///{database_path.as_posix()}")
    try:
        assert set(inspect(migrated.engine).get_table_names()) == {
            *EXPECTED_TABLES,
            "alembic_version",
        }
        with migrated.engine.connect() as connection:
            differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert differences == []
    finally:
        migrated.dispose()

    command.downgrade(config, "base")
    downgraded = Database(f"sqlite+pysqlite:///{database_path.as_posix()}")
    try:
        assert not (set(inspect(downgraded.engine).get_table_names()) & EXPECTED_TABLES)
    finally:
        downgraded.dispose()


def test_schema_compiles_for_postgresql() -> None:
    dialect = postgresql.dialect()
    rendered = "\n".join(
        str(CreateTable(table).compile(dialect=dialect)) for table in Base.metadata.sorted_tables
    )
    assert "UUID" in rendered
    assert "TIMESTAMP WITH TIME ZONE" in rendered
