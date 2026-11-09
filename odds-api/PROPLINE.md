# Combined odds collection

The main application currently imports NHL, NBA, NFL, NCAAF, and NCAAB from PropLine and
Unabated into one SQL database and the existing `/v1` API.

MLB routes remain supported, but `COLLECTION_EXCLUDED_LEAGUES=["mlb_baseball"]`
pauses all scheduled MLB provider requests. Set that list to `[]` to resume it.

## Schedule

A single supervised `odds_api.collector` process owns both feeds:

| Minutes from first startup | Feed |
|---|---|
| 0 | PropLine, all five leagues |
| 4 | Unabated, all five leagues |
| 8 | PropLine |
| 12 | Unabated |

Both intervals are 480 seconds. Starts are separated by 240 seconds; requests
within a provider cycle are sequential. Unabated retains its five-second odds
request limiter. The scheduler persists its origin and claimed slot under
`artifacts/collection/schedule.json`; restarts do not issue an immediate duplicate
cycle. Long cycles and downtime delay the next provider turn instead of skipping it.
Starts remain at least four minutes apart; the same provider is never polled
more often than every eight minutes. Slow upstream responses can extend that
interval. There are no catch-up bursts. PostgreSQL advisory locks exclude duplicate collectors and the legacy
standalone PropLine writer. Heartbeats continue between cycles.

PropLine sends one bulk odds request per league with explicit player prop keys,
`h2h`, `spreads`, `period=all`, and book IDs/links. It does not request events or
bookmakers separately. Five calls every eight minutes use **900 requests/day**,
leaving 100 of a 1,000-request daily allowance for diagnostics. No automatic
PropLine retries; quota headers and Retry-After govern cooldowns.

Unabated sends one straight-board request (moneyline and spread IDs discovered
from `/bettype`) and one props-board request per league. Metadata is cached and
shared between the two scopes. Odds requests cover whole leagues, never one call
per game. Normal operation is ten odds calls per cycle, plus metadata refreshes.
NCAAF and NCAAB props also use bulk `/event/cfb/upcoming` and `/event/cbb/upcoming`
catalogs, cached hourly, to supply fixtures missing from inline prop context.
Catalog failure preserves usable odds. School names come from the same
provider's team catalog rather than event abbreviations.

## Shared API and identities

Canonical sport keys are `nhl_hockey`, `nba_basketball`, `nfl_football`,
`mlb_baseball`, `ncaaf_football`, and `ncaab_basketball`. Unabated uses `cfb` for NCAAF
and `cbb` for NCAAB; PropLine uses `football_ncaaf` and `basketball_ncaab`.
Provider route keys are mapped internally. MLB remains in the API catalog during its collection pause.
Books retain provenance: `unabated_<source-id>` and `propline_<book-key>`.
API refreshes never remove missing selections from either feed, even on a
complete empty response. An existing selection changes only when the incoming
price is available, valid, unexpired, and collected later, with no source-time
regression or loss of a known observation time. Missing, invalid, or older data
preserves the prior quote and its original timestamps; it ages normally instead
of being refreshed synthetically. Existing kickoff pruning still applies.
Moneylines and spreads are served by the sport odds endpoint; player props by
`/v1/events/{id}/props` or the event odds endpoint. Periods and alternate lines
retain distinct market keys, including NHL `p1`, `p2`, and `p3`.

Unabated supplies the canonical event catalog. PropLine matches a unique pairing
of both teams and kickoff time; ambiguous or unmatched events are counted and
excluded, never guessed. NBA allows the verified ten-minute tipoff discrepancy
(up to fifteen minutes); other leagues allow five minutes. A cold-start PropLine
snapshot is rejoined after Unabated discovery without another upstream request.
The original collection timestamps and expiration remain unchanged. A game only
listed by PropLine will wait for canonical discovery; this is visible in the
unmatched-event counts.

Player IDs are reused only for unique full-name matches on the same fixture.
Otherwise confirmed provider IDs are namespaced. PrizePicks, Underdog, and
Sportzino also accept a named-player identity scoped to the matched fixture when
the provider omits player IDs, including college props. Ambiguous player matches
remain excluded. O/U lines, milestone names, and yes-only props retain their
original semantics. Frozen/suspended lines and withdrawn outcomes remain excluded.

The bookmaker filter includes `prizepicks`, `underdog`, and `sportzino`.
PrizePicks standard projections are included; goblin/demon and unclassified
projections are excluded. Its synthetic +100 prices are retained as supplied.
Underdog's real two-way American prices already include payout multipliers and
are never multiplied again. Other DFS platforms remain excluded. The Lambda
keeps fantasy entries out of sportsbook arbitrage and PrizePicks synthetic
prices out of the fair-price consensus. Per-book `stored_outcomes:<book>` counters
show successfully normalized selections in collection status.

Freshness defaults are 600 seconds since collection for both feeds; PropLine
also expires 900 seconds after the upstream market observation, or at kickoff.
Unabated's existing source-age and explicit provider expiry rules still apply.
Cached Unabated props remain labelled as cached during an outage; `freshOnly=true`
excludes them. A successful rejoin never makes an old snapshot fresh again.

## Run and inspect

Set the credentials in `.env`, use the six-league `LEAGUES_JSON` in `.env.example`,
and run `docker compose up --build -d`. Both poll interval settings must be 480;
collection TTLs must cover that interval. `PROPLINE_ENABLED=true` is the default.
The API image has no browser. `collection-artifacts` stores scheduler/status files;
`odds-data` retains the SQL database. No new migration is required.

`/v1/status` exposes Unabated scope outcomes and PropLine per-league coverage,
counts, quota headers, and failures. Logs include `feed_cycle_started` and
`feed_cycle_finished` with the provider and schedule slot.

For a separate retrieval-only capture, run `python -m scripts.probe_propline`.
It makes at most five requests and saves raw JSON plus a coverage report under
`artifacts/propline`. It never writes SQL. Historical captures remain available.

## Local Bet365 streaming

Run `docker compose --env-file .env.bet365 -f compose.bet365.yaml up --build -d`
on your local machine. See [configuration and operations](README.md) for the
dedicated collector key and server setup. The collector runs headed Edge/Xvfb
under a 1 GiB RAM and 1 vCPU limit, one league at a time, and sends verified HTTP
snapshots over HTTPS. The default active leagues are NHL, NBA, NFL, NCAAF,
and NCAAB. MLB stays paused unless explicitly configured.

The server validates source records and timestamps, joins existing canonical
events and comparable player O/U selections, and merges observations into
the shared compressed Redis store. Canonical events and other providers'
selections retain their identities and lifecycle. The local service has its
own artifact volume and requires only the ingestion key. `/v1/status` exposes
server ingestion progress; local status records browser or delivery errors.

## References

- https://prop-line.com/docs
- https://prop-line.com/llms-full.txt
- https://docs.unabated.com/reference

Offline tests cover both HTTP contracts, five-league API reads, provider-isolated
refreshes, cold-start rejoining, spread signs, NHL periods, freshness, schedule
offsets, restart deduplication, and missed-slot handling. Repository/API tests
also run against a disposable PostgreSQL database.
