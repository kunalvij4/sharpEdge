## Redis / combined-provider deployment

The default deployment stores current odds from Propline and Unabated in hosted
Redis. Copy `.env.example` to `.env`, supply the full TLS `REDIS_URL`, product
`API_KEYS`, `UNABATED_API_KEY`, and `PROPLINE_API_KEY`, then run from this directory:

```sh
docker compose up -d --build --remove-orphans
```

This replaces the former PostgreSQL/migration containers without deleting their
volume. Old SQL odds are not migrated. Unabated supplies canonical event IDs;
Propline prices are joined after discovery, including on a fresh Redis store.
Collection alternates Propline and Unabated every four minutes, so each provider
repeats every eight minutes. Each Unabated slot collects straight odds and props;
each Propline slot makes one bulk call per configured supported league.
Both providers retain separate selections: refreshing Unabated does not replace
or remove Propline bets. Set `UNABATED_ODDS_ENABLED=false` only to use Unabated
for event/team metadata instead of odds.

PropLine's bulk odds request filters bookmakers upstream with `bookmakers=`.
The same single request per league retrieves game lines and props from the
configured books, reducing the payload before JSON/model validation and
normalization. The configured PropLine keys are:

```text
onexbet,bet25,bet99,betfair_ex,betmgm,betrivers,betus,bookmaker_eu,bovada,
courtside,draftkings,fanatics,fanduel,fliff,hardrock,kalshi,novig,pinnacle,
polymarket,polymarket_us,prophetx,rebet,thescorebet,thrillzz
```

These are the documented keys for the requested bookmakers. PropLine's
[full reference](https://prop-line.com/llms-full.txt) identifies `thescorebet`
as the Ontario book; it does not document separate TheScore US/CA keys or a
Caesars bookmaker key. Those entries need confirmed provider support before
they can be requested. Book/market availability varies by league. This filter
applies to PropLine collection; existing stored quotes retain their original
timestamps and expiry, and Unabated collection keeps its existing behavior.

Redis holds compressed event JSON in the API's bookmaker/market/outcome shape.
The collector prepares prices and grouping; API reads apply filters and current
freshness without reconstructing domain quotes. Existing flat records remain
readable and upgrade on collection. See [Redis response storage](deploy/redis-response-storage.md)
for the format, benchmark, migration, and rollback commands. Updates use
bounded batches of optimistic transactions, preserve prior observations on partial/stale responses,
and expire event documents at kickoff. Redis must support WATCH/MULTI/EXEC,
Lua locks, and TLS for remote connections. Use a persistent, non-evicting Redis service if restart durability
is required. Local Redis is optional (see below). The application image
builds for the host architecture to avoid forced amd64 emulation on Apple Silicon.

Event documents use lossless compression to keep both providers' quotes within
the Redis memory limit. Startup compresses existing documents atomically before
starting the API and collectors, preserving every quote and its original expiry.
Plain JSON remains readable during migration. Redis 7 or newer is required for
safe memory recovery when the store is already full. Older images without
compressed-document support cannot read migrated event documents.

The URL is secret configuration; never commit `.env`. Redis connection URL behavior:
https://redis.io/docs/latest/develop/clients/connection-urls/

### Self-hosted Redis on a 4 GB / 2 vCPU server

The local override adds Redis with `maxmemory 512mb`, a 1 GB container limit,
and `noeviction`. It uses the existing zlib-compressed event documents and
kickoff expiration. Redis is reachable only on an internal Docker network shared
with the API; port 6379 is not published. This endpoint is not accessible to Lambda.

Set `REDIS_URL=redis://redis:6379/0` in `.env`, then run:

```sh
docker compose -f compose.yaml -f compose.local-redis.yaml up -d --build
```

Use both Compose files for subsequent commands. For GitHub deployments, the script adds `ODDS_REDIS_MODE=local` to the
server's `.env` when the mode is absent, then selects the override and local URL
automatically, even if an old hosted URL remains in the file. Set
`ODDS_REDIS_MODE=external` explicitly to keep using hosted Redis. Local mode does not require the `ODDS_REDIS_URL` GitHub secret.

Persistence is disabled: a Redis restart loses cached odds and collector state.
Providers refill the store on their collection schedule; coverage is incomplete
until collection succeeds. Existing hosted data is not copied. Do not use this
instance for durable data or the Lambda opportunity cache. At the memory limit,
writes fail rather than evicting event documents or indexes.

Measure a peak collection cycle and concurrent API requests before increasing
the budget: decompressed Python objects consume additional API memory. The 1 GB
container limit leaves about 3 GB for the application, OS, and headroom; it is
not a guarantee that the combined workload fits. Inspect with:

```sh
docker compose -f compose.yaml -f compose.local-redis.yaml stats --no-stream
docker compose -f compose.yaml -f compose.local-redis.yaml exec redis redis-cli INFO memory
docker compose -f compose.yaml -f compose.local-redis.yaml exec redis redis-cli INFO stats
```

Watch `used_memory`, `used_memory_rss`, peak usage, errors, and API latency.
The GitHub inspection workflow also reports Redis RSS, peak usage, and evictions.
Keep the Redis container limit above `maxmemory` to allow allocator and buffer
overhead. Enabling persistence requires revisiting the memory budget.

Legacy SQL operation is still available with `STORAGE_BACKEND=sql`, `DATABASE_URL`,
and Alembic migrations. The older deployment sections below describe that setup.

# In-House Odds API — Phase 1

The API combines Unabated and PropLine for **NHL, NBA, NFL, MLB, and NCAAF**.
One supervised collector runs PropLine at minute 0, Unabated at minute 4, then
PropLine at minute 8. Each provider repeats every eight minutes. Moneylines,
spreads, and supported player props share the same event catalog and API.
See [PROPLINE.md](PROPLINE.md) for identity matching, freshness, quota, and operations.

Bet365 runs independently through `compose.bet365.yaml` and `Dockerfile.bet365`.
It saves captures for review and has no database connection or API integration.
The main image contains no browser or Playwright dependencies.

## Start with Docker Compose

For automatic GitHub image builds and manual deployment to the production server,
see [GitHub deployment setup](deploy/README.md).

1. Copy `.env.example` to `.env`.
2. Set `API_KEYS`, `UNABATED_API_KEY`, `PROPLINE_API_KEY`, and `POSTGRES_PASSWORD` locally. Use a URL-safe database password, or percent-encode reserved URL characters in the connection URL. Never paste provider credentials into chat or commit them.
3. Confirm your Unabated account's permitted leagues, sources, markets, request policy, and attribution requirements.
4. Run:

```sh
docker compose up --build -d
docker compose logs -f api
```

Compose waits for PostgreSQL, runs `alembic upgrade head` in a one-shot migration service, and starts the combined application container. PostgreSQL data lives in `odds-data`; collector schedule and status live in `collection-artifacts`. Ordinary `docker compose down` preserves both. The application runs as UID/GID 10001 on Linux/amd64 without a browser.

Swagger UI: <http://localhost:8000/docs>. OpenAPI: <http://localhost:8000/openapi.json>. Use Swagger's Authorize button with your **product** key.

```sh
curl -H "X-API-Key: YOUR_PRODUCT_KEY" http://localhost:8000/v1/sports
curl -H "X-API-Key: YOUR_PRODUCT_KEY" "http://localhost:8000/v1/sports/nba_basketball/odds?markets=h2h&oddsFormat=american"
curl -H "X-API-Key: YOUR_PRODUCT_KEY" "http://localhost:8000/v1/events/EVENT_ID/odds?markets=player_points,player_rebounds&oddsFormat=american"
curl -H "X-API-Key: YOUR_PRODUCT_KEY" http://localhost:8000/v1/status
```

An empty list before collection succeeds is expected. Inspect each scope in `/v1/status` to distinguish an uncollected scope, an empty successful board, partial data, or a failure.

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

This creates and cleans up its own disposable containers and network, seeds synthetic odds, verifies two API workers and the supervised application runtime, restarts the database/API, and simulates a provider outage using a closed local port. It never contacts Unabated or PropLine.

Set `TEST_DATABASE_URL` to an **empty disposable PostgreSQL database** to run repository and API tests against both backends. The test fixture downgrades and recreates that test database's application schema. CI provisions its own PostgreSQL database, runs the suite, and builds the Docker image.

## API contract

| Endpoint | Behavior |
|---|---|
| `GET /v1/sports` | Configured leagues, NHL, NBA, NFL, MLB, and NCAAF by default |
| `GET /v1/sports/{sport}/events` | Events with a future commence time |
| `GET /v1/sports/{sport}/odds` | Actionable moneylines and spreads across events |
| `GET /v1/events/{event_id}/odds` | Moneylines and selected props; cached props carry explicit freshness labels |
| `GET /v1/events/{event_id}/props` | All supported player props, including alternates and periods, from every stored book |
| `GET /v1/status` | Collection success/failure, lag, misses, warnings, counts, rate limits, freshness |
| `GET /health/live` | Process liveness |
| `GET /health/ready` | Database connectivity and migration revision |

All product endpoints require `X-API-Key` or the compatibility query parameter `apiKey`. Health endpoints, Swagger, and the OpenAPI schema are public. Query-string keys can appear in proxy logs; use the header and keep access logging disabled or redact `apiKey` in your proxy. The combined application container receives the provider credentials required by its collector.

Both odds endpoints accept comma-separated `markets` (default `h2h`) and `bookmakers`, plus `oddsFormat=decimal|american` (default decimal). Props must be requested from the event endpoint. Event and odds queries accept inclusive `commenceTimeFrom` and `commenceTimeTo` bounds with an explicit UTC offset. Unknown sports/events return 404; unknown bookmakers, unsupported markets, invalid dates, invalid formats, reversed bounds, and unsupported parameters return 422. Missing/invalid product credentials return 401. A not-ready internal dependency returns 503 on readiness.

For every supported prop on a game, use `/v1/events/{event_id}/props?oddsFormat=american`. The equivalent event odds query is `?markets=all_props&oddsFormat=american`. The props route defaults to `markets=all_props` and accepts the same bookmaker, market, date, and format filters. To request one or several prop types, use e.g. `?markets=player_points,player_rebounds` for NBA or `?markets=player_pass_yds,player_receptions` for NFL. Game IDs come from the matching sport's `/events` endpoint. All-props means all supported normalized prop keys; unsupported settlement types still appear as collector warnings.

Props can now include recently cached prices during an upstream outage. The default `PROPS_CACHE_TTL=3600` bounds their collection age to one hour; `SOURCE_TTL` and explicit source expiry remain enforced. Each prop outcome includes `freshness.status`, `actionable`, `collected_at`, `source_updated_at`, `expires_at`, and `age_seconds`. Stale cached prices have `actionable:false`. The response's `freshness` object summarizes fresh/stale counts; `X-Odds-Data-Status` repeats its status. These timestamps are never refreshed by reading the API or by a failed collection. Add `freshOnly=true` to either event route for fresh actionable prices only. Set `PROPS_CACHE_TTL=0` to disable cached props globally. Moneylines continue to use the strict collection freshness limit.

Responses use events → bookmakers → markets → outcomes. Player over/under outcomes have `name`, `price`, `point`, and player `description`. American odds are integers; decimal prices are rounded to four places. All serialized times are UTC.

### Compatibility differences

This implements the Phase 1 subset of [The Odds API v4](https://the-odds-api.com/liveapi/guides/v4/); it is not a complete drop-in replacement.

This service exposes `/v1` business routes. The league keys are `nba_basketball`, `nfl_football`, and `mlb_baseball`. Event props and odds use `/v1/events/{event_id}/props` and `/v1/events/{event_id}/odds`; no sport parameter is required. Health probes remain `/health/live` and `/health/ready`. Older `/v4` routes are removed.

Events are excluded at their commence time, regardless of their upstream status. An independent maintenance process deletes commenced events and their markets, selections, and odds every second, including during provider outages. Writers also prune and reject commenced events, using the current database-write time rather than the capture time. Expired event IDs return 404. Deletion frees PostgreSQL space for reuse; normal autovacuum reclaims dead rows without a blocking table rewrite. Snapshot history remains disabled by default (`SNAPSHOT_RETENTION_DAYS=0`).

Run `alembic upgrade head` with old collectors stopped before starting the v1 service. Revision `0002` renames league references while preserving event, market, and selection IDs. Legacy league names in `LEAGUES_JSON` are translated at startup; API clients should use the new keys.

Duplicate selections use the newest source timestamp when it establishes an unambiguous quote. Conflicting selections with missing or tied timestamps are suspended individually and reported as warnings; other valid props on the board continue updating. Unoffered Bet365 tabs are skipped, while navigation failures remain visible as failures.

- Internal event IDs are deterministic UUID5 hex strings derived from league key and provider event ID. They do not equal The Odds API's IDs.
- Public bookmaker keys use normalized sportsbook names, such as `draftkings`, `fanduel`, and `bet365`, consistently across Unabated and PropLine. Bookmaker filters use these same keys. Storage identities remain provider-specific, so each feed updates only its own quotes; missing books or lines never delete the other feed’s odds. Every discovered account-authorized Unabated source is considered. Existing stored documents are projected using these public keys without a data migration.
- `last_update` is null when individual source timestamps are absent. It is never synthesized from collection time. When grouped, it is the newest known source timestamp among included outcomes; it does not imply every outcome changed then.
- Region filters, scores, futures, historical endpoints, dateFormat, quota/billing headers, and event/market discovery endpoints beyond the required subset are not implemented. Unsupported query parameters are rejected.
- Suspended, removed, explicitly expired, source-expired, and final/cancelled/unknown-event quotes are excluded. Stale props within the bounded cache policy are returned with explicit non-actionable labels unless `freshOnly=true`; stale moneylines remain excluded. Known events with no eligible prices return `bookmakers: []`.
- Freshness is reported separately in `/v1/status` and `X-Odds-Observed-At`, `X-Odds-Collected-TTL`, and `X-Odds-Source-TTL` headers. The observed-at header is the API observation time, not an upstream update time.
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

The combined collector repeats each provider every eight minutes:

| Offset | Provider | Scope |
|---|---|---|
| 0 minutes | PropLine | All five leagues, game lines and props |
| 4 minutes | Unabated | All five leagues, game lines and props |
| 8 minutes | PropLine | Repeat |

One durable schedule controls both feeds. A restart resumes the saved schedule;
slow cycles and downtime delay the next provider without skipping its turn or creating catch-up bursts. A provider
cycle completes before another starts. See [PROPLINE.md](PROPLINE.md) for the
request budget, eight-minute freshness windows, and standalone Bet365 service.

One limiter controls all provider HTTP calls, using a configurable general admission interval and a separate odds interval. Every retry passes through it. 429/5xx and transport errors have bounded exponential backoff; valid numeric and HTTP-date Retry-After values defer shared admission. 401, coverage denials, unsupported requests, and unsuccessful provider envelopes fail safely without exposing upstream error bodies. They do not erase stored boards. No tier fallback is attempted.

Odds HTTP calls are serialized across all scopes, with the configured odds interval measured from completion. Waiting odds requests do not hold the shared admission lock, so discovery can proceed under its own general limit. Admission rechecks shared cooldowns after waking. Slow responses and provider errors can cause a feed to miss its slot; the collector does not increase request frequency to catch up.

The [Unabated discovery guide](https://docs.unabated.com/guides/discovery) identifies lookup endpoints for leagues, sources, bet definitions, periods, people, teams, and events. Relatively static metadata is refreshed hourly; scope metadata every five minutes by default. Boards discover new events/lines on each fetch. A source/player/team not yet in cached discovery causes safe preservation until discovery catches up. Scope metadata TTL can be lowered.

API refreshes preserve existing markets and prices unless a valid, fresher
replacement arrives for the same selection. Empty, partial, failed, or narrower
responses do not remove absent selections, including selections from the other
provider. Replacements require a newer collection time, an available valid price,
non-expired freshness, and no regression or loss of a previously known source
observation time. Retained rows keep their original timestamps and expiration;
reading or refreshing another feed never makes them fresh again. Market, period,
player, exact line, side, book, and provider identities remain distinct. Existing
kickoff pruning and freshness rules still apply.

Availability has available, suspended, removed, and stale states. Staleness is calculated at read time from:
- time since collection exceeding `COLLECTED_TTL`;
- a known source modification exceeding `SOURCE_TTL`;
- an explicit upstream freshness expiry.

A missing source timestamp stays null. A fresh collection can contain an old source update. The [response concepts guide](https://docs.unabated.com/guides/response-concepts) distinguishes individual line timestamps and source status from board-level timestamps. The board's lastUpdated value is never assigned to every line. Completed and cancelled event quotes are excluded even if an old line remains in storage.

The collector permits only `/league`, `/bettype`, `/market-type`, `/period-type/{league}`, `/team/{league}`, `/player/{league}`, and `/market/{league}/{straight|props}/{odds|sources}` for configured leagues. The actual odds calls are moneylines from `/market/{league}/straight/odds` with discovered moneyline bet IDs and player props from `/market/{league}/props/odds`. The complete props board preserves unsupported-mapping warnings rather than silently narrowing coverage. Discovery data is cached; `/v1/status.provider_metrics` reports outgoing request counts by path.

There is no upcoming-event enrichment, cross-market sportsbook fallback, or speculative season/futures/deeplink request. Events, starts, and lifecycle state come from the odds board. Teams and players are resolved directly from their documented league catalogs, while sportsbook metadata comes from the requested market type's own sources endpoint. Odds authorization must succeed before identities are fetched. Book status, props status, and disabled market-type IDs remain enforced. Unresolved books, players, or individual event contexts are reported and skipped without blocking other valid quotes, making the board partial and preserving absent stored prices.

For a partial refresh, `/v1/status` updates `last_attempt`, `selection_count`, and warnings. `last_success` advances only for complete refreshes. Structured logs include the failing provider path and HTTP status, a safe validation category, and bounded warning codes; raw upstream error bodies and credentials are omitted.

Optional snapshot retention is disabled with `SNAPSHOT_RETENTION_DAYS=0`. When enabled, normalized quote snapshots are stored and older snapshots pruned during collection transactions. Current odds are always persisted.

## Ownership, shutdown, and operations

API workers never start collection or synchronously contact Unabated. A dedicated collector owns a PostgreSQL session advisory lock. A second collector exits instead of creating a schedule. An ownership-connection failure terminates collection. In-flight jobs are cancelled and awaited before releasing ownership and closing the HTTP client/database. Do not share the same provider key across separate databases or unrelated deployments; their rate limiters would not coordinate.

HTTP liveness, database readiness, collector heartbeat, and per-scope provider health are separate. A provider outage does not make healthy persisted reads depend on the provider. Old prices are served only while within the configured freshness policy. Structured collector logs include league, scope, run ID, duration, selection count, and outcome; provider exception messages, response bodies, headers, and signed URLs are not logged.

Unabated response decoding and normalization run in worker threads so large
props boards do not block ownership renewal. Heartbeat failures log their
exception class; interrupted collections report `cancelled`. See the
[October 30 collector incident analysis](deploy/collector-incident-2026-10-30.md)
for the reproduced defect, validation, and remaining production checks.

Configuration is documented in `.env.example`. To add a league, extend `LEAGUES_JSON` with its public key, title, and discovered route. Scheduling divides the cycle into two slots per league. Check that the configured interval and the provider's limits can accommodate the new number of requests; no orchestration or schema rewrite is needed.

## Provider terms and acceptance validation

This integration follows the [quickstart](https://docs.unabated.com/start/quickstart), [odds guide](https://docs.unabated.com/guides/odds), [errors and limits](https://docs.unabated.com/guides/errors-and-limits), and [machine-readable API contract](https://data.unabated.com/swagger/v1/swagger.json).

Available datasets depend on the account's access tier and agreement. Some response fields and books may be absent. The implementation respects 403s and discovered disabled/offline sources and never switches datasets to work around restrictions. Account-specific sportsbook coverage, prop coverage, latency, and unmapped definitions must be recorded during live validation.

Returned selection links are stored with their exact line. `UNABATED_PARTNER_CODE` replaces/adds `utm_campaign` only on HTTPS Gambly links; alternate lines never inherit the main line's URL. Links are not added to the core v4 payload. A publisher that exposes stored links must satisfy its own attribution/display terms and test partner attribution on its platform. No separate deeplink-generation endpoint is called. The quickstart documents partner tracking; your provider agreement remains authoritative.

Observe a continuous run while the collector operates:

```sh
uv run python -m scripts.validate_run --seconds 7200 --output validation.json
```

Point `DATABASE_URL` at the database being collected. The observer records upcoming events, collection status, counts, and previously observed event IDs that disappear after commence time. It does not call Unabated. Live and final states are not retained under the pregame-only policy. Run across actual scheduled start times to observe expiry.

Before claiming deployment acceptance:
- Verify all six scope schedules and actual lag under the account's request policy.
- Compare discovered source/market coverage against the configured account.
- Add sanitized real provider fixtures and representative existing consumer payloads.
- Resolve/review every reported unsupported mapping or document the coverage gap.
- Verify events disappear at commence time and their stored odds are deleted; verify suspended/relisted lines before kickoff.
- Verify restart persistence, multiple API workers, collector ownership, and provider outage behavior.
- Verify partner-link attribution if links are published.

The Docker smoke test also verifies commence-time deletion during a provider outage using synthetic data.
