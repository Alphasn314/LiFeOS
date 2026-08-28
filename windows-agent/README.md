# LifeOS Windows Agent V1

This package is a deliberately limited Windows client. It collects only the
foreground process name, truncated window title, idle duration, lock state,
session metadata, and heartbeats. It never reads keystrokes, clipboard content,
screenshots, microphone, or video.

V1 capabilities are notifications, confirmations, audited `WOULD_BLOCK`, and
idempotent `RELEASE_ALL`. There is no process termination, shell/PowerShell,
registry, firewall, task-scheduler, autostart, or permanent restriction code.

Configuration is provided with environment variables:

- `LIFEOS_CORE_URL` (default `http://127.0.0.1:8000`)
- `LIFEOS_DEVICE_ID` (optional UUID; a stable local UUID is derived if omitted)
- `LIFEOS_DEVICE_NAME` (optional display name; defaults to the Windows host name)
- `LIFEOS_DEV_TOKEN` (optional bearer token; never persisted)
- `LIFEOS_AGENT_DB` (optional SQLite queue path)
- `LIFEOS_HEARTBEAT_SECONDS` (default and minimum `15`)
- `LIFEOS_SAMPLE_SECONDS` (default `5`)
- `LIFEOS_COMMAND_POLL_SECONDS` (default `5`)

Run locally with `lifeos-windows-agent`. The package does not install or register
itself for automatic startup.

Before every activity sample, the Agent asks Core for this device's active
session. A `200` assignment is attached to the observation, while an authoritative
`204` clears it. If Core or the network is unavailable, the last known assignment
is retained so queued observations keep their original session context.

Sampling and heartbeat cycles first idempotently enroll the stable device UUID.
Concurrent cycles share one enrollment request. If enrollment is unavailable,
observations and heartbeats still enter the SQLite outbox and enrollment is
retried on the next cycle.
