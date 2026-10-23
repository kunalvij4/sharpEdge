# Bet365 in the application container

`docker compose up --build --detach` runs one application container with FastAPI,
Unabated collection, Bet365 collection, and Xvfb. PostgreSQL retains its existing
volume and schema. The one-shot migration container exits before startup.

The Python supervisor restarts failed child processes independently. Unabated's
existing polling schedule, request limiter, database lease, and heartbeat remain
in force. Bet365 uses at most two simultaneous headed Edge sessions; collection
never runs in HTTP handlers. The browser uses the existing seccomp profile and
non-root user. Use Linux/amd64 on AWS and `TZ=America/New_York`.

Matching queries restrict support lookups to candidate events/players/markets.
Application database connections disable PostgreSQL parallel gather workers to
avoid concurrent hash joins exhausting Docker's shared-memory allocation. The
database service reserves 256 MB shared memory for other database operations.

Bet365 refreshes remove only its own prices for successfully captured market
types. Unabated refreshes remove only Unabated prices. Both writers lock the
league before committing, and an intersection check inside that transaction
rejects props whose other-book support disappeared during matching. Query-time
checks also enforce bounded support and pregame status. Bet365 cannot update
canonical event metadata or Unabated collection status.

## Coverage and matching

The collector reads NJ by default. Homepage moneylines cover the offered NBA,
NFL, and MLB fixtures. NBA Points O/U uses the league board. NFL passing yards,
passing touchdowns, receiving yards, and rushing yards use the homepage's first
offered event. MLB pitcher strikeouts, pitcher outs, and hits use the first
offered event. These are partial source coverage, not every Bet365 market/game.
Unavailable tabs fail independently and leave existing prices to expire.

The adapter joins only a unique pregame canonical fixture with matching home
and away teams. Abbreviated US city names are supported. The raw Bet365 kickoff
is a date-range check only; the canonical provider supplies the API kickoff and
lifecycle. Ambiguous doubleheaders are rejected. Players match an exact
normalized full name within the same event, market, side, and point, with a
unique existing player ID. No fuzzy player matching or inferred milestone lines
are used. Every accepted prop keeps the canonical API name, description, player
ID, period, point, and alternate flag. Bet365 prices and source selection/market
IDs replace the corresponding provider fields. Source modification/deep-link
fields stay null when unavailable.

Source selection IDs, odds, player order, and O/U columns are verified against
captured HTTP records before ingestion. WebSocket deltas are excluded.

## Freshness and operations

`BET365_ENABLED=true`, `BET365_REGION=nj`, `BET365_INTERVAL=90`, and
`BET365_MAX_AGE=150` are defaults. Attempts target 90 seconds per job; navigation
and queued browser work can delay completion. Captured prices retain their
original receive timestamps and expire after 150 seconds or at canonical game
start, whichever comes first. The API uses this bound for Bet365 freshness;
the existing books keep `COLLECTED_TTL`. Bet365 never enters the hour-long props
cache beyond its explicit expiry. `X-Odds-Bet365-TTL` reports its limit.

`GET /v1/status` retains existing collector/scopes fields and adds `bet365.jobs`
with each job's state, last attempt/success, counts, and duration. Current JSON,
screenshots, and raw references live at `/app/artifacts/bet365/<job>/runs/`;
three runs per job are retained, including their disposable browser profiles.
An old verification file is never imported as a new live capture.

Use `bookmakers=bet365` on existing odds/props endpoints to inspect the new book.
`python -m scripts.check_integrated_api` inside the application container saves
real HTTP response samples to `/app/artifacts/integration-api.json` and prints
credential-free counts. `BET365_ENABLED=false` disables browser collection.

When upgrading a deployment with the former separate `collector` service,
prepare the new image first, then stop that collector and start the combined
application. Its supervisor retries the existing exclusive lease during a
handover. Do not leave the old collector running: older versions replace whole
boards and can remove Bet365 prices. Keep the database volume.

The active implementation consists of `odds_api/bet365_collector.py`, its
canonical adapter and shared runtime helpers in `odds_api/infrastructure/`, and
the capture/browser/normalization/verification modules in `scripts/`. Historical
standalone containers and generic research probes have been retired. The
container smoke check, API response check, and collection-isolation check remain
available for deployment verification.
