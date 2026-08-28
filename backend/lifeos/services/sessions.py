from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import Clock
from ..config import Settings
from ..errors import LifeOSError, NotFoundError, VersionConflictError
from ..models import (
    CommandRow,
    DeviceRow,
    EventLedgerRow,
    ExecutionSessionRow,
    PlanHeadRow,
    PlanVersionRow,
    PolicyDecisionRow,
    RuntimeStateHeadRow,
    RuntimeStateRow,
    ScheduleBlockRow,
)
from ..schemas import (
    BreakRequest,
    CommitmentMode,
    EmergencyReleaseRequest,
    ExecutionSessionRead,
    OverrideRequest,
    SessionAction,
    SessionStart,
    SessionState,
)
from .audit import append_event

TERMINAL_STATES = {"COMPLETED", "ABORTED", "MISSED"}


def session_read(row: ExecutionSessionRow) -> ExecutionSessionRead:
    return ExecutionSessionRead(
        session_id=row.session_id,
        plan_version_id=row.plan_version_id,
        block_id=row.block_id,
        task_id=row.task_id,
        device_id=row.device_id,
        commitment_mode=CommitmentMode(row.commitment_mode),
        session_state=SessionState(row.session_state),
        scheduled_start_at=row.scheduled_start_at,
        scheduled_end_at=row.scheduled_end_at,
        started_at=row.actual_start_at,
        ended_at=row.actual_end_at,
        dry_run=row.dry_run,
        intervention_level=row.intervention_level,
        emergency_released_at=row.emergency_released_at,
        override_reason=row.override_reason,
        version=row.version,
        reason_codes=row.reason_codes,
    )


class SessionService:
    def __init__(self, clock: Clock, settings: Settings) -> None:
        self.clock = clock
        self.settings = settings

    def start(self, db: Session, payload: SessionStart) -> ExecutionSessionRead:
        block = db.get(ScheduleBlockRow, payload.block_id)
        if block is None:
            raise NotFoundError("ScheduleBlock", payload.block_id)
        plan = db.get(PlanVersionRow, block.plan_version_id)
        if plan is None:
            raise NotFoundError("PlanVersion", block.plan_version_id)
        head = db.scalar(
            select(PlanHeadRow).where(
                PlanHeadRow.plan_date == plan.plan_date,
                PlanHeadRow.display_timezone == plan.display_timezone,
            )
        )
        if (
            head is None
            or head.revision != payload.expected_plan_revision
            or head.current_plan_version_id != plan.plan_version_id
        ):
            actual = head.revision if head is not None else 0
            raise VersionConflictError(payload.expected_plan_revision, actual)
        device = db.scalar(
            select(DeviceRow)
            .where(DeviceRow.device_id == payload.device_id)
            .with_for_update()
        )
        if device is None:
            raise NotFoundError("Device", payload.device_id)
        active = db.scalar(
            select(ExecutionSessionRow).where(
                ExecutionSessionRow.device_id == payload.device_id,
                ExecutionSessionRow.session_state.not_in(TERMINAL_STATES),
            )
        )
        if active is not None:
            same_block = active.block_id == block.block_id
            raise LifeOSError(
                "SESSION_ALREADY_ACTIVE" if same_block else "DEVICE_SESSION_ALREADY_ACTIVE",
                (
                    "the schedule block already has a non-terminal session"
                    if same_block
                    else "the device already has a non-terminal execution session"
                ),
                409,
                ["SESSION_ALREADY_ACTIVE" if same_block else "DEVICE_SESSION_ALREADY_ACTIVE"],
            )

        now = self.clock.now()
        dry_run = self.settings.dry_run or not self.settings.real_enforcement_enabled
        preauthorization = {
            "commitment_mode": payload.commitment_mode,
            "dry_run": dry_run,
            "allowed_actions": self._allowed_actions(payload.commitment_mode),
        }
        row = ExecutionSessionRow(
            plan_version_id=plan.plan_version_id,
            block_id=block.block_id,
            task_id=block.task_id,
            device_id=payload.device_id,
            commitment_mode=payload.commitment_mode,
            session_state="RUNNING",
            scheduled_start_at=block.start_at,
            scheduled_end_at=block.end_at,
            actual_start_at=now,
            actual_end_at=None,
            dry_run=dry_run,
            intervention_level=0,
            preauthorization=preauthorization,
            reason_codes=["SESSION_STARTED"],
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        self._append_state(
            db,
            row=row,
            context=self._context_for_block(block.kind),
            session_state="RUNNING",
            reason_codes=["SENSOR_WARMING_UP"],
        )
        append_event(
            db,
            event_type="SESSION.STARTED",
            occurred_at=now,
            received_at=now,
            source="core",
            entity_type="ExecutionSession",
            entity_id=row.session_id,
            idempotency_key=f"session:start:{row.session_id}",
            payload={
                "block_id": str(row.block_id),
                "commitment_mode": row.commitment_mode,
                "dry_run": row.dry_run,
            },
            reason_codes=["SESSION_STARTED"],
        )
        return session_read(row)

    def get_row(self, db: Session, session_id: UUID) -> ExecutionSessionRow:
        row = db.get(ExecutionSessionRow, session_id)
        if row is None:
            raise NotFoundError("ExecutionSession", session_id)
        return row

    def get(self, db: Session, session_id: UUID) -> ExecutionSessionRead:
        return session_read(self.get_row(db, session_id))

    def active_for_device(self, db: Session, device_id: UUID) -> ExecutionSessionRead | None:
        if db.get(DeviceRow, device_id) is None:
            raise NotFoundError("Device", device_id)
        row = db.scalar(
            select(ExecutionSessionRow)
            .where(
                ExecutionSessionRow.device_id == device_id,
                ExecutionSessionRow.session_state.not_in(TERMINAL_STATES),
            )
            .order_by(ExecutionSessionRow.updated_at.desc(), ExecutionSessionRow.session_id)
            .limit(1)
        )
        return session_read(row) if row is not None else None

    def transition(
        self, db: Session, session_id: UUID, action: str, payload: SessionAction
    ) -> ExecutionSessionRead:
        row = self.get_row(db, session_id)
        if row.version != payload.expected_version:
            raise VersionConflictError(payload.expected_version, row.version)
        transitions = {
            "pause": ({"RUNNING", "STARTING"}, "PAUSED"),
            "resume": ({"PAUSED", "INTERRUPTED"}, "RUNNING"),
            "complete": ({"RUNNING", "PAUSED", "INTERRUPTED"}, "COMPLETED"),
            "abort": (
                {"PLANNED", "DUE", "STARTING", "RUNNING", "PAUSED", "INTERRUPTED"},
                "ABORTED",
            ),
        }
        if action not in transitions:
            raise ValueError(f"unknown session action {action}")
        allowed, target = transitions[action]
        if row.session_state not in allowed:
            raise LifeOSError(
                "INVALID_SESSION_TRANSITION",
                f"cannot {action} a session in {row.session_state}",
                409,
                ["INVALID_SESSION_TRANSITION"],
            )
        now = self.clock.now()
        row.session_state = target
        row.reason_codes = [f"SESSION_{target}"]
        row.updated_at = now
        if target in TERMINAL_STATES:
            row.actual_end_at = now
            row.intervention_level = 0
        db.flush()
        self._append_state(
            db,
            row=row,
            context="FOCUS" if target == "RUNNING" else "UNPLANNED",
            session_state=target,
            reason_codes=row.reason_codes,
        )
        append_event(
            db,
            event_type=f"SESSION.{target}",
            occurred_at=now,
            received_at=now,
            source="core",
            entity_type="ExecutionSession",
            entity_id=row.session_id,
            idempotency_key=f"session:{action}:{row.session_id}:{row.version}",
            payload={"reason": payload.reason, "version": row.version},
            reason_codes=row.reason_codes,
        )
        return session_read(row)

    def emergency_release(
        self, db: Session, session_id: UUID, payload: EmergencyReleaseRequest
    ) -> ExecutionSessionRead:
        row = self.get_row(db, session_id)
        existing = db.scalar(
            select(EventLedgerRow).where(EventLedgerRow.idempotency_key == payload.idempotency_key)
        )
        if existing is not None:
            if (
                existing.entity_id != session_id
                or existing.event_type != "SESSION.EMERGENCY_RELEASED"
                or existing.payload != {"reason": payload.reason}
            ):
                raise LifeOSError(
                    "IDEMPOTENCY_CONFLICT",
                    "emergency release key was used for another operation",
                    409,
                    ["IDEMPOTENCY_CONFLICT"],
                )
            return session_read(row)

        now = self.clock.now()
        append_event(
            db,
            event_type="SESSION.EMERGENCY_RELEASED",
            occurred_at=now,
            received_at=now,
            source="user",
            entity_type="ExecutionSession",
            entity_id=row.session_id,
            idempotency_key=payload.idempotency_key,
            payload={"reason": payload.reason},
            reason_codes=["EMERGENCY_RELEASED"],
            compare_occurred_at=False,
        )
        row.emergency_released_at = now
        if row.session_state not in TERMINAL_STATES:
            row.session_state = "INTERRUPTED"
        row.intervention_level = 0
        row.reason_codes = ["EMERGENCY_RELEASED"]
        row.updated_at = now
        self._cancel_enforcement(db, row.session_id, now)
        state = self._append_state(
            db,
            row=row,
            context="EMERGENCY",
            session_state=row.session_state,
            reason_codes=["EMERGENCY_RELEASED"],
        )
        self._release_command(db, row, state, f"emergency:{payload.idempotency_key}", now)
        db.flush()
        return session_read(row)

    def ordinary_override(
        self, db: Session, session_id: UUID, payload: OverrideRequest
    ) -> ExecutionSessionRead:
        row = self.get_row(db, session_id)
        if row.version != payload.expected_version:
            raise VersionConflictError(payload.expected_version, row.version)
        if row.session_state not in {"RUNNING", "PAUSED", "INTERRUPTED", "RECOVERY"}:
            raise LifeOSError(
                "INVALID_SESSION_TRANSITION",
                f"cannot override a session in {row.session_state}",
                409,
                ["INVALID_SESSION_TRANSITION"],
            )
        now = self.clock.now()
        row.override_at = now
        row.override_reason = payload.reason
        row.session_state = "PAUSED"
        row.intervention_level = 0
        row.reason_codes = ["ORDINARY_OVERRIDE"]
        row.updated_at = now
        self._cancel_enforcement(db, row.session_id, now)
        state = self._append_state(
            db,
            row=row,
            context="BREAK",
            session_state="PAUSED",
            reason_codes=["ORDINARY_OVERRIDE"],
        )
        self._release_command(
            db,
            row,
            state,
            f"ordinary-override:{row.session_id}:{payload.expected_version}",
            now,
        )
        append_event(
            db,
            event_type="SESSION.OVERRIDDEN",
            occurred_at=now,
            received_at=now,
            source="user",
            entity_type="ExecutionSession",
            entity_id=row.session_id,
            idempotency_key=f"session:override:{row.session_id}:{payload.expected_version}",
            payload={"reason": payload.reason},
            reason_codes=["ORDINARY_OVERRIDE"],
        )
        db.flush()
        return session_read(row)

    def take_break(
        self, db: Session, session_id: UUID, payload: BreakRequest
    ) -> ExecutionSessionRead:
        row = self.get_row(db, session_id)
        if row.version != payload.expected_version:
            raise VersionConflictError(payload.expected_version, row.version)
        if row.session_state not in {"RUNNING", "INTERRUPTED"}:
            raise LifeOSError(
                "INVALID_SESSION_TRANSITION",
                f"cannot take a break from {row.session_state}",
                409,
                ["INVALID_SESSION_TRANSITION"],
            )
        now = self.clock.now()
        row.session_state = "PAUSED"
        row.intervention_level = 0
        row.reason_codes = ["USER_REPORTED_FATIGUE", "SESSION_PAUSED"]
        row.updated_at = now
        self._cancel_enforcement(db, row.session_id, now)
        state = self._append_state(
            db,
            row=row,
            context="BREAK",
            session_state="PAUSED",
            reason_codes=["USER_REPORTED_FATIGUE", "BREAK_REQUIRED"],
        )
        self._release_command(
            db,
            row,
            state,
            f"break:{row.session_id}:{payload.expected_version}",
            now,
            reason_code="USER_REPORTED_FATIGUE",
        )
        append_event(
            db,
            event_type="SESSION.BREAK_STARTED",
            occurred_at=now,
            received_at=now,
            source="user",
            entity_type="ExecutionSession",
            entity_id=row.session_id,
            idempotency_key=f"session:break:{row.session_id}:{payload.expected_version}",
            payload={
                "duration_minutes": payload.duration_minutes,
                "reason": payload.reason,
            },
            reason_codes=["USER_REPORTED_FATIGUE", "BREAK_REQUIRED"],
        )
        db.flush()
        return session_read(row)

    def _append_state(
        self,
        db: Session,
        *,
        row: ExecutionSessionRow,
        context: str,
        session_state: str,
        reason_codes: list[str],
    ) -> RuntimeStateRow:
        now = self.clock.now()
        head = db.scalar(
            select(RuntimeStateHeadRow).where(RuntimeStateHeadRow.device_id == row.device_id)
        )
        state_version = 1 if head is None else head.state_version + 1
        features = {
            "window_60_coverage_seconds": 0.0,
            "window_300_coverage_seconds": 0.0,
            "allowed_app_ratio_60s": 0.0,
            "blocked_app_ratio_60s": 0.0,
            "blocked_continuous_seconds": 0.0,
            "allowed_continuous_seconds": 0.0,
            "idle_seconds": None,
            "sensor_conflict": False,
        }
        state = RuntimeStateRow(
            device_id=row.device_id,
            session_id=row.session_id,
            estimated_at=now,
            context=context,
            presence="UNKNOWN",
            engagement="UNKNOWN",
            session_state=session_state,
            device_role="SENSOR",
            confidence=0.0,
            reason_codes=reason_codes,
            valid_until=now + timedelta(seconds=30),
            state_version=state_version,
            features=features,
        )
        db.add(state)
        db.flush()
        if head is None:
            db.add(
                RuntimeStateHeadRow(
                    device_id=row.device_id,
                    current_state_id=state.state_id,
                    state_version=state_version,
                    updated_at=now,
                )
            )
        else:
            head.current_state_id = state.state_id
            head.state_version = state_version
            head.updated_at = now
        db.flush()
        return state

    def _cancel_enforcement(self, db: Session, session_id: UUID, now: object) -> None:
        commands = db.scalars(
            select(CommandRow).where(
                CommandRow.session_id == session_id,
                CommandRow.status.in_(["PENDING", "DELIVERED"]),
                CommandRow.command_type.in_(["WOULD_BLOCK", "START_BLOCK", "ENTER_RECOVERY"]),
            )
        ).all()
        for command in commands:
            command.status = "CANCELLED"
            command.updated_at = now  # type: ignore[assignment]

    def _release_command(
        self,
        db: Session,
        session: ExecutionSessionRow,
        state: RuntimeStateRow,
        idempotency_key: str,
        now: object,
        reason_code: str | None = None,
    ) -> None:
        resolved_reason = reason_code or (
            "EMERGENCY_RELEASED" if "emergency" in idempotency_key else "ORDINARY_OVERRIDE"
        )
        decision = PolicyDecisionRow(
            decision_id=uuid4(),
            session_id=session.session_id,
            state_id=state.state_id,
            state_version=state.state_version,
            commitment_mode=session.commitment_mode,
            intervention_level=0,
            action="RELEASE_ALL",
            risk_level="SAFE",
            dry_run=True,
            decided_at=now,
            expires_at=now + timedelta(minutes=5),  # type: ignore[operator]
            idempotency_key=f"decision:{idempotency_key}",
            reason_codes=[resolved_reason],
        )
        db.add(decision)
        db.flush()
        db.add(
            CommandRow(
                target_device_id=session.device_id,
                session_id=session.session_id,
                decision_id=decision.decision_id,
                role_lease_id=None,
                authorized_commitment_mode=session.commitment_mode,
                command_type="RELEASE_ALL",
                risk_level="SAFE",
                status="PENDING",
                issued_at=now,
                not_before=now,
                expires_at=now + timedelta(minutes=5),  # type: ignore[operator]
                required_state_version=state.state_version,
                idempotency_key=f"command:{idempotency_key}",
                payload={"duration_seconds": 0},
                dry_run=True,
                reason_codes=decision.reason_codes,
                updated_at=now,
            )
        )

    @staticmethod
    def _allowed_actions(mode: str) -> list[str]:
        actions = ["SHOW_NOTIFICATION"]
        if mode in {"STANDARD", "STRICT"}:
            actions.extend(["SHOW_CONFIRMATION", "WOULD_BLOCK"])
        if mode == "STRICT":
            actions.append("ENTER_RECOVERY")
        return actions

    @staticmethod
    def _context_for_block(kind: str) -> str:
        return {
            "TASK": "FOCUS",
            "FIXED_EVENT": "CLASS",
            "BREAK": "BREAK",
            "MEAL": "MEAL",
            "TRAVEL": "TRAVEL",
            "SLEEP": "SLEEP",
        }.get(kind, "UNPLANNED")
