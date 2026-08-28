from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lifeos.api import create_app
from lifeos.clock import FixedClock
from lifeos.config import Settings
from lifeos.db import Database


@dataclass
class ApiHarness:
    database: Database
    database_url: str
    clock: FixedClock
    client: TestClient
    headers: dict[str, str]
    settings: Settings


@pytest.fixture
def api_harness(tmp_path: Path) -> ApiHarness:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'lifeos-test.db').as_posix()}"
    database = Database(database_url)
    database.create_schema()
    clock = FixedClock(datetime(2026, 8, 28, 23, 0, tzinfo=UTC))
    settings = Settings(
        database_url=database_url,
        dev_auth_token="test-token",
        dry_run=True,
        real_enforcement_enabled=False,
    )
    client = TestClient(create_app(settings=settings, database=database, clock=clock))
    harness = ApiHarness(
        database=database,
        database_url=database_url,
        clock=clock,
        client=client,
        headers={"Authorization": "Bearer test-token"},
        settings=settings,
    )
    yield harness
    client.close()
    database.dispose()
