# LifeOS Web V1

TypeScript/React/Vite PWA for the authoritative LifeOS Core. The UI contains no seeded or fallback business data: empty, unavailable, expired, and unknown states remain explicit.

## Run locally

```powershell
cd web
npm install
npm run dev
```

The default Core URL is `http://localhost:8000`. Override it with `VITE_LIFEOS_API_BASE` at build time or use **连接设置** in the UI. The bearer token is held in `sessionStorage`; the API base and display timezone are held in `localStorage`.

Core CORS must allow the Vite origin (`http://localhost:5173` by default). All stored timestamps remain UTC; the UI requests and formats plans with the configured IANA display timezone, defaulting to `Asia/Shanghai`.

## V1 surfaces

- Today timeline and deterministic generate/replan controls
- Task create, read, update, complete, and soft-delete/cancel flows with `expected_version`
- Device heartbeat status and current RuntimeState freshness/confidence/features
- Session start/transition/break controls and manual Session UUID recovery
- Distinct Ordinary Override and Emergency Release flows
- Append-only audit event list with reason codes, idempotency key, and payload inspection
- Prominent dry-run/live/offline safety state
- Installable shell and conservative static-only service worker cache

Emergency Release generates one idempotency key when its confirmation dialog opens and keeps it through retries. The service worker never caches `/api/*`, `/health`, or `/ready` responses.

## Verification

```powershell
npm run format:check
npm run typecheck
npm test
npm run build
```
