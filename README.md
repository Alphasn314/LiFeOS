# LifeOS V1

LifeOS is a local-first closed-loop execution system. Its FastAPI Core is the sole
source of truth; a React PWA and a deliberately limited Python Windows Agent are
clients. V1 plans deterministically, reduces approved activity observations into
multi-axis runtime state, records dry-run interventions, and remains usable when
the optional AI provider is offline.

V1 never terminates processes, edits the registry/firewall, installs autostart,
uses a camera/microphone, or enables real blocking. `dry_run=true` and
`real_enforcement_enabled=false` are the shipped defaults.

## Quick start with Docker Compose

Prerequisites are Docker Desktop with its Linux daemon running and free local
ports 54329, 8000, and 5173.

```powershell
Copy-Item .env.example .env
# Replace both placeholder secrets in .env before starting.
docker compose up --build
```

Compose binds all published ports to `127.0.0.1` only. Open the Web PWA at
<http://localhost:5173>, set its bearer token to the value in `.env`, and leave
the Core URL as `http://localhost:8000`. OpenAPI is at
<http://localhost:8000/docs>. The API container runs `alembic upgrade head`
before starting Core.

To stop without deleting PostgreSQL data:

```powershell
docker compose down
```

`docker compose down -v` deletes the LifeOS PostgreSQL volume and is intentionally
not part of the normal workflow.

## Windows Agent

The Agent runs in a separate Windows shell. It derives a stable UUID, enrolls
itself idempotently, and stores unsent items in
`%LOCALAPPDATA%\LifeOS\agent-queue.db` by default.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e "backend[dev]"
.\.venv\Scripts\python -m pip install -e "windows-agent[dev]"
$env:LIFEOS_CORE_URL = "http://127.0.0.1:8000"
$env:LIFEOS_DEV_TOKEN = "replace-with-the-compose-token"
.\.venv\Scripts\lifeos-windows-agent.exe
```

Optional Agent variables are documented in `windows-agent/README.md`. No service,
scheduled task, tray app, or startup entry is installed.

## Source-development workflow

Start PostgreSQL only, apply migrations, then run Core and Web in separate shells:

```powershell
docker compose up -d postgres
$env:LIFEOS_POSTGRES_PASSWORD = "use-the-same-value-as-your-.env-file"
$env:LIFEOS_DATABASE_URL = "postgresql+psycopg://lifeos:$($env:LIFEOS_POSTGRES_PASSWORD)@127.0.0.1:54329/lifeos"
$env:LIFEOS_DEV_AUTH_TOKEN = "local-dev-token"
.\.venv\Scripts\python -m alembic -c backend/alembic.ini upgrade head
.\.venv\Scripts\python -m uvicorn lifeos.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

```powershell
Set-Location web
npm ci
npm run dev
```

The Vite origin is allowed by default. Enter `local-dev-token` in the Web
connection settings. Core stores UTC and displays/plans in `Asia/Shanghai` unless
the request or Web setting chooses another IANA timezone.

## Verification

```powershell
$env:LIFEOS_POSTGRES_PASSWORD = "use-the-same-value-as-your-.env-file"
$env:LIFEOS_TEST_POSTGRES_URL = "postgresql+psycopg://lifeos:$($env:LIFEOS_POSTGRES_PASSWORD)@127.0.0.1:54329/lifeos"
.\.venv\Scripts\python -m pytest backend/tests
.\.venv\Scripts\python -m ruff check backend/lifeos backend/tests
.\.venv\Scripts\python -m mypy --config-file backend/pyproject.toml backend/lifeos

.\.venv\Scripts\python -m pytest windows-agent/tests
.\.venv\Scripts\python -m ruff check windows-agent/src windows-agent/tests
.\.venv\Scripts\python -m mypy --config-file windows-agent/pyproject.toml windows-agent/src

Set-Location web
npm run format:check
npm run typecheck
npm test
npm run build
npm audit
```

Use a disposable PostgreSQL database for the online test suite when possible;
tests insert validation records but do not drop the database. SQLite remains an
explicit fast-test backend and is not the Core deployment default.

## Documentation

- `docs/architecture.md` and ADRs define the system boundaries.
- `contracts/` contains the frozen language-neutral V1 transport schemas.
- `docs/v1-acceptance.md` maps every gate to executable evidence.
- `LiFeOS_V1_REPORT.md` is the detailed Chinese implementation, ambiguity, and
  tuning report.
