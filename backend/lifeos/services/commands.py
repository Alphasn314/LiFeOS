from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import Clock
from ..config import Settings
from ..errors import IdempotencyConflictError, LifeOSError, NotFoundError
from ..models import (
    CommandAckRow,
    CommandRow,
    DeviceRoleLeaseRow,
    DeviceRow,
    RuntimeStateHeadRow,
)
from ..schemas import (
    CommandAckIn,
    CommandAckRead,
    CommandPayload,
    CommandPollResponse,
    CommandRead,
    CommandType,
    CommitmentMode,
    DeviceRole,
    RoleLeaseRead,
)
from .audit import append_event


def command_read(row: CommandRow) -> CommandRead:
    return CommandRead(
        command_id=row.command_id,
        target_device_id=row.target_device_id,
        session_id=row.session_id,
        decision_id=row.decision_id,
        role_lease_id=row.role_lease_id,
        authorized_commitment_mode=CommitmentMode(row.authorized_commitment_mode),
        command_type=CommandType(row.command_type),
        risk_level=cast(Literal["SAFE", "HARD"], row.risk_level),
        issued_at=row.issued_at,
        not_before=row.not_before,
        expires_at=row.expires_at,
        required_state_version=row.required_state_version,
        idempotency_key=row.idempotency_key,
        payload=CommandPayload.model_validate(row.payload),
        dry_run=row.dry_run,
        reason_codes=row.reason_codes,
    )


def ack_read(row: CommandAckRow, *, duplicate: bool) -> CommandAckRead:
    return CommandAckRead(
        ack_id=row.ack_id,
        command_id=row.command_id,
        device_id=row.device_id,
        acknowledged_at=row.acknowledged_at,
        status=cast(
            Literal["ACCEPTED", "EXECUTED", "REJECTED", "FAILED", "EXPIRED"],
            row.status,
        ),
        observed_state_version=row.observed_state_version,
        idempotency_key=row.idempotency_key,
        details=row.details,
        reason_codes=row.reason_codes,
        duplicate=duplicate,
    )


class CommandService:
    def __init__(self, clock: Clock, settings: Settings) -> None:
        self.clock = clock
        self.settings = settings

    def poll(self, db: Session, device_id: UUID, *, limit: int = 20) -> CommandPollResponse:
        device = db.get(DeviceRow, device_id)
        if device is None:
            raise NotFoundError("Device", device_id)
        now = self.clock.now()
        rows = db.scalars(
            select(CommandRow)
            .where(
                CommandRow.target_device_id == device_id,
                CommandRow.status.in_(["PENDING", "DELIVERED"]),
                CommandRow.not_before <= now,
            )
            .order_by(CommandRow.issued_at, CommandRow.command_id)
            .limit(limit)
        ).all()
        state_head = db.scalar(
            select(RuntimeStateHeadRow).where(RuntimeStateHeadRow.device_id == device_id)
        )
        ready: list[CommandRead] = []
        for row in rows:
            rejection = self._rejection_reason(db, row, device, state_head, now)
            if rejection is not None:
                row.status = "EXPIRED" if rejection == "COMMAND_EXPIRED" else "REJECTED"
                self._audit_rejection(db, row, rejection, now)
                continue
            if now < row.not_before:
                continue
            row.status = "DELIVERED"
            row.updated_at = now
            ready.append(command_read(row))
        db.flush()
        leases = db.scalars(
            select(DeviceRoleLeaseRow).where(
                DeviceRoleLeaseRow.device_id == device_id,
                DeviceRoleLeaseRow.revoked_at.is_(None),
                DeviceRoleLeaseRow.expires_at > now,
            )
        ).all()
        return CommandPollResponse(
            commands=ready,
            latest_state_version=(state_head.state_version if state_head is not None else None),
            role_leases=[
                RoleLeaseRead(
                    lease_id=lease.lease_id,
                    device_id=lease.device_id,
                    role=DeviceRole(lease.role),
                    issued_at=lease.issued_at,
                    expires_at=lease.expires_at,
                    revoked_at=lease.revoked_at,
                    issued_for_state_version=lease.issued_for_state_version,
                    version=lease.version,
                    reason_codes=lease.reason_codes,
                )
                for lease in leases
            ],
        )

    def acknowledge(self, db: Session, payload: CommandAckIn) -> CommandAckRead:
        existing = db.scalar(
            select(CommandAckRow).where(CommandAckRow.idempotency_key == payload.idempotency_key)
        )
        if existing is not None:
            same = (
                existing.command_id == payload.command_id
                and existing.ack_id == payload.ack_id
                and existing.device_id == payload.device_id
                and existing.status == payload.status
                and existing.acknowledged_at == payload.acknowledged_at
                and existing.observed_state_version == payload.observed_state_version
                and existing.details == payload.details
                and existing.reason_codes == payload.reason_codes
            )
            if not same:
                raise IdempotencyConflictError(payload.idempotency_key)
            return ack_read(existing, duplicate=True)

        command = db.get(CommandRow, payload.command_id)
        if command is None:
            raise NotFoundError("Command", payload.command_id)
        if command.target_device_id != payload.device_id:
            raise LifeOSError(
                "TARGET_DEVICE_MISMATCH",
                "acknowledging device is not the command target",
                409,
                ["TARGET_DEVICE_MISMATCH"],
            )

        now = self.clock.now()
        recorded_status = payload.status
        reason_codes = list(payload.reason_codes)
        if command.command_type != "RELEASE_ALL" and payload.status in {
            "ACCEPTED",
            "EXECUTED",
        }:
            state_head = db.scalar(
                select(RuntimeStateHeadRow).where(
                    RuntimeStateHeadRow.device_id == payload.device_id
                )
            )
            if (
                state_head is None
                or payload.observed_state_version != command.required_state_version
                or state_head.state_version != command.required_state_version
            ):
                recorded_status = "REJECTED"
                reason_codes = ["STATE_VERSION_MISMATCH"]
            elif payload.acknowledged_at >= command.expires_at or now >= command.expires_at:
                recorded_status = "EXPIRED"
                reason_codes = ["COMMAND_EXPIRED"]

        row = CommandAckRow(
            ack_id=payload.ack_id,
            command_id=payload.command_id,
            device_id=payload.device_id,
            status=recorded_status,
            acknowledged_at=payload.acknowledged_at,
            idempotency_key=payload.idempotency_key,
            observed_state_version=payload.observed_state_version,
            details=payload.details,
            reason_codes=reason_codes,
        )
        db.add(row)
        if recorded_status in {"EXECUTED", "ACCEPTED"}:
            command.status = "ACKED"
        elif recorded_status == "EXPIRED":
            command.status = "EXPIRED"
        elif recorded_status in {"REJECTED", "FAILED"}:
            command.status = "REJECTED"
        command.updated_at = now
        db.flush()
        append_event(
            db,
            event_type="COMMAND.ACKNOWLEDGED",
            occurred_at=payload.acknowledged_at,
            received_at=now,
            source="windows-agent",
            entity_type="Command",
            entity_id=command.command_id,
            idempotency_key=f"audit:{payload.idempotency_key}",
            payload={
                "ack_id": str(row.ack_id),
                "status": recorded_status,
                "observed_state_version": payload.observed_state_version,
            },
            reason_codes=reason_codes,
        )
        return ack_read(row, duplicate=False)

    def _rejection_reason(
        self,
        db: Session,
        row: CommandRow,
        device: DeviceRow,
        state_head: RuntimeStateHeadRow | None,
        now: object,
    ) -> str | None:
        if now >= row.expires_at:  # type: ignore[operator]
            return "COMMAND_EXPIRED"
        if row.command_type == "RELEASE_ALL":
            return None
        if state_head is None or state_head.state_version != row.required_state_version:
            return "STATE_VERSION_MISMATCH"
        if row.risk_level != "HARD":
            return None
        if self.settings.dry_run or not self.settings.real_enforcement_enabled:
            return "DRY_RUN_REQUIRED"
        if not device.core_reachable or device.status != "ONLINE":
            return "CORE_UNREACHABLE"
        if row.role_lease_id is None:
            return "LEASE_REQUIRED"
        lease = db.get(DeviceRoleLeaseRow, row.role_lease_id)
        if (
            lease is None
            or lease.device_id != row.target_device_id
            or lease.role != "PRIMARY_ENFORCEMENT"
            or lease.revoked_at is not None
            or lease.expires_at <= now  # type: ignore[operator]
        ):
            return "LEASE_EXPIRED"
        return None

    def _audit_rejection(self, db: Session, row: CommandRow, reason: str, now: object) -> None:
        append_event(
            db,
            event_type="COMMAND.REJECTED",
            occurred_at=now,  # type: ignore[arg-type]
            received_at=now,  # type: ignore[arg-type]
            source="core",
            entity_type="Command",
            entity_id=row.command_id,
            idempotency_key=f"command:reject:{row.command_id}:{reason}",
            payload={"status": row.status, "required_state_version": row.required_state_version},
            reason_codes=[reason],
        )
