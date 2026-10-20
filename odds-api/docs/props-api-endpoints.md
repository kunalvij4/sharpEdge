# NBA and NFL player props

Base URL: `http://localhost:8000`. Send `X-API-Key: <your product key>` for every route below. Swagger is at `/docs`.

| Purpose | Method and path |
|---|---|
| NBA games and IDs | `GET /v4/sports/basketball_nba/events` |
| NFL games and IDs | `GET /v4/sports/americanfootball_nfl/events` |
| All supported NBA game props | `GET /v4/sports/basketball_nba/events/{event_id}/props?oddsFormat=american` |
| All supported NFL game props | `GET /v4/sports/americanfootball_nfl/events/{event_id}/props?oddsFormat=american` |
| NBA props via the existing odds route | `GET /v4/sports/basketball_nba/events/{event_id}/odds?markets=all_props&oddsFormat=american` |
| NFL props via the existing odds route | `GET /v4/sports/americanfootball_nfl/events/{event_id}/odds?markets=all_props&oddsFormat=american` |
| Selected NBA markets | `GET /v4/sports/basketball_nba/events/{event_id}/odds?markets=player_points,player_rebounds,player_assists&oddsFormat=american` |
| Selected NFL markets | `GET /v4/sports/americanfootball_nfl/events/{event_id}/odds?markets=player_pass_yds,player_rush_yds,player_reception_yds,player_receptions&oddsFormat=american` |
| Collector failures, warnings, and endpoint request counts | `GET /status` |

The `/props` route defaults to every supported prop market, including available alternate and period variants from every stored sportsbook. It accepts a comma-separated `markets` filter for a subset and `bookmakers` for a subset of books. The equivalent selector on the existing event odds route is `markets=all_props`. Unknown markets are rejected; all-props includes only mapped normalized markets, not unsupported milestone/yes-no settlement types. See the mapping table in README for the complete built-in base keys.

Example for the event supplied in the investigation:

```sh
curl 'http://localhost:8000/v4/sports/basketball_nba/events/275f9649fc6e5e69b4e35ccd890aa8e8/props?oddsFormat=american' \
  -H 'X-API-Key: YOUR_PRODUCT_KEY'
```

## Freshness and cached prices

The original event odds route now also returns eligible recently cached props when a provider refresh fails. Cache reads never change the original collection/source timestamps. The default maximum collection age is one hour (`PROPS_CACHE_TTL=3600`), and the source freshness limit and explicit upstream expiry still apply. Suspended, removed, terminal-event, and expired quotes remain excluded.

Every prop outcome has a `freshness` object containing `status` (`fresh` or `stale`), `actionable`, `collected_at`, `source_updated_at`, `expires_at`, and `age_seconds`. Cached stale outcomes have `actionable:false`; they are available for display and inspection, not classified as current actionable odds. An event-level summary and `X-Odds-Data-Status` header show `fresh`, `stale`, `mixed`, or `unavailable`.

Add `freshOnly=true` to either event endpoint to return only fresh actionable quotes. That can return an empty book list during an upstream outage. `PROPS_CACHE_TTL=0` disables the cached behavior globally. Moneylines use the original strict freshness policy.

## Unabated endpoints used

The collector enforces an explicit path allowlist for configured leagues:

| Data | Unabated route |
|---|---|
| Moneyline prices | `/market/{league}/straight/odds`, filtered by discovered moneyline bet IDs |
| Player-prop prices | `/market/{league}/props/odds` |
| Books and source status for the requested market | `/market/{league}/{straight|props}/sources` |
| Team names | `/team/{league}` |
| Player names | `/player/{league}`, only when processing props |
| League, bet, market, and period IDs | `/league`, `/bettype`, `/market-type`, `/period-type/{league}` |

Lookups are cached and identities are fetched only after the requested odds board succeeds. Event context comes from the board; the collector no longer calls `/event/{league}/upcoming`, probes other market types for sources, or requests seasons, futures, streams, bet slips, or deep links. Endpoint counters are visible in `/status` under `provider_metrics` keys such as `requests:/market/nba/props/odds`.

The routes follow the official [odds guide](https://docs.unabated.com/guides/odds) and [discovery guide](https://docs.unabated.com/guides/discovery). Provider `success:false` responses remain failures; cached serving does not claim to repair those upstream operations.

## Deployment verification, 2026-10-19

At 20:47:17–20:47:19 UTC, the rebuilt API returned:

| Query | Books | Outcomes | Status |
|---|---:|---:|---|
| Supplied Detroit–Boston event, `player_points` | 12 | 198 | Stale cached |
| Same event, all supported props | 12 | 921 | Stale cached |
| Same event, `freshOnly=true` | 0 | 0 | Unavailable |
| Washington–San Francisco NFL game, all supported props | 15 | 1,368 | Stale cached |

These are observation-time counts, not guaranteed ongoing coverage. Safe output is in `props-api-verification-2026-10-19.jsonl`; `scripts/verify_props_api.py` reproduces the checks using our API/database without contacting Unabated. The collector heartbeat was healthy and path counters contained only permitted calls.

139 offline/SQLite tests passed. They cover request allowlists, endpoint budgets, cached metadata, NBA/NFL props, alternate/period identity, strict freshness, bounded cached prices, source expiry, suspended/removed prices, and terminal events. No provider failure or API read refreshes timestamps.

The rebuilt image also passed isolated Docker checks for the all-props endpoint and freshness labels, two API workers, authentication, persisted moneylines/props, OpenAPI, database/API restart persistence, provider outage cache reads, collector ownership, credential redaction, and graceful shutdown. The production API/database were healthy, the collector was running, and migrations completed successfully. Provider operation failures remain visible in collector logs; these checks do not claim to repair Unabated's server-side processing.
