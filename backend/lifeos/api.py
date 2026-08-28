from collections.abc import Iterator
from datetime import date
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import AwareDatetime
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .ai import AIProvider, MockAIProvider
from .clock import Clock, SystemClock
from .config import Settings, get_settings
from .db import Database, create_db
from .errors import LifeOSError
from .schemas import (
    AIJobRead,
    AIJobSubmit,
    BreakRequest,
    BreakResponse,
    CommandAckIn,
    CommandAckRead,
    CommandPollResponse,
    DeviceRead,
    DeviceRegister,
    EmergencyReleaseRequest,
    ErrorItem,
    ErrorResponse,
    EventAccepted,
    EventEnvelopeIn,
    EventEnvelopeRead,
    ExecutionSessionRead,
    FixedEventCreate,
    FixedEventRead,
    FixedEventUpdate,
    HeartbeatIn,
    ObservationIn,
    OverrideRequest,
    PlanRequest,
    PlanVersionRead,
    RuntimeStateRead,
    SessionAction,
    SessionStart,
    TaskCreate,
    TaskRead,
    TaskUpdate,
)
from .services.ai_jobs import AIJobService
from .services.commands import CommandService
from .services.devices import DeviceService
from .services.event_orchestration import EventOrchestrator
from .services.events import EventService
from .services.plans import PlanService
from .services.runtime_service import RuntimeService
from .services.sessions import SessionService
from .services.tasks import FixedEventService, TaskService


def create_app(
    *,
    settings: Settings | None = None,
    database: Database | None = None,
    clock: Clock | None = None,
    ai_provider: AIProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_database = database or create_db(settings=resolved_settings)
    resolved_clock = clock or SystemClock()

    app = FastAPI(
        title="LifeOS Core API",
        version="0.1.0",
        description="Authoritative V1 planning, execution, observation, and safety Core.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
    app.state.database = resolved_database
    app.state.settings = resolved_settings
    app.state.clock = resolved_clock
    task_service = TaskService(resolved_clock)
    fixed_event_service = FixedEventService(
        resolved_clock, resolved_settings.display_timezone
    )
    device_service = DeviceService(resolved_clock)
    event_service = EventService(resolved_clock)
    plan_service = PlanService(resolved_clock)
    event_orchestrator = EventOrchestrator(
        event_service, plan_service, resolved_settings.display_timezone
    )
    runtime_service = RuntimeService(resolved_clock)
    session_service = SessionService(resolved_clock, resolved_settings)
    command_service = CommandService(resolved_clock, resolved_settings)
    ai_job_service = AIJobService(
        resolved_clock, ai_provider or MockAIProvider(resolved_clock)
    )
    app.state.task_service = task_service
    app.state.fixed_event_service = fixed_event_service
    app.state.device_service = device_service
    app.state.event_service = event_service
    app.state.plan_service = plan_service
    app.state.event_orchestrator = event_orchestrator
    app.state.runtime_service = runtime_service
    app.state.session_service = session_service
    app.state.command_service = command_service
    app.state.ai_job_service = ai_job_service

    def db_session() -> Iterator[Session]:
        yield from resolved_database.get_session()

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = resolved_settings.dev_auth_token
        if not expected:
            return
        supplied = ""
        if authorization and authorization.lower().startswith("bearer "):
            supplied = authorization[7:]
        if supplied != expected:
            raise LifeOSError(
                "AUTHENTICATION_REQUIRED",
                "a valid local development bearer token is required",
                401,
                ["AUTHENTICATION_REQUIRED"],
            )

    Db = Annotated[Session, Depends(db_session)]
    Authorized = Annotated[None, Depends(authorize)]

    @app.exception_handler(LifeOSError)
    async def lifeos_error(_request: Request, exc: LifeOSError) -> JSONResponse:
        body = ErrorResponse(
            title=exc.error_code.replace("_", " ").title(),
            status=exc.status_code,
            detail=exc.detail,
            error_code=exc.error_code,
            reason_codes=exc.reason_codes,
            correlation_id=exc.correlation_id,
            errors=[ErrorItem.model_validate(item) for item in exc.errors],
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=body.model_dump(mode="json"),
            media_type="application/problem+json",
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        body = ErrorResponse(
            title="Request Validation Failed",
            status=422,
            detail="one or more request fields are invalid",
            error_code="VALIDATION_ERROR",
            reason_codes=["VALIDATION_ERROR"],
            correlation_id=uuid4(),
            errors=[
                ErrorItem(
                    path=".".join(str(part) for part in item["loc"]),
                    message=item["msg"],
                )
                for item in exc.errors()
            ],
        )
        return JSONResponse(
            status_code=422,
            content=body.model_dump(mode="json"),
            media_type="application/problem+json",
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error(_request: Request, _exc: IntegrityError) -> JSONResponse:
        body = ErrorResponse(
            title="Persistence Conflict",
            status=409,
            detail="the request conflicts with persisted LifeOS state",
            error_code="PERSISTENCE_CONFLICT",
            reason_codes=["PERSISTENCE_CONFLICT"],
            correlation_id=uuid4(),
        )
        return JSONResponse(
            status_code=409,
            content=body.model_dump(mode="json"),
            media_type="application/problem+json",
        )

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, exc: ValueError) -> JSONResponse:
        body = ErrorResponse(
            title="Invalid Domain Value",
            status=422,
            detail=str(exc),
            error_code="DOMAIN_VALIDATION_ERROR",
            reason_codes=["DOMAIN_VALIDATION_ERROR"],
            correlation_id=uuid4(),
        )
        return JSONResponse(
            status_code=422,
            content=body.model_dump(mode="json"),
            media_type="application/problem+json",
        )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "lifeos-core",
            "version": "0.1.0",
            "dry_run": resolved_settings.dry_run,
            "real_enforcement_enabled": resolved_settings.real_enforcement_enabled,
        }

    @app.get("/ready")
    def ready(db: Db) -> dict[str, str]:
        try:
            db.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise LifeOSError(
                "DATABASE_UNAVAILABLE",
                "authoritative database is unavailable",
                503,
                ["DATABASE_UNAVAILABLE"],
            ) from exc
        return {"status": "ready"}

    @app.post("/api/v1/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
    def create_task(payload: TaskCreate, db: Db, _auth: Authorized) -> TaskRead:
        return task_service.create(db, payload)

    @app.get("/api/v1/tasks", response_model=list[TaskRead])
    def list_tasks(db: Db, _auth: Authorized, include_terminal: bool = False) -> list[TaskRead]:
        return task_service.list(db, include_terminal=include_terminal)

    @app.get("/api/v1/tasks/{task_id}", response_model=TaskRead)
    def get_task(task_id: UUID, db: Db, _auth: Authorized) -> TaskRead:
        return task_service.get(db, task_id)

    @app.patch("/api/v1/tasks/{task_id}", response_model=TaskRead)
    def update_task(task_id: UUID, payload: TaskUpdate, db: Db, _auth: Authorized) -> TaskRead:
        return task_service.update(db, task_id, payload)

    @app.delete("/api/v1/tasks/{task_id}", response_model=TaskRead)
    def delete_task(
        task_id: UUID,
        db: Db,
        _auth: Authorized,
        expected_version: int = Query(ge=1),
    ) -> TaskRead:
        return task_service.delete(db, task_id, expected_version)

    @app.post(
        "/api/v1/fixed-events",
        response_model=FixedEventRead,
        status_code=status.HTTP_201_CREATED,
    )
    def create_fixed_event(payload: FixedEventCreate, db: Db, _auth: Authorized) -> FixedEventRead:
        return fixed_event_service.create(db, payload)

    @app.get("/api/v1/fixed-events", response_model=list[FixedEventRead])
    def list_fixed_events(
        start_at: Annotated[AwareDatetime, Query()],
        end_at: Annotated[AwareDatetime, Query()],
        db: Db,
        _auth: Authorized,
    ) -> list[FixedEventRead]:
        if end_at <= start_at:
            raise ValueError("end_at must be after start_at")
        return fixed_event_service.list(db, start_at, end_at)

    @app.get("/api/v1/fixed-events/{fixed_event_id}", response_model=FixedEventRead)
    def get_fixed_event(fixed_event_id: UUID, db: Db, _auth: Authorized) -> FixedEventRead:
        return fixed_event_service.get(db, fixed_event_id)

    @app.patch("/api/v1/fixed-events/{fixed_event_id}", response_model=FixedEventRead)
    def update_fixed_event(
        fixed_event_id: UUID,
        payload: FixedEventUpdate,
        db: Db,
        _auth: Authorized,
    ) -> FixedEventRead:
        return fixed_event_service.update(db, fixed_event_id, payload)

    @app.delete("/api/v1/fixed-events/{fixed_event_id}", status_code=204)
    def delete_fixed_event(
        fixed_event_id: UUID,
        db: Db,
        _auth: Authorized,
        expected_version: int = Query(ge=1),
    ) -> None:
        fixed_event_service.delete(db, fixed_event_id, expected_version)

    @app.post(
        "/api/v1/plans/generate",
        response_model=PlanVersionRead,
        status_code=status.HTTP_201_CREATED,
    )
    def generate_plan(payload: PlanRequest, db: Db, _auth: Authorized) -> PlanVersionRead:
        if "display_timezone" not in payload.model_fields_set:
            payload = payload.model_copy(
                update={"display_timezone": resolved_settings.display_timezone}
            )
        return plan_service.generate(db, payload)

    @app.get("/api/v1/plans/current", response_model=PlanVersionRead)
    def current_plan(
        plan_date: date,
        db: Db,
        _auth: Authorized,
        display_timezone: str | None = None,
    ) -> PlanVersionRead:
        return plan_service.current(
            db, plan_date, display_timezone or resolved_settings.display_timezone
        )

    @app.get("/api/v1/plans/history", response_model=list[PlanVersionRead])
    def plan_history(
        plan_date: date,
        db: Db,
        _auth: Authorized,
        display_timezone: str | None = None,
    ) -> list[PlanVersionRead]:
        return plan_service.history(
            db, plan_date, display_timezone or resolved_settings.display_timezone
        )

    @app.post("/api/v1/devices", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
    def register_device(payload: DeviceRegister, db: Db, _auth: Authorized) -> DeviceRead:
        return device_service.register(db, payload)

    @app.put("/api/v1/devices/{device_id}", response_model=DeviceRead)
    def enroll_device(
        device_id: UUID, payload: DeviceRegister, db: Db, _auth: Authorized
    ) -> DeviceRead:
        return device_service.enroll(db, device_id, payload)

    @app.get("/api/v1/devices", response_model=list[DeviceRead])
    def list_devices(db: Db, _auth: Authorized) -> list[DeviceRead]:
        device_service.mark_stale_offline(db)
        return device_service.list(db)

    @app.get("/api/v1/devices/{device_id}", response_model=DeviceRead)
    def get_device(device_id: UUID, db: Db, _auth: Authorized) -> DeviceRead:
        return device_service.get(db, device_id)

    @app.get(
        "/api/v1/devices/{device_id}/active-session",
        response_model=ExecutionSessionRead,
        responses={204: {"description": "The device has no non-terminal session."}},
    )
    def active_device_session(
        device_id: UUID, db: Db, _auth: Authorized
    ) -> ExecutionSessionRead | Response:
        active = session_service.active_for_device(db, device_id)
        return active if active is not None else Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/v1/devices/heartbeats", response_model=DeviceRead)
    def heartbeat(payload: HeartbeatIn, db: Db, _auth: Authorized) -> DeviceRead:
        return device_service.heartbeat(db, payload)

    @app.post(
        "/api/v1/observations",
        response_model=RuntimeStateRead,
        status_code=status.HTTP_201_CREATED,
    )
    def ingest_observation(payload: ObservationIn, db: Db, _auth: Authorized) -> RuntimeStateRead:
        return runtime_service.ingest_observation(db, payload)

    @app.get("/api/v1/devices/{device_id}/runtime-state", response_model=RuntimeStateRead)
    def current_runtime_state(device_id: UUID, db: Db, _auth: Authorized) -> RuntimeStateRead:
        return runtime_service.current(db, device_id)

    @app.post(
        "/api/v1/sessions",
        response_model=ExecutionSessionRead,
        status_code=status.HTTP_201_CREATED,
    )
    def start_session(payload: SessionStart, db: Db, _auth: Authorized) -> ExecutionSessionRead:
        return session_service.start(db, payload)

    @app.get("/api/v1/sessions/{session_id}", response_model=ExecutionSessionRead)
    def get_session(session_id: UUID, db: Db, _auth: Authorized) -> ExecutionSessionRead:
        return session_service.get(db, session_id)

    @app.post(
        "/api/v1/sessions/{session_id}/break",
        response_model=BreakResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def take_break(
        session_id: UUID, payload: BreakRequest, db: Db, _auth: Authorized
    ) -> BreakResponse:
        paused = session_service.take_break(db, session_id, payload)
        plan = plan_service.insert_break(
            db, session_id, duration_minutes=payload.duration_minutes
        )
        return BreakResponse(session=paused, plan=plan)

    @app.post(
        "/api/v1/sessions/{session_id}/emergency-release",
        response_model=ExecutionSessionRead,
    )
    def emergency_release(
        session_id: UUID,
        payload: EmergencyReleaseRequest,
        db: Db,
        _auth: Authorized,
    ) -> ExecutionSessionRead:
        return session_service.emergency_release(db, session_id, payload)

    @app.post(
        "/api/v1/sessions/{session_id}/ordinary-override",
        response_model=ExecutionSessionRead,
    )
    def ordinary_override(
        session_id: UUID,
        payload: OverrideRequest,
        db: Db,
        _auth: Authorized,
    ) -> ExecutionSessionRead:
        return session_service.ordinary_override(db, session_id, payload)

    @app.post("/api/v1/sessions/{session_id}/{action}", response_model=ExecutionSessionRead)
    def transition_session(
        session_id: UUID,
        action: str,
        payload: SessionAction,
        db: Db,
        _auth: Authorized,
    ) -> ExecutionSessionRead:
        return session_service.transition(db, session_id, action, payload)

    @app.get("/api/v1/devices/{device_id}/commands", response_model=CommandPollResponse)
    def poll_commands(
        device_id: UUID,
        db: Db,
        _auth: Authorized,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> CommandPollResponse:
        return command_service.poll(db, device_id, limit=limit)

    @app.post("/api/v1/commands/acks", response_model=CommandAckRead)
    def acknowledge_command(payload: CommandAckIn, db: Db, _auth: Authorized) -> CommandAckRead:
        return command_service.acknowledge(db, payload)

    @app.post(
        "/api/v1/events",
        response_model=EventAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def ingest_event(payload: EventEnvelopeIn, db: Db, _auth: Authorized) -> EventAccepted:
        return event_orchestrator.ingest(db, payload)

    @app.get("/api/v1/events", response_model=list[EventEnvelopeRead])
    def list_events(
        db: Db,
        _auth: Authorized,
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> list[EventEnvelopeRead]:
        return event_service.list(db, limit=limit)

    @app.post("/api/v1/ai/jobs", response_model=AIJobRead, status_code=status.HTTP_201_CREATED)
    def run_ai_job(payload: AIJobSubmit, db: Db, _auth: Authorized) -> AIJobRead:
        return ai_job_service.submit_and_run(db, payload)

    return app
