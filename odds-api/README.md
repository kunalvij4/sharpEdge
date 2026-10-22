# In-House Odds API — Phase 1

Bet365 investigation: see the [New Jersey moneyline and O/U verification](docs/bet365-nj-extraction-2026-10-21.md) for the latest capture and reproducible browser setup, the [earlier headed extraction](docs/bet365-extraction-2026-10-21.md) for the Virginia snapshot and AWS virtual-display instructions, and the [integration plan](docs/bet365-integration-plan.md) for the proposed provider architecture. The browser tools are optional and do not run inside the production API or collector.

A FastAPI service that reads persisted Unabated moneylines and player props. A separate collector discovers account metadata, normalizes boards, and commits each refresh in one database transaction. PostgreSQL is the deployment database; SQLite supports local development and offline tests.

## Start with Docker Compose

1. Copy `.env.example` to `.env`.
2. Set `API_KEYS`, `UNABATED_API_KEY`, and `POSTGRES_PASSWORD` locally. Use a URL-safe database password, or percent-encode reserved URL characters in the connection URL. Never paste provider credentials into chat or commit them.
3. Confirm your Unabated account's permitted leagues, sources, markets, request policy, and attribution requirements.
4. Run:

```sh
docker compose up --build -d
docker compose logs -f collector
```

Compose waits for PostgreSQL, runs `alembic upgrade head` in a one-shot migration service, and then starts the API and collector. PostgreSQL data lives in the `odds-data` named volume. Ordinary `docker compose down` preserves it. The API and collector image runs as UID/GID 10001. The database's server process runs as the postgres user.

Swagger UI: <http://localhost:8000/docs>. OpenAPI: <http://localhost:8000/openapi.json>. Use Swagger's Authorize button with your **product** key.

```sh
curl -H "X-API-Key: YOUR_PRODUCT_KEY" http://localhost:8000/v4/sports
curl -H "X-API-Key: YOUR_PRODUCT_KEY" "http://localhost:8000/v4/sports/basketball_nba/odds?markets=h2h&oddsFormat=american"
curl -H "X-API-Key: YOUR_PRODUCT_KEY" "http://localhost:8000/v4/sports/basketball_nba/events/EVENT_ID/odds?markets=player_points,player_rebounds&oddsFormat=american"
curl -H "X-API-Key: YOUR_PRODUCT_KEY" http://localhost:8000/status
```

An empty list before collection succeeds is expected. Inspect each scope in `/status` to distinguish an uncollected scope, an empty successful board, partial data, or a failure.

For upgrades, rebuild the image and run migrations before replacing the services:

```sh
docker compose build
docker compose run --rm migrate
docker compose up -d
```

## Local development

Python 3.12 or 3.13 and uv 0.9.4 are supported. `uv.lock` pins the full dependency graph and hashes. No provider credentials are needed to run tests.

```sh
uv sync --locked --dev
uv run alembic upgrade head
uv run uvicorn odds_api.main:app --reload --no-access-log
```

Run the collector in another terminal:

```sh
uv run python -m odds_api.collector
```

The local default database is `sqlite:///./odds.db`. Set `API_KEYS` in your environment or `.env` before starting the API. Multiple local collectors are prevented by an OS file lock beside the SQLite database. SQLite is intended for a single host. Use PostgreSQL for replicas.

```sh
uv run ruff check .
uv run ruff format --check .
uv run python -m pytest -q
```

Exercise a built image without provider credentials:

```sh
uv run python -m scripts.smoke_container --image odds-api:phase1
```

This creates and cleans up its own disposable containers and network, seeds synthetic odds, verifies two API workers, restarts the database/API, and simulates a provider outage using a closed local port. It never contacts Unabated.

Set `TEST_DATABASE_URL` to an **empty disposable PostgreSQL database** to run repository and API tests against both backends. The test fixture downgrades and recreates that test database's application schema. CI provisions its own PostgreSQL database, runs the suite, and builds the Docker image.

## API contract

| Endpoint | Behavior |
|---|---|
| `GET /v4/sports` | Configured leagues, including NBA, NFL, and MLB by default |
| `GET /v4/sports/{sport}/events` | Pregame/live/delayed/postponed events |
| `GET /v4/sports/{sport}/odds` | Actionable moneylines across events |
| `GET /v4/sports/{sport}/events/{event_id}/odds` | Moneylines and selected props; cached props carry explicit freshness labels |
| `GET /v4/sports/{sport}/events/{event_id}/props` | All supported player props, including alternates and periods, from every stored book |
| `GET /status` | Collection success/failure, lag, misses, warnings, counts, rate limits, freshness |
| `GET /health/live` | Process liveness |
| `GET /health/ready` | Database connectivity and migration revision |

All product endpoints require `X-API-Key` or the compatibility query parameter `apiKey`. Health endpoints, Swagger, and the OpenAPI schema are public. Query-string keys can appear in proxy logs; use the header and keep access logging disabled or redact `apiKey` in your proxy. Compose does not pass the provider secret into the API service.

Both odds endpoints accept comma-separated `markets` (default `h2h`) and `bookmakers`, plus `oddsFormat=decimal|american` (default decimal). Props must be requested from the event endpoint. Event and odds queries accept inclusive `commenceTimeFrom` and `commenceTimeTo` bounds with an explicit UTC offset. Unknown sports/events return 404; unknown bookmakers, unsupported markets, invalid dates, invalid formats, reversed bounds, and unsupported parameters return 422. Missing/invalid product credentials return 401. A not-ready internal dependency returns 503 on readiness.

For every supported prop on a game, use `/v4/sports/basketball_nba/events/{event_id}/props?oddsFormat=american` or `/v4/sports/americanfootball_nfl/events/{event_id}/props?oddsFormat=american`. The equivalent event odds query is `?markets=all_props&oddsFormat=american`. The props route defaults to `markets=all_props` and accepts the same bookmaker, market, date, and format filters. To request one or several prop types, use e.g. `?markets=player_points,player_rebounds` for NBA or `?markets=player_pass_yds,player_receptions` for NFL. Game IDs come from the matching sport's `/events` endpoint. All-props means all supported normalized prop keys; unsupported settlement types still appear as collector warnings.

Props can now include recently cached prices during an upstream outage. The default `PROPS_CACHE_TTL=3600` bounds their collection age to one hour; `SOURCE_TTL` and explicit source expiry remain enforced. Each prop outcome includes `freshness.status`, `actionable`, `collected_at`, `source_updated_at`, `expires_at`, and `age_seconds`. Stale cached prices have `actionable:false`. The response's `freshness` object summarizes fresh/stale counts; `X-Odds-Data-Status` repeats its status. These timestamps are never refreshed by reading the API or by a failed collection. Add `freshOnly=true` to either event route for fresh actionable prices only. Set `PROPS_CACHE_TTL=0` to disable cached props globally. Moneylines continue to use the strict collection freshness limit.

Responses use events → bookmakers → markets → outcomes. Player over/under outcomes have `name`, `price`, `point`, and player `description`. American odds are integers; decimal prices are rounded to four places. All serialized times are UTC.

### Compatibility differences

This implements the Phase 1 subset of [The Odds API v4](https://the-odds-api.com/liveapi/guides/v4/); it is not a complete drop-in replacement.

- Internal event IDs are deterministic UUID5 hex strings derived from league key and provider event ID. They do not equal The Odds API's IDs.
- Bookmaker keys are stable `unabated_<source-id>` identifiers. Source names can change without changing a key. Every discovered account-authorized source is considered; there is no book-name allowlist.
- `last_update` is null when individual source timestamps are absent. It is never synthesized from collection time. When grouped, it is the newest known source timestamp among included outcomes; it does not imply every outcome changed then.
- Region filters, scores, futures, historical endpoints, dateFormat, quota/billing headers, and event/market discovery endpoints beyond the required subset are not implemented. Unsupported query parameters are rejected.
- Suspended, removed, explicitly expired, source-expired, and final/cancelled/unknown-event quotes are excluded. Stale props within the bounded cache policy are returned with explicit non-actionable labels unless `freshOnly=true`; stale moneylines remain excluded. Known events with no eligible prices return `bookmakers: []`.
- Freshness is reported separately in `/status` and `X-Odds-Observed-At`, `X-Odds-Collected-TTL`, and `X-Odds-Source-TTL` headers. The observed-at header is the API observation time, not an upstream update time.
- Periods and alternate lines have distinct public market keys as described below. Outcome arrays may contain multiple points for a player.
- Fixtures in `tests/fixtures` are synthetic examples based on the documented hierarchy. No actual existing consumer payload or account response was supplied; replace/add sanitized real fixtures during acceptance validation.

## Mapping player props and periods

Mappings use **IDs obtained from discovery**, resolved through explicit semantic names. No numeric league/book/bet/period IDs are inferred from display names or composite dictionary keys. League route names in `LEAGUES_JSON` are matched against discovered route names, then their returned numeric IDs are used to validate boards.

The exact built-in name aliases are maintained in `odds_api/infrastructure/normalization.py`. Supported families include:

| Provider bet definition | Public base key |
|---|---|
| Moneyline | `h2h` |
| Player Points / Points | `player_points` |
| Player Rebounds / Rebounds | `player_rebounds` |
| Player Assists / Assists | `player_assists` |
| Points + Rebounds + Assists | `player_points_rebounds_assists` |
| Points + Rebounds / Points + Assists / Rebounds + Assists | `player_points_rebounds` / `player_points_assists` / `player_rebounds_assists` |
| Three Pointers Made / 3 Pointers Made | `player_threes` |
| Steals / Blocks / Turnovers | `player_steals` / `player_blocks` / `player_turnovers` |
| Passing Yards / Touchdowns / Attempts / Completions / Interceptions | `player_pass_yds` / `player_pass_tds` / `player_pass_attempts` / `player_pass_completions` / `player_pass_interceptions` |
| Rushing Yards / Attempts | `player_rush_yds` / `player_rush_attempts` |
| Receiving Yards / Receptions | `player_reception_yds` / `player_receptions` |
| Rushing + Receiving Yards | `player_rush_reception_yds` |
| Hits / Total Bases / Home Runs / Runs / Runs Batted In / Batter Walks | `batter_hits` / `batter_total_bases` / `batter_home_runs` / `batter_runs_scored` / `batter_rbis` / `batter_walks` |
| Pitcher Strikeouts / Outs Recorded / Hits Allowed / Earned Runs | `pitcher_strikeouts` / `pitcher_outs` / `pitcher_hits_allowed` / `pitcher_earned_runs` |

Generic ambiguous definitions such as just “Strikeouts” require an explicit ID override after checking their meaning. Only player selections with discovered player context and over/under side indexes are normalized as props. Yes/no, touchdown scorers, combos outside the mapped families, team props, nonempty bet subtypes, and unknown periods are reported as unsupported, rather than guessed. Verified MLB aliases include `RBIs`, `Pitcher Outs`, `Pitcher Hits Allowed`, `Pitcher Earned Runs`, and `Hitter Walks`. Lines missing the points needed for an over/under are skipped with `missing_prop_points` warnings; valid selections and alternate lines still update in a partial refresh.

Override or add verified mappings without editing code:

```dotenv
UNABATED_BET_TYPE_MAP={"12345":"player_points","67890":"pitcher_strikeouts"}
UNABATED_PERIOD_MAP={"123":"full","456":"q1"}
```

The IDs above are placeholders; replace them with account discovery results. Period names map to `full`, `q1`–`q4`, `h1`, `h2`, the first three/five/seven innings (`1st_3_innings`, `1st_5_innings`, `1st_7_innings`), or individual innings (`1st_1_innings` through `9th_1_innings`). Full game has no suffix; other periods append `_<period>`. Alternates append `_alternate` before the period suffix. For example: `player_points`, `player_points_q1`, and `player_points_alternate_q1`. These period/alternate key combinations are local extensions; consumer support must be checked.

## Collection, persistence, and freshness

Default deadlines repeat every 30 seconds from collector startup:

| Offset | League | Scope |
|---|---|---|
| 0s | NBA | Moneylines |
| 5s | NBA | Props |
| 10s | NFL | Moneylines |
| 15s | NFL | Props |
| 20s | MLB | Moneylines |
| 25s | MLB | Props |

Monotonic deadlines advance from the previous scheduled deadline. A running scope is skipped and counted as a missed deadline. After a pause, only the latest due refresh is attempted; older cycles are counted rather than replayed. The shared limiter still paces recovery and retries. Discovery startup, latency, retries, and request-policy constraints can delay actual requests; monitor scheduling lag. The cadence describes collection attempts, not guaranteed data freshness.

One limiter controls all provider HTTP calls, using a configurable general admission interval and a separate odds interval. Every retry passes through it. 429/5xx and transport errors have bounded exponential backoff; valid numeric and HTTP-date Retry-After values defer shared admission. 401, coverage denials, unsupported requests, and unsuccessful provider envelopes fail safely without exposing upstream error bodies. They do not erase stored boards. No tier fallback is attempted.

Odds HTTP calls are serialized across all scopes, with the configured odds interval measured from completion. Waiting odds requests do not hold the shared admission lock, so discovery can proceed under its own general limit. Admission rechecks shared cooldowns after waking. The six 30-second schedule deadlines remain fixed; slow responses, the completion interval, or provider errors can delay admission and cause recorded missed cycles. On Free API, six calls plus their response times may exceed one cycle; the collector does not increase request frequency to catch up.

The [Unabated discovery guide](https://docs.unabated.com/guides/discovery) identifies lookup endpoints for leagues, sources, bet definitions, periods, people, teams, and events. Relatively static metadata is refreshed hourly; scope metadata every five minutes by default. Boards discover new events/lines on each fetch. A source/player/team not yet in cached discovery causes safe preservation until discovery catches up. Scope metadata TTL can be lowered.

A confirmed complete board atomically updates current odds and marks previously present but missing selections removed within that league and board kind. Nonempty upstream messages or unsupported mappings make a board partial, suppressing removals. Malformed/incomplete structures and unresolved required identities fail the refresh. Partial boards can update valid mapped prices without deleting missing prices. Successful empty boards are distinct from failures. Both source line IDs and internal IDs are stored separately; alternate point values and period/player/book context participate in market identity.

Availability has available, suspended, removed, and stale states. Staleness is calculated at read time from:
- time since collection exceeding `COLLECTED_TTL`;
- a known source modification exceeding `SOURCE_TTL`;
- an explicit upstream freshness expiry.

A missing source timestamp stays null. A fresh collection can contain an old source update. The [response concepts guide](https://docs.unabated.com/guides/response-concepts) distinguishes individual line timestamps and source status from board-level timestamps. The board's lastUpdated value is never assigned to every line. Completed and cancelled event quotes are excluded even if an old line remains in storage.

The collector permits only `/league`, `/bettype`, `/market-type`, `/period-type/{league}`, `/team/{league}`, `/player/{league}`, and `/market/{league}/{straight|props}/{odds|sources}` for configured leagues. The actual odds calls are moneylines from `/market/{league}/straight/odds` with discovered moneyline bet IDs and player props from `/market/{league}/props/odds`. The complete props board preserves unsupported-mapping warnings rather than silently narrowing coverage. Discovery data is cached; `/status.provider_metrics` reports outgoing request counts by path.

There is no upcoming-event enrichment, cross-market sportsbook fallback, or speculative season/futures/deeplink request. Events, starts, and lifecycle state come from the odds board. Teams and players are resolved directly from their documented league catalogs, while sportsbook metadata comes from the requested market type's own sources endpoint. Odds authorization must succeed before identities are fetched. Book status, props status, and disabled market-type IDs remain enforced. Unresolved books, players, or individual event contexts are reported and skipped without blocking other valid quotes, making the board partial and preserving absent stored prices.

For a partial refresh, `/status` updates `last_attempt`, `selection_count`, and warnings. `last_success` advances only for complete refreshes. Structured logs include the failing provider path and HTTP status, a safe validation category, and bounded warning codes; raw upstream error bodies and credentials are omitted.

Optional snapshot retention is disabled with `SNAPSHOT_RETENTION_DAYS=0`. When enabled, normalized quote snapshots are stored and older snapshots pruned during collection transactions. Current odds are always persisted.

## Ownership, shutdown, and operations

API workers never start collection or synchronously contact Unabated. A dedicated collector owns a PostgreSQL session advisory lock. A second collector exits instead of creating a schedule. An ownership-connection failure terminates collection. In-flight jobs are cancelled and awaited before releasing ownership and closing the HTTP client/database. Do not share the same provider key across separate databases or unrelated deployments; their rate limiters would not coordinate.

HTTP liveness, database readiness, collector heartbeat, and per-scope provider health are separate. A provider outage does not make healthy persisted reads depend on the provider. Old prices are served only while within the configured freshness policy. Structured collector logs include league, scope, run ID, duration, selection count, and outcome; provider exception messages, response bodies, headers, and signed URLs are not logged.

Configuration is documented in `.env.example`. To add a league, extend `LEAGUES_JSON` with its public key, title, and discovered route. Scheduling divides the cycle into two slots per league. Check that the configured interval and the provider's limits can accommodate the new number of requests; no orchestration or schema rewrite is needed.

## Provider terms and acceptance validation

This integration follows the [quickstart](https://docs.unabated.com/start/quickstart), [odds guide](https://docs.unabated.com/guides/odds), [errors and limits](https://docs.unabated.com/guides/errors-and-limits), and [machine-readable API contract](https://data.unabated.com/swagger/v1/swagger.json).

Available datasets depend on the account's access tier and agreement. Some response fields and books may be absent. The implementation respects 403s and discovered disabled/offline sources and never switches datasets to work around restrictions. Account-specific sportsbook coverage, prop coverage, latency, and unmapped definitions must be recorded during live validation.

Returned selection links are stored with their exact line. `UNABATED_PARTNER_CODE` replaces/adds `utm_campaign` only on HTTPS Gambly links; alternate lines never inherit the main line's URL. Links are not added to the core v4 payload. A publisher that exposes stored links must satisfy its own attribution/display terms and test partner attribution on its platform. No separate deeplink-generation endpoint is called. The quickstart documents partner tracking; your provider agreement remains authoritative.

Observe a continuous run while the collector operates:

```sh
uv run python -m scripts.validate_run --seconds 7200 --output validation.json
```

Point `DATABASE_URL` at the database being collected. The observer reads persisted data and records event state transitions, collection status, counts, and whether a single event was seen pregame, live, and final. It does not call Unabated. Run across actual scheduled games; elapsed time alone cannot establish lifecycle coverage.

Before claiming deployment acceptance:
- Verify all six scope schedules and actual lag under the account's request policy.
- Compare discovered source/market coverage against the configured account.
- Add sanitized real provider fixtures and representative existing consumer payloads.
- Resolve/review every reported unsupported mapping or document the coverage gap.
- Capture pregame → live → completed transitions and suspended/relisted lines.
- Verify restart persistence, multiple API workers, collector ownership, and provider outage behavior.
- Verify partner-link attribution if links are published.

See `docs/acceptance-status.md` for the current validation record.
