# Combined odds collection

The main application imports NHL, NBA, NFL, MLB, and NCAAF from PropLine and
Unabated into one SQL database and the existing `/v1` API.

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
per game. Normal operation is ten odds calls per cycle, plus metadata refreshes. NCAAF props also use one bulk `/event/cfb/upcoming`
catalog, cached hourly, to supply fixtures missing from inline prop context.
Catalog failure preserves usable odds. School names come from the same
provider's team catalog rather than event abbreviations.

## Shared API and identities

Canonical sport keys are `nhl_hockey`, `nba_basketball`, `nfl_football`,
`mlb_baseball`, and `ncaaf_football`. Unabated uses `cfb` for NCAAF; PropLine uses `football_ncaaf`. Provider route keys are mapped internally.
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
Otherwise confirmed provider IDs are namespaced. O/U lines, milestone names,
and yes-only props retain their original semantics. DFS, frozen/suspended lines,
withdrawn outcomes, and ambiguous selections are excluded or suspended.

Freshness defaults are 600 seconds since collection for both feeds; PropLine
also expires 900 seconds after the upstream market observation, or at kickoff.
Unabated's existing source-age and explicit provider expiry rules still apply.
Cached Unabated props remain labelled as cached during an outage; `freshOnly=true`
excludes them. A successful rejoin never makes an old snapshot fresh again.

## Run and inspect

Set the credentials in `.env`, use the five-league `LEAGUES_JSON` in `.env.example`,
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

## Standalone Bet365

Run `docker compose -f compose.bet365.yaml up --build -d` independently.
This service uses `Dockerfile.bet365`, headed Edge/Xvfb, and its own artifact
volume. It receives no SQL or provider credentials, does not connect to the main
stack's network, and archives raw, normalized, and verification JSON for review.
It retains the existing NBA/NFL/MLB capture jobs. Its data is excluded from the
main API (`BET365_ENABLED=false`), including any older stored Bet365 rows.
The earlier adapter remains available for later review; the running standalone
service never calls its SQL ingestion function.

## References

- https://prop-line.com/docs
- https://prop-line.com/llms-full.txt
- https://docs.unabated.com/reference

Offline tests cover both HTTP contracts, five-league API reads, provider-isolated
refreshes, cold-start rejoining, spread signs, NHL periods, freshness, schedule
offsets, restart deduplication, and missed-slot handling. Repository/API tests
also run against a disposable PostgreSQL database.
