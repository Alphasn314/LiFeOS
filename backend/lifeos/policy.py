from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid5

from lifeos.schemas import (
    CommandPayload,
    CommandRead,
    CommandType,
    CommitmentMode,
    Engagement,
    RuntimeStateRead,
    SessionState,
    utc,
)

POLICY_VERSION = "intervention-v1"
_POLICY_NAMESPACE = UUID("4b7308a9-9afe-4e36-9cb7-b12cb9280168")


@dataclass(frozen=True, slots=True)
class PolicyDecisionDraft:
    decision_id: UUID
    session_id: UUID | None
    state_version: int
    commitment_mode: str
    level: int
    action: str
    dry_run: bool
    decided_at: datetime
    expires_at: datetime
    reason_codes: tuple[str, ...]
    policy_version: str = POLICY_VERSION


@dataclass(frozen=True, slots=True)
class PolicyResult:
    decision: PolicyDecisionDraft
    command: CommandRead | None


def evaluate_policy(
    runtime_state: RuntimeStateRead,
    *,
    commitment_mode: CommitmentMode,
    evaluated_at: datetime,
    off_task_seconds: float,
    ignored_prompts: int = 0,
    allowed_blocklist: Sequence[str] = (),
) -> PolicyResult:
    """Map current confirmed evidence to one bounded, V1-dry-run command draft."""
    if off_task_seconds < 0 or ignored_prompts < 0:
        raise ValueError("policy durations and counters cannot be negative")
    now = utc(evaluated_at)
    mode = str(commitment_mode)
    if mode not in {item.value for item in CommitmentMode}:
        raise ValueError("unknown commitment mode")
    level, action, reasons = _level_for_state(
        runtime_state,
        mode,
        now,
        off_task_seconds,
        ignored_prompts,
    )
    semantic_key = f"policy:{runtime_state.session_id}:{runtime_state.state_version}:{level}:{mode}"
    decision_id = uuid5(_POLICY_NAMESPACE, semantic_key)
    decision_time = utc(runtime_state.estimated_at)
    decision = PolicyDecisionDraft(
        decision_id=decision_id,
        session_id=runtime_state.session_id,
        state_version=runtime_state.state_version,
        commitment_mode=mode,
        level=level,
        action=action,
        dry_run=True,
        decided_at=decision_time,
        expires_at=utc(runtime_state.valid_until),
        reason_codes=tuple(reasons),
    )
    command = _command_for_decision(
        decision,
        runtime_state,
        tuple(dict.fromkeys(app.casefold() for app in allowed_blocklist)),
    )
    return PolicyResult(decision, command)


def _level_for_state(
    state: RuntimeStateRead,
    mode: str,
    now: datetime,
    off_task_seconds: float,
    ignored_prompts: int,
) -> tuple[int, str, list[str]]:
    mode_reason = f"COMMITMENT_{mode}"
    usable = (
        state.session_id is not None
        and str(state.session_state) == SessionState.RUNNING
        and str(state.engagement) == Engagement.OFF_TASK
        and state.confidence >= 0.65
        and now < utc(state.valid_until)
    )
    if not usable:
        reason = (
            "ENGAGEMENT_UNKNOWN"
            if str(state.engagement) == Engagement.UNKNOWN
            or state.confidence < 0.65
            or now >= utc(state.valid_until)
            else "ENGAGEMENT_NORMAL"
        )
        return 0, "NONE", [reason, mode_reason]
    if off_task_seconds < 30:
        return 0, "NONE", ["ENGAGEMENT_NORMAL", mode_reason]
    if off_task_seconds < 90:
        return 1, "NOTIFY", ["OFF_TASK_30_SECONDS", mode_reason]
    if off_task_seconds <= 180:
        return 2, "CONFIRM", ["OFF_TASK_90_SECONDS", mode_reason]

    if mode == CommitmentMode.ADVISORY:
        return 2, "ADVISE_CHOICES", ["OFF_TASK_180_SECONDS", mode_reason]
    if ignored_prompts >= 3:
        return 5, "INTERRUPT_AND_REPLAN", ["OFF_TASK_180_SECONDS", mode_reason]
    if mode == CommitmentMode.STRICT and ignored_prompts >= 2:
        return 4, "RECOVERY_DRY_RUN", ["OFF_TASK_180_SECONDS", mode_reason]
    return 3, "WOULD_BLOCK", ["OFF_TASK_180_SECONDS", mode_reason]


def _command_for_decision(
    decision: PolicyDecisionDraft,
    state: RuntimeStateRead,
    applications: tuple[str, ...],
) -> CommandRead | None:
    if decision.level == 0 or decision.session_id is None:
        return None

    command_type: CommandType
    payload: CommandPayload
    ttl_seconds: int
    extra_reasons: list[str] = []
    if decision.level == 1:
        command_type = CommandType.SHOW_NOTIFICATION
        payload = CommandPayload(message="Return to the current LifeOS task.")
        ttl_seconds = 60
    elif decision.level == 2 and decision.commitment_mode == CommitmentMode.ADVISORY:
        command_type = CommandType.SHOW_NOTIFICATION
        payload = CommandPayload(
            message="Return, take a 10-minute break, replan, or end the session."
        )
        ttl_seconds = 60
    elif decision.level == 2:
        command_type = CommandType.SHOW_CONFIRMATION
        payload = CommandPayload(
            message="Choose how to continue this session.",
            choices=["RETURN_TO_TASK", "BREAK_10_MINUTES", "REPLAN", "END_SESSION"],
        )
        ttl_seconds = 120
    elif decision.level == 3:
        command_type = CommandType.WOULD_BLOCK
        payload = CommandPayload(
            message="Dry-run: the pre-authorized blocklist would be limited for 10 minutes.",
            applications=list(applications),
            duration_seconds=600,
            restriction_id=uuid5(decision.decision_id, "restriction"),
        )
        ttl_seconds = 60
        extra_reasons.extend(["DRY_RUN_REQUIRED", "WOULD_BLOCK_ONLY"])
    elif decision.level == 4:
        command_type = CommandType.WOULD_BLOCK
        payload = CommandPayload(
            message="Dry-run: Strict Recovery Mode would begin for at most 15 minutes.",
            applications=list(applications),
            duration_seconds=900,
            restriction_id=uuid5(decision.decision_id, "recovery"),
        )
        ttl_seconds = 60
        extra_reasons.extend(["DRY_RUN_REQUIRED", "WOULD_BLOCK_ONLY"])
    else:
        command_type = CommandType.SHOW_NOTIFICATION
        payload = CommandPayload(
            message=(
                "Session interrupted after no response; restrictions expire "
                "and replan is requested."
            )
        )
        ttl_seconds = 60

    command_key = f"{decision.decision_id}:{command_type}"
    reasons = list(dict.fromkeys([*decision.reason_codes, *extra_reasons]))
    command_expires_at = min(
        decision.decided_at + timedelta(seconds=ttl_seconds),
        decision.expires_at,
    )
    return CommandRead(
        command_id=uuid5(_POLICY_NAMESPACE, command_key),
        target_device_id=state.device_id,
        session_id=decision.session_id,
        decision_id=decision.decision_id,
        role_lease_id=None,
        authorized_commitment_mode=CommitmentMode(decision.commitment_mode),
        command_type=command_type,
        risk_level="SAFE",
        issued_at=decision.decided_at,
        not_before=decision.decided_at,
        expires_at=command_expires_at,
        required_state_version=decision.state_version,
        idempotency_key=f"command:{command_key}",
        payload=payload,
        dry_run=True,
        reason_codes=reasons,
    )
