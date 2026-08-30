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

## Target NAS, SSH, camera, and real-enforcement boundary

The V2 topology uses NAS Core behind the user's always-on authenticated VPN. Web
uses a TLS gateway; Windows and iOS use a forced `lifeos-bridge` SSH subsystem.
Device keys are paired out of band, pinned to the verified SongNAS host key,
device-bound, scoped, rotated/revoked, and cannot open shell, PTY, SFTP, forwarding,
arbitrary filesystem or database access.

AI and self-evolution outputs are typed proposals. They never become code, shell,
registry/firewall input, leases, blocklists, retention changes, Emergency behavior
or user replan commands. Learning model revisions are immutable, validated,
audited, selectable and rollback-capable.

LifeOS Windows may eventually reuse transactional hosts/HKLM URL policy and exact
process termination from the user's V4.2 controller. Those actions stay disabled
until target/Session/commitment/state/TTL/idempotency/blocklist/duration/online
Core+device/lease/capability/rollback/audit guards and every Emergency/rest/restart
failure test pass. Local Emergency is immediate and has no phrase, AI or network
precondition.

iOS camera use is explicit, foreground-only and on-device. AVFoundation/Vision
buffers are throttled and immediately discarded. No frame, thumbnail, video,
embedding, face identity, emotion, document content or crash attachment is stored
or uploaded. Only bounded presence/orientation/away-duration/coverage/confidence/
validity/reason evidence leaves the Vision boundary. Denial, suspension, occlusion,
phone removal, failure or low confidence is `UNKNOWN`.

With a free Apple Personal Team, V2 uses local `UserNotifications`; APNs is not a
required or guaranteed channel. Lock-screen text is generic. Windows remains the
independent reminder fallback.

Personal histories, summaries, task profiles, model/plan/Session/audit revisions
are retained permanently by user decision and partitioned by date. Detailed
decision context reads the latest 72 hours by default. Camera frames never enter
retention. High-frequency evidence is encrypted, growth-monitored, exportable and
kept out of ordinary AI prompts. Test/fixture data is deleted after formal release
freeze.

Same-NAS snapshots/local copies are one failure domain and must be labelled as such;
they are not disaster recovery against total NAS loss.

## V1 security limitations

TLS termination, per-user identity, encrypted agent queue, signed command envelopes,
key rotation, and automatic retention jobs are deployment/V2 work. V1 must be
bound to loopback or a trusted private development network and must not be exposed
directly to the Internet. The EventLedger is append-only by application-service
convention; V1 does not install a database trigger or separate write-denied role.
