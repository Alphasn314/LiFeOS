"""Small durable SQLite outbox and processed-command ledger."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .clock import as_utc_text
from .models import CommandAck


@dataclass(frozen=True, slots=True)
class OutboxItem:
    sequence: int
    message_type: str
    idempotency_key: str
    payload: dict[str, Any]
    attempts: int


class SQLiteAgentStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock, self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS outbox (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_type TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_outbox_available
                    ON outbox(available_at, sequence);
                CREATE TABLE IF NOT EXISTS processed_commands (
                    command_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    ack_json TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @staticmethod
    def _canonical_json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def enqueue(
        self,
        message_type: str,
        idempotency_key: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> bool:
        payload_json = self._canonical_json(payload)
        now_text = as_utc_text(now)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO outbox(
                    message_type, idempotency_key, payload_json, created_at, available_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (message_type, idempotency_key, payload_json, now_text, now_text),
            )
            if cursor.rowcount == 1:
                return True
            existing = self._connection.execute(
                "SELECT message_type, payload_json FROM outbox WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is None:
                return False
            if existing["message_type"] != message_type or existing["payload_json"] != payload_json:
                raise ValueError("local idempotency key was reused with a different payload")
            return False

    def due(self, now: datetime, limit: int = 100) -> list[OutboxItem]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT sequence, message_type, idempotency_key, payload_json, attempts
                FROM outbox
                WHERE available_at <= ?
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (as_utc_text(now), limit),
            ).fetchall()
        return [
            OutboxItem(
                sequence=int(row["sequence"]),
                message_type=str(row["message_type"]),
                idempotency_key=str(row["idempotency_key"]),
                payload=json.loads(str(row["payload_json"])),
                attempts=int(row["attempts"]),
            )
            for row in rows
        ]

    def mark_delivered(self, sequence: int) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM outbox WHERE sequence = ?", (sequence,))

    def mark_failed(self, item: OutboxItem, now: datetime, error: str) -> None:
        delay_seconds = min(300, 2 ** min(item.attempts, 8))
        available_at = as_utc_text(now + timedelta(seconds=delay_seconds))
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE outbox
                SET attempts = attempts + 1, available_at = ?, last_error = ?
                WHERE sequence = ?
                """,
                (available_at, error[:500], item.sequence),
            )

    def pending_count(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) AS count FROM outbox").fetchone()
        return int(row["count"])

    def processed_ack(self, command_id: str, idempotency_key: str) -> CommandAck | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT ack_json FROM processed_commands
                WHERE command_id = ? OR idempotency_key = ?
                LIMIT 1
                """,
                (command_id, idempotency_key),
            ).fetchone()
        return CommandAck.model_validate_json(str(row["ack_json"])) if row else None

    def record_processed(self, ack: CommandAck, command_idempotency_key: str) -> CommandAck:
        ack_json = ack.model_dump_json()
        with self._lock, self._connection:
            try:
                self._connection.execute(
                    """
                    INSERT INTO processed_commands(
                        command_id, idempotency_key, ack_json, processed_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        str(ack.command_id),
                        command_idempotency_key,
                        ack_json,
                        as_utc_text(ack.acknowledged_at),
                    ),
                )
            except sqlite3.IntegrityError:
                winner = self.processed_ack(str(ack.command_id), command_idempotency_key)
                if winner is None:
                    raise
                return winner
        return ack

    def set_latest_state_version(self, version: int) -> None:
        if version < 1:
            raise ValueError("state version must be positive")
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO agent_state(key, value) VALUES ('latest_state_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(version),),
            )

    def latest_state_version(self) -> int | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM agent_state WHERE key = 'latest_state_version'"
            ).fetchone()
        return int(row["value"]) if row else None
