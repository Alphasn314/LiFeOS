# ADR-0002: V1 enforcement is structurally dry-run

- Status: Accepted for V1 contract freeze
- Date: 2026-08-28

## Decision

V1 does not implement process termination, restart prevention, registry, firewall,
task-scheduler, administrator, or autostart capabilities. Policy still exercises
authorization, escalation, command expiry, state binding, auditing, acknowledgement,
override, and Emergency Release, but a block action is serialized as
`WOULD_BLOCK` with `dry_run=true`.

## Consequences

The closed-loop logic and safety guard can be tested without risking the user's
machine. V2 real adapters will require a new ADR, explicit feature flag, lease,
pre-authorized blocklist, bounded duration, and dedicated failure tests.

