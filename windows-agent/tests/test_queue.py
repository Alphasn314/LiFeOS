from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from lifeos_windows_agent.queue import SQLiteAgentStore


def test_outbox_is_oldest_first_and_idempotent(tmp_path: Path, now) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteAgentStore(tmp_path / "agent.db")
    assert store.enqueue("observation", "sample-key-0001", {"value": 1}, now)
    assert not store.enqueue("observation", "sample-key-0001", {"value": 1}, now)
    assert store.enqueue("heartbeat", "sample-key-0002", {"value": 2}, now)

    assert [item.idempotency_key for item in store.due(now)] == [
        "sample-key-0001",
        "sample-key-0002",
    ]
    first = store.due(now)[0]
    store.mark_failed(first, now, "offline")
    assert [item.idempotency_key for item in store.due(now)] == ["sample-key-0002"]
    assert [item.idempotency_key for item in store.due(now + timedelta(seconds=1))] == [
        "sample-key-0001",
        "sample-key-0002",
    ]


def test_outbox_rejects_same_key_with_different_payload(tmp_path: Path, now) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteAgentStore(tmp_path / "agent.db")
    store.enqueue("observation", "sample-key-0001", {"value": 1}, now)
    with pytest.raises(ValueError, match="reused"):
        store.enqueue("observation", "sample-key-0001", {"value": 2}, now)


def test_outbox_and_state_survive_store_restart(tmp_path: Path, now) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "restart.db"
    first = SQLiteAgentStore(path)
    assert first.enqueue("observation", "restart-key-0001", {"value": 7}, now)
    first.set_latest_state_version(12)
    first.close()

    restarted = SQLiteAgentStore(path)
    try:
        due = restarted.due(now)
        assert [(item.idempotency_key, item.payload) for item in due] == [
            ("restart-key-0001", {"value": 7})
        ]
        assert restarted.latest_state_version() == 12
    finally:
        restarted.close()
