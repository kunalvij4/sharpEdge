# Acceptance status

The implementation has passed offline, PostgreSQL, and container validation. Live-account acceptance is still pending.

## Collector recovery follow-up

The collector recovery was deployed and verified against the configured account on 2026-10-19. NBA, NFL, and MLB moneylines are now persisted and served despite failed event enrichment. The current local suite has 106 passing tests, and isolated container checks pass. Player-prop odds endpoints still return unsuccessful HTTP-200 envelopes, including with valid discovered bet-type filters. See [collector recovery](collector-recovery.md) for live counts, safeguards, and remaining provider/mapping gaps. The earlier validation record below describes the original fixture-only implementation.

## Validation record — 2026-10-19

- Automated suite: **117 passed** across SQLite and disposable PostgreSQL, including concurrent reader visibility during an uncommitted board refresh.
- Ruff lint, formatting, and dependency lock consistency checks passed.
- Docker image `odds-api:phase1` built successfully.
- Docker Compose configuration validated using example configuration and a nonfunctional test key.
- Container smoke checks passed: migrations, non-root UID 10001, two API workers, product authentication, persisted moneylines/props, OpenAPI, database/API restart persistence, cached serving during a simulated provider outage, exclusive collector ownership, credential redaction, and graceful shutdown.
- Container checks used synthetic data and a closed local port for the simulated provider; **no Unabated account request was made**.
- CI includes PostgreSQL tests, image build, and the same container smoke check.
- One third-party Starlette/AnyIO deprecation warning was observed; it did not affect test results.

The standalone PostgreSQL test container and smoke resources were removed after verification. The built image remains available locally.

## Implemented

- Independent domain, application, infrastructure, and HTTP layers with explicit dependency injection.
- Persisted normalized relationships, deterministic source-based identity, atomic board refreshes, migration 0001, and optional retained snapshots.
- NBA/NFL/MLB fixed-deadline staggered scheduling, shared admission control, retries/backoff, nonoverlap, and missed-deadline accounting.
- Account metadata discovery, every discovered sportsbook, available/suspended/removed/stale handling, alternate lines, periods, player context, and unsupported mapping reporting.
- Authenticated v4 endpoints, validated public schemas and query filters, OpenAPI/Swagger, and separate HTTP/database/collection health.
- Non-root application image, persistent PostgreSQL Compose deployment, pinned dependency lock, automated tests, and CI image build.
- A continuous validation observer for real event lifecycle evidence.

## Evidence to complete at deployment

No provider secret or sanitized account response was supplied. Consequently, live account coverage, successful authentication, actual provider payload variants, real collection cadence under account limits, and continuous pregame/live/final validation remain unverified.

The fixture boards and compatibility payload are synthetic. No payload from an existing consuming application was supplied. Unknown semantics are reported conservatively; exhaustive mapping of every account-authorized prop cannot be claimed until its definitions have been inspected.

Run the documented live validation procedure and record actual sportsbook/league/market coverage gaps here. Do not mark those Definition of Done items complete solely because offline tests pass.
