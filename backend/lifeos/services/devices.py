from __future__ import annotations

from datetime import timedelta
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import Clock
from ..errors import LifeOSError, NotFoundError
from ..models import DeviceRow
from ..schemas import DeviceRead, DeviceRegister, HeartbeatIn
from .audit import append_event


class DeviceService:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def register(self, db: Session, payload: DeviceRegister) -> DeviceRead:
        now = self.clock.now()
        row = DeviceRow(
            name=payload.name,
            device_type=payload.device_type,
            capabilities=sorted(set(payload.capabilities)),
            status="UNKNOWN",
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        append_event(
            db,
            event_type="DEVICE.REGISTERED",
            occurred_at=now,
            received_at=now,
            source="core",
            entity_type="Device",
            entity_id=row.device_id,
            idempotency_key=f"device:register:{row.device_id}",
            payload={"name": row.name, "device_type": row.device_type},
            reason_codes=["EVENT_ACCEPTED"],
        )
        return self._read(row)

    def enroll(self, db: Session, device_id: UUID, payload: DeviceRegister) -> DeviceRead:
        """Idempotently provision an Agent-owned stable device identifier."""

        existing = db.get(DeviceRow, device_id)
        if existing is not None:
            if existing.device_type != payload.device_type:
                raise LifeOSError(
                    "DEVICE_ID_CONFLICT",
                    "the stable device identifier is already enrolled with another type",
                    409,
                    ["DEVICE_ID_CONFLICT"],
                )
            return self._read(existing)

        now = self.clock.now()
        row = DeviceRow(
            device_id=device_id,
            name=payload.name,
            device_type=payload.device_type,
            capabilities=sorted(set(payload.capabilities)),
            status="UNKNOWN",
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        append_event(
            db,
            event_type="DEVICE.ENROLLED",
            occurred_at=now,
            received_at=now,
            source="windows-agent",
            entity_type="Device",
            entity_id=row.device_id,
            idempotency_key=f"device:enroll:{row.device_id}",
            payload={"name": row.name, "device_type": row.device_type},
            reason_codes=["DEVICE_ENROLLED"],
        )
        return self._read(row)

    def get_row(self, db: Session, device_id: UUID) -> DeviceRow:
        row = db.get(DeviceRow, device_id)
        if row is None:
            raise NotFoundError("Device", device_id)
        return row

    def heartbeat(self, db: Session, payload: HeartbeatIn) -> DeviceRead:
        row = self.get_row(db, payload.device_id)
        received_at = self.clock.now()
        if payload.observed_at > received_at + timedelta(minutes=5):
            raise LifeOSError(
                "HEARTBEAT_FROM_FUTURE",
                "heartbeat clock is more than five minutes ahead of Core",
                422,
                ["HEARTBEAT_FROM_FUTURE"],
            )
        _, created = append_event(
            db,
            event_type="DEVICE.HEARTBEAT",
            event_id=payload.heartbeat_id,
            occurred_at=payload.observed_at,
            received_at=received_at,
            source="windows-agent",
            entity_type="Device",
            entity_id=row.device_id,
            idempotency_key=payload.idempotency_key,
            payload=payload.model_dump(
                mode="json", exclude={"heartbeat_id", "idempotency_key", "reason_codes"}
            ),
            reason_codes=payload.reason_codes,
        )
        if created and (
            row.last_heartbeat_at is None or payload.observed_at >= row.last_heartbeat_at
        ):
            row.last_heartbeat_at = payload.observed_at
            row.agent_version = payload.agent_version
            row.capabilities = sorted(set(payload.capabilities))
            row.latest_state_version = payload.latest_state_version
            row.core_reachable = payload.core_reachable
            row.status = "ONLINE" if payload.core_reachable else "DEGRADED"
            row.updated_at = received_at
            db.flush()
        return self._read(row)

    def get(self, db: Session, device_id: UUID) -> DeviceRead:
        return self._read(self.get_row(db, device_id))

    def list(self, db: Session) -> list[DeviceRead]:
        return [self._read(row) for row in db.scalars(select(DeviceRow)).all()]

    def mark_stale_offline(self, db: Session) -> int:
        cutoff = self.clock.now() - timedelta(seconds=45)
        rows = db.scalars(
            select(DeviceRow).where(
                DeviceRow.last_heartbeat_at.is_not(None),
                DeviceRow.last_heartbeat_at <= cutoff,
                DeviceRow.status != "OFFLINE",
            )
        ).all()
        for row in rows:
            row.status = "OFFLINE"
            row.updated_at = self.clock.now()
        db.flush()
        return len(rows)

    def _read(self, row: DeviceRow) -> DeviceRead:
        status = row.status
        if row.last_heartbeat_at is not None:
            if self.clock.now() - row.last_heartbeat_at >= timedelta(seconds=45):
                status = "OFFLINE"
            elif status == "DEGRADED":
                status = "OFFLINE"
        if status not in {"ONLINE", "OFFLINE", "UNKNOWN"}:
            status = "UNKNOWN"
        return DeviceRead(
            device_id=row.device_id,
            name=row.name,
            device_type=cast(Literal["WINDOWS", "WEB", "MOBILE", "SERVER"], row.device_type),
            capabilities=row.capabilities,
            status=cast(Literal["ONLINE", "OFFLINE", "UNKNOWN"], status),
            last_heartbeat_at=row.last_heartbeat_at,
            version=row.version,
        )
