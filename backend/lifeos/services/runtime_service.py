from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import Clock
from ..errors import IdempotencyConflictError, LifeOSError, NotFoundError
from ..models import (
    CommandRow,
    DeviceRow,
    ExecutionSessionRow,
    FeatureSnapshotRow,
    ObservationRow,
    PolicyDecisionRow,
    RuntimeStateHeadRow,
    RuntimeStateRow,
    ScheduleBlockRow,
    TaskRow,
)
from ..policy import evaluate_policy
from ..runtime import FeatureSnapshot, build_feature_snapshot, reduce_runtime_state
from ..schemas import (
    CommitmentMode,
    Context,
    DeviceRole,
    Engagement,
    FeatureRead,
    ObservationIn,
    ObservationKind,
    ObservationPayload,
    Presence,
    RuntimeStateRead,
    SessionState,
)
from .audit import append_event

DEFAULT_BLOCKED_APPS = ["cs2.exe"]


def runtime_state_read(row: RuntimeStateRow) -> RuntimeStateRead:
    return RuntimeStateRead(
        state_id=row.state_id,
        device_id=row.device_id,
        session_id=row.session_id,
        estimated_at=row.estimated_at,
        context=Context(row.context),
        presence=Presence(row.presence),
        engagement=Engagement(row.engagement),
        session_state=SessionState(row.session_state),
        device_role=DeviceRole(row.device_role),
        confidence=row.confidence,
        reason_codes=row.reason_codes,
        valid_until=row.valid_until,
        state_version=row.state_version,
        features=FeatureRead.model_validate(row.features),
    )


class RuntimeService:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def ingest_observation(self, db: Session, payload: ObservationIn) -> RuntimeStateRead:
        device = db.get(DeviceRow, payload.device_id)
        if device is None:
            raise NotFoundError("Device", payload.device_id)
        session = None
        if payload.session_id is not None:
            session = db.get(ExecutionSessionRow, payload.session_id)
            if session is None:
                raise NotFoundError("ExecutionSession", payload.session_id)
            if session.device_id != payload.device_id:
                raise LifeOSError(
                    "TARGET_DEVICE_MISMATCH",
                    "observation device does not own the execution session",
                    409,
                    ["TARGET_DEVICE_MISMATCH"],
                )
        existing = db.scalar(
            select(ObservationRow).where(ObservationRow.idempotency_key == payload.idempotency_key)
        )
        if existing is not None:
            if (
                existing.observation_id != payload.observation_id
                or existing.device_id != payload.device_id
                or existing.session_id != payload.session_id
                or existing.schema_version != payload.schema_version
                or existing.kind != payload.kind
                or existing.observed_at != payload.observed_at
                or existing.payload != payload.payload.model_dump(mode="json")
                or existing.reason_codes != payload.reason_codes
            ):
                raise IdempotencyConflictError(payload.idempotency_key)
            return self.current(db, payload.device_id)

        now = self.clock.now()
        if payload.observed_at > now + timedelta(minutes=5):
            raise LifeOSError(
                "OBSERVATION_FROM_FUTURE",
                "observation clock is more than five minutes ahead of Core",
                422,
                ["OBSERVATION_FROM_FUTURE"],
            )
        row = ObservationRow(
            observation_id=payload.observation_id,
            schema_version=payload.schema_version,
            device_id=payload.device_id,
            session_id=payload.session_id,
            kind=payload.kind,
            observed_at=payload.observed_at,
            received_at=payload.received_at or now,
            idempotency_key=payload.idempotency_key,
            payload=payload.payload.model_dump(mode="json"),
            reason_codes=payload.reason_codes,
        )
        db.add(row)
        db.flush()
        append_event(
            db,
            event_type="OBSERVATION.ACCEPTED",
            occurred_at=payload.observed_at,
            received_at=now,
            source="windows-agent",
            entity_type="Observation",
            entity_id=row.observation_id,
            idempotency_key=f"audit:{payload.idempotency_key}",
            payload={
                "kind": payload.kind,
                "device_id": str(payload.device_id),
                "session_id": str(payload.session_id) if payload.session_id else None,
            },
            reason_codes=payload.reason_codes,
        )

        observations = self._observations(db, payload.device_id, payload.session_id, now)
        allowed_apps, blocked_apps, idle_tolerance, context = self._activity_rules(db, session)
        features = build_feature_snapshot(
            observations,
            device_id=payload.device_id,
            session_id=payload.session_id,
            evaluated_at=now,
            allowed_apps=allowed_apps,
            blocked_apps=blocked_apps,
        )
        feature_row = self._persist_features(db, features, len(observations))

        head = db.scalar(
            select(RuntimeStateHeadRow).where(RuntimeStateHeadRow.device_id == payload.device_id)
        )
        previous_row = db.get(RuntimeStateRow, head.current_state_id) if head else None
        previous_state = (
            runtime_state_read(previous_row)
            if previous_row is not None and previous_row.session_id == payload.session_id
            else None
        )
        previous_features = self._previous_features(db, payload.device_id, feature_row)
        state_version = 1 if head is None else head.state_version + 1
        state = reduce_runtime_state(
            features,
            estimated_at=now,
            context=Context(context),
            session_state=SessionState(session.session_state if session is not None else "PLANNED"),
            device_role=DeviceRole.SENSOR,
            state_version=state_version,
            idle_tolerance_seconds=idle_tolerance,
            previous_state=previous_state,
            previous_features=previous_features,
        )
        state_row = RuntimeStateRow(
            state_id=state.state_id,
            device_id=state.device_id,
            session_id=state.session_id,
            feature_snapshot_id=feature_row.feature_snapshot_id,
            estimated_at=state.estimated_at,
            context=state.context,
            presence=state.presence,
            engagement=state.engagement,
            session_state=state.session_state,
            device_role=state.device_role,
            confidence=state.confidence,
            reason_codes=state.reason_codes,
            valid_until=state.valid_until,
            state_version=state.state_version,
            features=state.features.model_dump(mode="json"),
        )
        db.add(state_row)
        db.flush()
        if head is None:
            head = RuntimeStateHeadRow(
                device_id=state.device_id,
                current_state_id=state.state_id,
                state_version=state.state_version,
                updated_at=now,
            )
            db.add(head)
        else:
            head.current_state_id = state.state_id
            head.state_version = state.state_version
            head.updated_at = now
        device.latest_state_version = state.state_version
        device.updated_at = now
        db.flush()
        if session is not None:
            self._apply_policy(db, session, state_row, state, blocked_apps)
        return runtime_state_read(state_row)

    def current(self, db: Session, device_id: UUID) -> RuntimeStateRead:
        head = db.scalar(
            select(RuntimeStateHeadRow).where(RuntimeStateHeadRow.device_id == device_id)
        )
        if head is None:
            raise NotFoundError("RuntimeState", device_id)
        row = db.get(RuntimeStateRow, head.current_state_id)
        if row is None:
            raise NotFoundError("RuntimeState", head.current_state_id)
        return runtime_state_read(row)

    def _observations(
        self, db: Session, device_id: UUID, session_id: UUID | None, now: datetime
    ) -> list[ObservationIn]:
        rows = db.scalars(
            select(ObservationRow)
            .where(
                ObservationRow.device_id == device_id,
                ObservationRow.session_id == session_id,
                ObservationRow.observed_at >= now - timedelta(seconds=300),
                ObservationRow.observed_at <= now,
            )
            .order_by(ObservationRow.observed_at, ObservationRow.observation_id)
        ).all()
        return [
            ObservationIn(
                schema_version="1.0",
                observation_id=row.observation_id,
                device_id=row.device_id,
                session_id=row.session_id,
                kind=ObservationKind(row.kind),
                observed_at=row.observed_at,
                received_at=row.received_at,
                idempotency_key=row.idempotency_key,
                payload=ObservationPayload.model_validate(row.payload),
                reason_codes=row.reason_codes,
            )
            for row in rows
        ]

    def _activity_rules(
        self, db: Session, session: ExecutionSessionRow | None
    ) -> tuple[list[str], list[str], int, str]:
        if session is None:
            return [], DEFAULT_BLOCKED_APPS, 300, "UNPLANNED"
        block = db.get(ScheduleBlockRow, session.block_id)
        if block is None:
            return [], DEFAULT_BLOCKED_APPS, 300, "UNPLANNED"
        allowed = list(block.allowed_apps)
        blocked = sorted(set([*block.blocked_apps, *DEFAULT_BLOCKED_APPS]))
        tolerance = 300
        if block.task_id is not None:
            task = db.get(TaskRow, block.task_id)
            if task is not None:
                allowed = task.allowed_apps
                blocked = sorted(set([*task.blocked_apps, *DEFAULT_BLOCKED_APPS]))
                tolerance = task.idle_tolerance_seconds
        context = {
            "TASK": "FOCUS",
            "FIXED_EVENT": "CLASS",
            "BREAK": "BREAK",
            "MEAL": "MEAL",
            "TRAVEL": "TRAVEL",
            "SLEEP": "SLEEP",
            "BUFFER": "FREE",
        }.get(block.kind, "UNPLANNED")
        return allowed, blocked, tolerance, context

    def _persist_features(
        self, db: Session, features: FeatureSnapshot, observation_count: int
    ) -> FeatureSnapshotRow:
        row = FeatureSnapshotRow(
            feature_snapshot_id=features.feature_id,
            device_id=features.device_id,
            session_id=features.session_id,
            computed_at=features.evaluated_at,
            window_60_started_at=features.evaluated_at - timedelta(seconds=60),
            window_300_started_at=features.evaluated_at - timedelta(seconds=300),
            window_ended_at=features.evaluated_at,
            window_60_coverage_seconds=features.window_60_coverage_seconds,
            window_300_coverage_seconds=features.window_300_coverage_seconds,
            allowed_app_ratio_60s=features.allowed_app_ratio_60s,
            blocked_app_ratio_60s=features.blocked_app_ratio_60s,
            blocked_continuous_seconds=features.blocked_continuous_seconds,
            allowed_continuous_seconds=features.allowed_continuous_seconds,
            idle_seconds=features.idle_seconds,
            sensor_conflict=features.sensor_conflict,
            source_observation_count=observation_count,
            algorithm_version=features.algorithm_version,
            reason_codes=list(features.reason_codes),
        )
        db.add(row)
        db.flush()
        return row

    def _previous_features(
        self, db: Session, device_id: UUID, current: FeatureSnapshotRow
    ) -> FeatureSnapshot | None:
        row = db.scalar(
            select(FeatureSnapshotRow)
            .where(
                FeatureSnapshotRow.device_id == device_id,
                FeatureSnapshotRow.session_id == current.session_id,
                FeatureSnapshotRow.feature_snapshot_id != current.feature_snapshot_id,
            )
            .order_by(FeatureSnapshotRow.computed_at.desc())
            .limit(1)
        )
        if row is None:
            return None
        failed = "SENSOR_FAILURE" in row.reason_codes
        locked = "PC_LOCKED" in row.reason_codes
        confidence = min(1.0, row.window_60_coverage_seconds / 60)
        if row.sensor_conflict or failed:
            confidence = 0.0
        elif locked:
            confidence = 1.0
        return FeatureSnapshot(
            feature_id=row.feature_snapshot_id,
            device_id=row.device_id,
            session_id=row.session_id,
            evaluated_at=row.window_ended_at,
            window_60_coverage_seconds=row.window_60_coverage_seconds,
            window_300_coverage_seconds=row.window_300_coverage_seconds,
            allowed_app_ratio_60s=row.allowed_app_ratio_60s,
            blocked_app_ratio_60s=row.blocked_app_ratio_60s,
            blocked_continuous_seconds=row.blocked_continuous_seconds,
            allowed_continuous_seconds=row.allowed_continuous_seconds,
            idle_seconds=row.idle_seconds,
            sensor_conflict=row.sensor_conflict,
            sensor_failed=failed,
            is_locked=locked,
            manual_presence=None,
            manual_presence_continuous_seconds=0,
            confidence=confidence,
            off_task_candidate=(
                row.blocked_continuous_seconds >= 30 or row.blocked_app_ratio_60s >= 0.60
            ),
            on_task_candidate=row.allowed_app_ratio_60s >= 0.75,
            reason_codes=tuple(row.reason_codes),
            algorithm_version=row.algorithm_version,
        )

    def _apply_policy(
        self,
        db: Session,
        session: ExecutionSessionRow,
        state_row: RuntimeStateRow,
        state: RuntimeStateRead,
        blocked_apps: list[str],
    ) -> None:
        off_task_seconds = self._off_task_seconds(db, state)
        result = evaluate_policy(
            state,
            commitment_mode=CommitmentMode(session.commitment_mode),
            evaluated_at=state.estimated_at,
            off_task_seconds=off_task_seconds,
            ignored_prompts=0,
            allowed_blocklist=blocked_apps,
        )
        key = (
            f"policy:{session.session_id}:{state.state_version}:"
            f"{result.decision.level}:{session.commitment_mode}"
        )
        decision = PolicyDecisionRow(
            decision_id=result.decision.decision_id,
            session_id=session.session_id,
            state_id=state_row.state_id,
            state_version=state.state_version,
            commitment_mode=session.commitment_mode,
            intervention_level=result.decision.level,
            action=result.decision.action,
            risk_level=(result.command.risk_level if result.command else "SAFE"),
            dry_run=True,
            decided_at=result.decision.decided_at,
            expires_at=result.decision.expires_at,
            idempotency_key=key,
            reason_codes=list(result.decision.reason_codes),
        )
        db.add(decision)
        db.flush()
        if session.intervention_level != result.decision.level:
            session.intervention_level = result.decision.level
            session.updated_at = self.clock.now()
        if state.session_state == "INTERRUPTED" and session.session_state not in {
            "COMPLETED",
            "ABORTED",
            "MISSED",
        }:
            session.session_state = "INTERRUPTED"
            session.reason_codes = state.reason_codes
        if result.command is not None:
            command = result.command
            db.add(
                CommandRow(
                    command_id=command.command_id,
                    target_device_id=command.target_device_id,
                    session_id=command.session_id,
                    decision_id=command.decision_id,
                    role_lease_id=command.role_lease_id,
                    authorized_commitment_mode=command.authorized_commitment_mode,
                    command_type=command.command_type,
                    risk_level=command.risk_level,
                    status="PENDING",
                    issued_at=command.issued_at,
                    not_before=command.not_before,
                    expires_at=command.expires_at,
                    required_state_version=command.required_state_version,
                    idempotency_key=command.idempotency_key,
                    payload=command.payload.model_dump(mode="json", exclude_none=True),
                    dry_run=True,
                    reason_codes=command.reason_codes,
                    updated_at=self.clock.now(),
                )
            )
        db.flush()
        append_event(
            db,
            event_type="POLICY.DECIDED",
            occurred_at=state.estimated_at,
            received_at=self.clock.now(),
            source="core",
            entity_type="PolicyDecision",
            entity_id=decision.decision_id,
            idempotency_key=f"audit:{key}",
            payload={
                "level": result.decision.level,
                "action": result.decision.action,
                "state_version": state.state_version,
            },
            reason_codes=list(result.decision.reason_codes),
        )

    @staticmethod
    def _off_task_seconds(db: Session, state: RuntimeStateRead) -> float:
        if state.engagement != "OFF_TASK" or state.session_id is None:
            return 0.0
        rows = db.scalars(
            select(RuntimeStateRow)
            .where(
                RuntimeStateRow.device_id == state.device_id,
                RuntimeStateRow.session_id == state.session_id,
                RuntimeStateRow.estimated_at <= state.estimated_at,
            )
            .order_by(RuntimeStateRow.estimated_at.desc())
        ).all()
        earliest = state.estimated_at
        for row in rows:
            if row.engagement != "OFF_TASK":
                break
            earliest = row.estimated_at
        return max(0.0, (state.estimated_at - earliest).total_seconds())
