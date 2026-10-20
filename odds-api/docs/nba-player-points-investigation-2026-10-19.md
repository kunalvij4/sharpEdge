# Empty player_points response for Detroit–Boston

Investigated local event `275f9649fc6e5e69b4e35ccd890aa8e8`, upstream event `134312`, starting 2026-10-20 at 19:00 UTC. The supplied event URL and `markets=player_points&oddsFormat=american` are valid. Product authentication succeeded; the event is pregame.

## Confirmed cause

At 19:42:47 UTC on 2026-10-19, the database held **397 full-game player_points selections for this event**. Of those, 382 had stored state `available` but were stale at observation time; the other 15 were suspended. The newest collection timestamp was **19:28:33 UTC**, about 14 minutes before the check. `COLLECTED_TTL=90` excludes quotes after 90 seconds without a successful refresh. Source timestamps and explicit expiry are checked separately, and `SOURCE_TTL=3600` also excludes older lines.

The same persisted rows were replayed through the real `OddsQueryService.odds` implementation using their last collection time as the diagnostic observation time. That produced **12 bookmakers and 248 eligible outcomes** for `player_points`. This is a diagnostic replay, not data served with an altered clock or altered freshness limits. It confirms that stored mapping, event identity, public market filtering, and response grouping work for the actual event.

The empty current response is therefore a consequence of failed refreshes and the freshness contract, not absence of collected player-points data. Partial successful boards update valid quotes even though the scope's `last_success` remains null, because that field is reserved for complete boards. Scope selection counts are retained through failures and do not indicate current actionable availability.

## Provider checks

The collector was paused for isolated read-only requests and automatically restarted afterward. `/bettype` identified two active definitions named `Points`: IDs 73 and 275, both player over/under bets with points. Each request was spaced at least six seconds from the previous response's completion, respecting `Retry-After` when present.

| UTC time | Request | HTTP | Envelope |
|---|---|---|---|
| 19:41:13 | `/market/nba/props/odds` | 200 | `success:false` |
| 19:41:22 | `/market/nba/props/odds?betTypeId=73` | 200 | `success:false` |
| 19:41:32 | `/market/nba/props/odds?betTypeId=275` | 200 | `success:false` |

All three returned: `Unexpected error while retrieving odds for the provided filter.` No HTTP 429 or 403 was returned by these probes. A single discovered bet filter did not restore the board, so narrowing to points is not a verified workaround. The provider's internal exception is not disclosed by that message.

Earlier collector logs show NBA props successfully normalized and stored at approximately 19:01, 19:07, 19:14, 19:21, and 19:28 UTC, with processing failures between successes. This is observed intermittent behavior, not a documented seven-minute provider update schedule. A 90-second collection window cannot keep that data actionable through multi-minute refresh failures.

The request path and repeated `betTypeId` query format match [Unabated's odds guide](https://docs.unabated.com/guides/odds). Their [error guide](https://docs.unabated.com/guides/errors-and-limits) treats an unsuccessful HTTP-200 envelope as an operation failure, not successful empty data.

## Changes and validation

Added `scripts/diagnose_event.py` to explain persisted availability for a chosen event/market, including diagnostic replay at its most recent collection time. Added `scripts/probe_event_points.py` for bounded provider-filter comparisons with credentials redacted. Evidence is recorded in `nba-points-event-diagnosis-2026-10-19.json` and `nba-points-provider-probes-2026-10-19.jsonl`.

A regression test exercises the same public points query with fresh data, at the 90-second boundary, after expiry and a failed refresh, and after recovery. All **13 HTTP API tests passed**; Ruff passed for the changed files. No runtime code or freshness setting was changed in this investigation; no image rebuild is needed for these diagnostics and tests. API/database health and the restarted collector were verified.

Reliable fresh props require successful provider refreshes. Serving older cached prices would require an explicit stale-data policy that labels their age; it would not repair collection. The current normal odds endpoint continues to exclude stale and suspended selections.
