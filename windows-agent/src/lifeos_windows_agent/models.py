"""Pydantic mirrors of the frozen language-neutral V1 Agent contracts."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_REASON_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_utc(value: datetime) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None:
        raise ValueError("timestamp must be timezone-aware")
    if offset.total_seconds() != 0:
        raise ValueError("timestamp must use UTC (Z or +00:00)")
    return value.astimezone(UTC)


def _validate_optional_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _validate_utc(value)


def _validate_reasons(value: list[str]) -> list[str]:
    if not 1 <= len(value) <= 32:
        raise ValueError("reason_codes must contain 1 to 32 entries")
    if len(value) != len(set(value)):
        raise ValueError("reason_codes must be unique")
    if any(_REASON_RE.fullmatch(code) is None for code in value):
        raise ValueError("reason_codes contain an invalid code")
    return value


class ObservationKind(StrEnum):
    ACTIVITY_SAMPLE = "ACTIVITY_SAMPLE"
    LOCK_STATE = "LOCK_STATE"
    SESSION_STATE = "SESSION_STATE"
    MANUAL_CHECK_IN = "MANUAL_CHECK_IN"
    SENSOR_STATUS = "SENSOR_STATUS"


class ObservationPayload(StrictModel):
    foreground_process: str | None = Field(default=None, max_length=128)
    window_title: str | None = Field(default=None, max_length=256)
    idle_seconds: int | None = Field(default=None, ge=0, le=86400)
    is_locked: bool | None = None
    manual_presence: str | None = None
    sensor_ok: bool | None = None
    client_session_state: str | None = Field(default=None, max_length=32)

    @field_validator("manual_presence")
    @classmethod
    def validate_presence(cls, value: str | None) -> str | None:
        if value not in {None, "PRESENT", "ABSENT", "UNKNOWN"}:
            raise ValueError("manual_presence is outside the frozen enum")
        return value


class Observation(StrictModel):
    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    observation_id: uuid.UUID
    device_id: uuid.UUID
    session_id: uuid.UUID | None
    kind: ObservationKind
    observed_at: datetime
    received_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=200)
    payload: ObservationPayload
    reason_codes: list[str]

    _utc_times = field_validator("observed_at", "received_at")(_validate_utc)
    _reasons = field_validator("reason_codes")(_validate_reasons)


class DeviceHeartbeat(StrictModel):
    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    heartbeat_id: uuid.UUID
    device_id: uuid.UUID
    observed_at: datetime
    agent_version: str = Field(min_length=1, max_length=32)
    capabilities: list[str] = Field(max_length=32)
    latest_state_version: int | None = Field(default=None, ge=1)
    core_reachable: bool
    idempotency_key: str = Field(min_length=8, max_length=200)
    reason_codes: list[str]

    _utc_time = field_validator("observed_at")(_validate_utc)
    _reasons = field_validator("reason_codes")(_validate_reasons)

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(len(item) > 64 for item in value):
            raise ValueError("capabilities must be unique and at most 64 characters")
        return value


class CommitmentMode(StrEnum):
    ADVISORY = "ADVISORY"
    STANDARD = "STANDARD"
    STRICT = "STRICT"


class CommandType(StrEnum):
    SHOW_NOTIFICATION = "SHOW_NOTIFICATION"
    SHOW_CONFIRMATION = "SHOW_CONFIRMATION"
    WOULD_BLOCK = "WOULD_BLOCK"
    START_BLOCK = "START_BLOCK"
    ENTER_RECOVERY = "ENTER_RECOVERY"
    RELEASE_ALL = "RELEASE_ALL"


class RiskLevel(StrEnum):
    SAFE = "SAFE"
    HARD = "HARD"


class CommandPayload(StrictModel):
    message: str | None = Field(default=None, max_length=500)
    choices: list[str] | None = Field(default=None, max_length=4)
    applications: list[str] | None = Field(default=None, max_length=64)
    duration_seconds: int | None = Field(default=None, ge=0, le=1800)
    restriction_id: uuid.UUID | None = None

    @field_validator("choices")
    @classmethod
    def validate_choices(cls, value: list[str] | None) -> list[str] | None:
        allowed = {"RETURN_TO_TASK", "BREAK_10_MINUTES", "REPLAN", "END_SESSION"}
        if value is not None and (len(value) != len(set(value)) or not set(value) <= allowed):
            raise ValueError("choices contain an unknown or duplicate value")
        return value

    @field_validator("applications")
    @classmethod
    def validate_applications(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (
            len(value) != len(set(value)) or any(len(item) > 128 for item in value)
        ):
            raise ValueError("applications must be unique and at most 128 characters")
        return value


class Command(StrictModel):
    schema_version: str = Field(pattern=r"^1\.0$")
    command_id: uuid.UUID
    target_device_id: uuid.UUID
    session_id: uuid.UUID
    decision_id: uuid.UUID
    role_lease_id: uuid.UUID | None
    authorized_commitment_mode: CommitmentMode
    command_type: CommandType
    risk_level: RiskLevel
    issued_at: datetime
    not_before: datetime
    expires_at: datetime
    required_state_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=200)
    payload: CommandPayload
    dry_run: bool
    reason_codes: list[str]

    _utc_times = field_validator("issued_at", "not_before", "expires_at")(_validate_utc)
    _reasons = field_validator("reason_codes")(_validate_reasons)

    @model_validator(mode="after")
    def validate_window_and_authority(self) -> Self:
        if not self.issued_at <= self.not_before < self.expires_at:
            raise ValueError(
                "command time window must satisfy issued_at <= not_before < expires_at"
            )
        if self.risk_level == RiskLevel.HARD:
            if self.role_lease_id is None:
                raise ValueError("hard command requires role_lease_id")
            if self.authorized_commitment_mode == CommitmentMode.ADVISORY:
                raise ValueError("hard command requires STANDARD or STRICT authority")
        return self


class DeviceRole(StrEnum):
    PRIMARY_INTERACTION = "PRIMARY_INTERACTION"
    PRIMARY_ENFORCEMENT = "PRIMARY_ENFORCEMENT"
    SENSOR = "SENSOR"
    NOTIFICATION_ONLY = "NOTIFICATION_ONLY"
    AI_WORKER = "AI_WORKER"
    STANDBY = "STANDBY"


class RoleLease(StrictModel):
    schema_version: str = Field(pattern=r"^1\.0$")
    lease_id: uuid.UUID
    device_id: uuid.UUID
    role: DeviceRole
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    issued_for_state_version: int = Field(ge=1)
    version: int = Field(ge=1)
    reason_codes: list[str]

    _utc_times = field_validator("issued_at", "expires_at")(_validate_utc)
    _optional_utc_time = field_validator("revoked_at")(_validate_optional_utc)
    _reasons = field_validator("reason_codes")(_validate_reasons)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.issued_at >= self.expires_at:
            raise ValueError("lease expires_at must follow issued_at")
        return self


class AckStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class CommandAck(StrictModel):
    ack_id: uuid.UUID
    command_id: uuid.UUID
    device_id: uuid.UUID
    status: AckStatus
    acknowledged_at: datetime
    observed_state_version: int | None = Field(default=None, ge=1)
    idempotency_key: str = Field(min_length=8, max_length=200)
    details: dict[str, Any]
    reason_codes: list[str]

    _utc_time = field_validator("acknowledged_at")(_validate_utc)
    _reasons = field_validator("reason_codes")(_validate_reasons)


class CommandBatch(StrictModel):
    commands: list[Command]
    latest_state_version: int | None = Field(default=None, ge=1)
    role_leases: list[RoleLease] = Field(default_factory=list)
