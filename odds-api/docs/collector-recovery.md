# Collector recovery — 2026-10-19

## Fixed and deployed

The pasted logs recorded `provider_operation_failed` for all six collection scopes without identifying the failing endpoint. The adapter made event discovery a mandatory dependency, so even successful odds endpoints could not populate the database when event discovery failed.

The deployed collector now:

- Uses event context embedded in a successful odds board if upcoming-event enrichment is unavailable.
- Marks these refreshes partial and preserves absent stored selections. Collection timestamps and upstream timestamps retain their separate meanings.
- Caches enrichment failures for up to 30 seconds to avoid repeating failing discovery calls in every slot.
- Requires the requested odds board to succeed before fetching fallback metadata. HTTP authentication failures, coverage denials, and invalid requests remain errors.
- Uses documented league team/player catalogs and the same league's straight sportsbook catalog if props-specific identity metadata has a processing/availability failure. Props sportsbook status and disabled market-type IDs remain enforced. No alternate odds dataset or credential is used.
- Reports unresolved source/player IDs and skips their quotes without inventing names or suppressing supported quotes. These boards remain partial.
- Includes `provider_path`, `provider_http_status`, safe validation categories, and bounded warnings in structured collection logs. Provider bodies, headers, query strings, and credentials are omitted.

## Live verification

At **2026-10-19 17:23:42 UTC** (1:23:42 PM America/New_York), API/database health checks passed and the collector heartbeat was healthy. The database contained 130 events, 2,050 markets, and 3,686 selections, including previously stored props; these totals do not imply all quotes are fresh or available.

The public moneyline endpoint returned actionable results under the configured freshness policy:

| League | Events with actionable moneylines | Bookmaker entries across events |
|---|---:|---:|
| NBA | 45 | 164 |
| NFL | 17 | 121 |
| MLB | 1 | 6 |

Moneyline collection outcomes are `partial` while event discovery and some period mappings remain unavailable. `last_success` is reserved for complete refreshes; `last_attempt`, `selection_count`, and warnings show the partial refreshes. Existing missing selections are not removed on this basis.

## Remaining provider blocker: player props

After removing discovery as the first blocker, current failures identify the actual odds endpoints:

```text
/market/nba/props/odds  HTTP 200, success:false
/market/nfl/props/odds  HTTP 200, success:false
/market/mlb/props/odds  HTTP 200, success:false
```

Props-specific source discovery also intermittently returned unsuccessful HTTP-200 envelopes. A successful MLB props refresh was observed earlier, but the latest props attempts failed. Previously stored prices are retained and stale prices are excluded by the normal freshness policy.

With the regular collector paused, three read-only probes used discovered IDs and the documented repeated `betTypeId` filter, spaced at least six seconds apart. All still returned `provider_operation_failed` inside HTTP 200:

| Request time (UTC) | League / market | Discovered bet IDs |
|---|---|---|
| 17:20:25 | NBA player points | 73, 275 |
| 17:20:33 | NFL passing yards | 14 |
| 17:20:40 | MLB pitcher strikeouts | 17 |

The regular collector was restarted automatically afterward. Narrowing the valid query did not restore props. The response does not identify the provider's internal exception or establish whether the issue is account-specific. Unabated needs to investigate these request times/paths for the configured account. Credentials are not included in this report.

Unknown period mappings remain explicit warnings: NBA period ID 3 and MLB IDs 12, 20, 26, and 27 were observed. Their semantics have not been guessed or folded into full-game moneylines.

## Validation

- **106 offline/SQLite tests passed**, including recovery, negative caching, partial-scope preservation, request construction, auth/coverage gates, and safe log fields.
- Ruff lint and formatting passed.
- Images rebuilt and the Compose stack started successfully with the persistent database retained.
- Isolated container checks passed for two API workers, product authentication, persisted moneylines/props, OpenAPI, restart persistence, provider outages, collector ownership, credential redaction, and shutdown. Those checks use synthetic data and a closed local provider port.
- Live API checks confirmed the moneyline results above. Full live props coverage and continuous pregame/live/final acceptance remain incomplete.

The identity fallback endpoints are documented in [Unabated discovery](https://docs.unabated.com/guides/discovery). The failed props URLs and filter format match the [API reference](https://docs.unabated.com/reference).

Read-only utilities: `scripts/collection_status.py` summarizes local API status; `scripts/probe_prop_boards.py` reproduces the filtered provider probes. Pause any other collector using the key before running the provider probes.
