# Security and privacy

## Threat boundary

Core accepts bearer-token-protected client data in local deployment, but treats
every payload, AI response, window title, and command acknowledgement as untrusted
input. The shared token authenticates access, not an individual device identity.
V1 local development uses one explicit bearer token. The application does not automatically
reject the well-known development default, so the operator must replace it before
any non-loopback use. Server-side secrets are environment variables and are not
committed; Web keeps its bearer token in sessionStorage. An explicitly empty Core
token disables authentication, so that setting is suitable only for controlled tests.

## Command safety

AI can request a structured suggestion only. It has no code path to a shell,
PowerShell, registry, firewall, task scheduler, or process adapter. Policy creates
typed command payloads from a closed enum. The Windows capability adapter handles
that enum and rejects unknown fields/actions. V1 only implements notifications,
prompts, `WOULD_BLOCK`, and `RELEASE_ALL`; real enforcement is absent.

Commands carry target, time window, required state version, idempotency, and audit
fields. Ordinary commands are checked against TTL/current state; `RELEASE_ALL`
intentionally bypasses state/late-ACK restrictions so release can fail open. V1
does not create real hard commands. The partial hard-row branch checks global
flags, device reachability and a lease, but complete session/preauthorization/
blocklist/duration/lease-state validation remains a V2 blocking requirement. The
Agent supports configurable clock-skew tolerance in its local validator; Core does
not implement a general clock-skew detector. The Agent SQLite queue is plaintext.
Failed rows may retain process/window-title evidence indefinitely: V1 has no
automatic retention, dead-letter policy, attempt ceiling, or capacity limit. It
contains no keystrokes, clipboard, screenshots, microphone, or video.

## Data minimization and retention

Window titles may contain sensitive text. The Agent truncates them to 256
characters, but V1 Core does not hash or redact them by profile. No automatic
retention/deletion job or effective 30/365-day default is implemented. A future
policy may use 30 days for raw observations and 365 days for commands/events, but
that is a proposal, not current behavior. FeatureSnapshot rows are derived records,
but V1 guarantees no exact historical rebuild: task app rules can change and no
versioned reconstruction workflow exists. No automatic summary workflow exists.

## API controls

- Pydantic rejects unknown fields on safety contracts.
- Safety fields and many strings/lists are bounded by Pydantic/contracts; V1 has
  no explicit global HTTP request-body size middleware.
- Version and idempotency conflicts are 409; missing/invalid shared bearer auth is
  401. V1 does not emit a distinct 403 authorization response.
- CORS origins are an explicit configuration list.
- Application audit events omit auth tokens and full observation payloads; reverse
  proxy/server access-log configuration remains an operator responsibility.
- Emergency Release has a dedicated, minimal transaction path.

Docker Compose requires explicit database/API secrets and binds PostgreSQL, Core,
and Web published ports to `127.0.0.1`. The development credentials in
`.env.example` are placeholders and must be replaced before startup.

## Target NAS, SSH, and mobile boundary

The V2 three-part topology uses a NAS-hosted Core behind trusted LAN or an
authenticated VPN. Web uses a TLS gateway. Windows and native iOS use SSH only
through a forced `lifeos-bridge` subsystem. Application keys cannot open a shell,
PTY, SFTP, agent/X11 forwarding, port forwarding, or arbitrary filesystem access.
Each Ed25519 key is independently enrolled, device-bound, scoped, rotated, revoked,
and protected by Windows CNG/DPAPI or iOS Keychain/Secure Enclave. Clients pin the
NAS host key. A QTS administrator session is an operator boundary, not an
application credential.

The bridge authenticates the SSH principal, replaces any claimed client identity
with the enrolled identity, validates bounded NDJSON, and calls Core services.
Clients never connect to PostgreSQL. Production exposes no PostgreSQL host port,
rejects blank/default authentication, restricts CORS to the deployed Web origin,
redacts credentials, rate-limits ingress, and keeps database/API secrets out of
images, repositories, URLs, notifications, and logs.

iOS push payloads contain only an opaque wake/event identifier and expiry. Push
delivery is neither authorization nor committed state. Raw process/title evidence,
human-state reports, experiments, and backups inherit explicit retention and
access policies; experiment features expire sooner than audit facts. Device
credentials authorize API scopes, while `DeviceRoleLease` remains a separate,
Core-issued domain authorization. Neither a credential, NAS availability, VPN,
nor a lease completes the missing real-enforcement guard.


## V1 security limitations

TLS termination, per-user identity, encrypted agent queue, signed command envelopes,
key rotation, and automatic retention jobs are deployment/V2 work. V1 must be
bound to loopback or a trusted private development network and must not be exposed
directly to the Internet. The EventLedger is append-only by application-service
convention; V1 does not install a database trigger or separate write-denied role.
