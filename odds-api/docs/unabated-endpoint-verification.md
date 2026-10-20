# Unabated endpoint verification — 2026-10-19

Reviewed against [the API reference](https://docs.unabated.com/reference) and its linked [OpenAPI document](https://data.unabated.com/swagger/v1/swagger.json). This check compares request construction with the published contract; it does not establish that every account endpoint is currently operational.

## Connection and authentication

- Server: `https://data.unabated.com`.
- All nine operations below use `GET`.
- The documented REST security scheme is an API key in the `X-Api-Key` header. The adapter sends it with `Accept: application/json`.
- These upstream paths are relative to the server root. Our service's `/v4` versioning applies to our public API, not to Unabated requests.

## Operations

| Adapter request | Contract operation ID | Required path values | Query parameters we send | Result |
|---|---|---|---|---|
| `/league` | `leagueGetAllLeagues` | None | None | Matches |
| `/bettype` | `betTypeGetBetTypes` | None | None | Matches |
| `/period-type/{league}` | `periodTypeGetPeriodTypesByLeague` | League string | None | Matches |
| `/market-type` | `marketTypeGetMarketTypes` | None | None | Matches |
| `/market/{league}/{marketType}/sources` | `marketDataGetSources` | League and market type strings | None | Matches |
| `/market/{league}/{marketType}/teams` | `marketDataGetTeams` | League and market type strings | None | Matches |
| `/market/{league}/{marketType}/people` | `marketDataGetPeople` | League and market type strings | None | Matches; props only |
| `/event/{league}/upcoming` | `eventGetUpcomingEvents` | League string | None | Matches |
| `/market/{league}/{marketType}/odds` | `marketDataGetOdds` | League and market type strings | Repeated `betTypeId` for moneylines; none for the full props board | Matches |

The market path parameter is restricted to `straight`, `futures`, or `props`; Phase 1 requests `straight` and `props`. The documented query representation for filtering odds is repeated integer-valued `betTypeId` entries. The adapter's list of tuples produces that representation. It does not send unsupported sportsbook, event, or period filters upstream.

`changedSince`, where documented, is optional. `X-API-Version` and `api-version` are also optional. In particular, `/event/{league}/upcoming` has no required date, season, market type, request body, or additional query parameter. Leaving those parameters absent complies with the reference.

## Responses and identifiers

The adapter checks HTTP status and the provider's `success` flag before using `data`. A failed operation inside HTTP 200 is handled as failure. HTTP 401/403 are handled separately from retryable 429/5xx responses, and retries honor `Retry-After` through the limiter.

Discovery payload handling supports the contract's league/bet/period/source lists and team/player dictionaries. Odds are read from `data.odds`, preserving structured IDs, periods, pregame/live groups, sides, and source lines. Missing required identities are rejected conservatively.

The previously identified market-type problem concerns response interpretation, not the request URL: discovery display names `Straight` and `Player Props` must map to route tokens `straight` and `props`. Numeric IDs remain discovered. The correction was subsequently deployed by rebuilding and starting the Docker Compose stack on 2026-10-19, and its presence was confirmed in the running collector.

## Automated verification

`tests/test_provider_requests.py` exercises the real client constructor with an offline HTTP transport for all six NBA/NFL/MLB × moneyline/props combinations. It verifies method, scheme, hostname, authentication header, Accept header, the exact endpoint set, and repeated odds query parameters. It uses synthetic credentials and performs no network requests.

The existing provider tests also cover both successful and unsuccessful envelopes, HTTP errors, retry limits, pagination, market-type display-name mapping, and the current dependency on a successful upcoming-events lookup.

Verification result: **25 provider/request tests passed**, including the six new request-construction cases. Ruff lint and formatting passed. Pytest reported a sandbox permission warning for its pre-existing cache directory; no test failed.

## Conclusion and remaining blocker

No incorrect request path, authentication header, or missing required request parameter was found. The event lookup error observed in the preceding [live investigation](unabated-investigation-2026-10-19.md) therefore is not explained by a mismatch with the published request contract. Its internal cause remains unknown without provider diagnostics. The adapter's mandatory event-discovery dependency continues to block collection when that operation fails.

This verification made only an unauthenticated request for the public OpenAPI document. It did not send new account/odds requests, alter the deployment, or change completeness policy.

## Subsequent deployment check — 2026-10-19

`docker compose up --build --detach --wait --wait-timeout 120` completed successfully. Database and API health checks passed, migration exited with code 0, and the collector heartbeat was healthy. The deployed collector contained the market-type mapping correction. All six scopes still reported `provider_operation_failed`, with no successful collection or stored odds. Deployment succeeded; provider collection remains blocked.

## Collector recovery follow-up

The subsequent collector fix removes the mandatory dependency on successful event enrichment. Successful odds boards now provide event context when that lookup is unavailable, with partial-scope preservation and explicit warnings. Props metadata failures may use the documented `/team/{league}` and `/player/{league}` identity catalogs and the same league's straight sportsbook catalog. These are metadata fallbacks after the requested board has succeeded, not substitutes for unauthorized odds. Authentication/coverage errors still propagate. See `collector-recovery.md` for deployment results and remaining provider failures.
