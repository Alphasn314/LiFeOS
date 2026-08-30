# LifeOS contribution contract

LifeOS is a safety-sensitive modular monolith. `backend/lifeos/schemas.py` and
`contracts/*.schema.json` are the frozen V1 boundary. Changes to those boundaries
require an ADR in `docs/adr/`, a migration when persistence changes, and contract
tests.

## Directory ownership

- `contracts/`, `docs/`: Architecture/Contracts
- `backend/lifeos/db.py`, `models.py`, `api.py`, `services/`: Core/Persistence
- `backend/lifeos/planning.py`, `runtime.py`, `policy.py`: Planner/Runtime
- `windows-agent/`: Windows Agent
- `web/`: Web UI
- `backend/lifeos/ai.py`, `context.py`: AI/Memory
- `backend/tests/`, `windows-agent/tests/`, `web/src/*.test.ts`, security review: QA/Security

An agent may edit only its assigned area. Shared-contract changes are coordinated
by the principal agent. Existing user files and unrelated changes must be kept.

## Required checks

Run formatting, type checking, and the tests relevant to the changed directory.
Mocks must be named as mocks. Do not claim an acceptance item passed without a
recorded command. Real enforcement stays feature-flagged off and `dry_run=true`.

## GitHub-first reuse policy

- Before implementing a module, check the platform/framework API and then search
  maintained GitHub source for a smaller reusable implementation.
- Verify source, license, exact tag/commit, path activity, dependencies, security
  posture, and failure behavior before copying or adding a dependency.
- Record `ADOPT`, `ADAPT`, `STUDY_ONLY`, or `REJECT`, pin provenance, retain required
  notices, and add denial/timeout/replay/rollback tests around the LifeOS-owned
  typed interface.
- Never copy unlicensed snippets/gists. Default-reject GPL/AGPL and unsuitable LGPL
  coupling unless an explicit review approves it. Reuse never weakens Core
  authority, user-only replan, camera-frame privacy, or hard-action guards.


## Safety rules

- Core is the sole source of truth; agents never promote themselves to primary.
- AI output is data only and never becomes a shell, registry, or firewall command.
- Every command carries idempotency, expiry, state version, and audit fields;
  `RELEASE_ALL` deliberately has fail-open state/ACK handling.
- Any future hard action must require session pre-authorization, a current role
  lease, an online Core/device, blocklist/duration authorization, and complete
  guard tests. V1's partial hard guard is not authorization to enable enforcement.
- Never record keystrokes, clipboard contents, screenshots, microphone, or video.
