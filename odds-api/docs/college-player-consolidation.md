# College player and university matching

College props can be joined across books without requiring provider player IDs to agree. The join uses a confirmed fixture, a verified school and the normalized complete player name. Markets still require the same statistic, period, side and exact line.

The November 2 provider captures contained names such as `Brayden Roggow (AKR)` alongside `Brayden Roggow`. Unabated's documented player catalog also contains `teamId`; the team catalog resolves that ID to a university. PropLine's player IDs were absent throughout the captured NCAAB board. The former matching treated a trailing school tag as part of the player's name, splitting otherwise comparable quotes.

## Implemented behavior

- The checked-in [school registry](../odds_api/domain/college_schools.json) covers 533 schools and more than 1,500 unambiguous aliases, including common names, acronyms and mascot names. Its references and verification date are recorded in the file. References are the provider team catalogs and ESPN's own college team catalogs; college collection does not require extra per-player network requests.
- Unabated's explicit roster school identifies players when that school belongs to the fixture. A trailing tag such as `(AKR)` is resolved against the schools playing in that fixture. A confirmed tag at one book can identify the same full name at another book on that fixture.
- Public descriptions use a consistent `Player Name (School)` form when affiliation is known. `DJ Smith (DUKE)` and `D.J. Smith` can therefore use the same displayed identity when the verified player belongs to Duke. IDs supplied by different providers remain independent inputs rather than a requirement for joining.
- Retained SQL and Redis odds receive the same consolidation when read. Their stored quote timestamps, expiry and prices are preserved. Public outcomes retain the existing `name`, `price`, `point` and `description` fields.
- Two players with the same name at opposing schools stay separate. Unqualified names that could refer to either player, conflicting IDs within one provider and tags identifying a school outside the fixture are rejected. Ambiguous acronyms do not force a university match. Initials are not expanded into guessed first names, and approximate spelling is not used to merge athletes.
- When school context is unavailable, the existing unique-name fallback remains scoped to the fixture. Verified nickname or alternate-spelling aliases would need an explicit roster reference; school plus surname alone is insufficient.

## Replay evidence

The captured boards were replayed at their original observation times, comparing commit `b15f4b5` with the new matcher and the same EV model. This was an offline diagnostic, not a change to the live freshness clock or EV eligibility rules.

| Captured NCAAB result | Before | After |
| --- | ---: | ---: |
| Source events that failed the canonical fixture join | 84 | 39 |
| Collected player-prop outcomes | 5,899 | 6,001 |
| Qualifying player-prop EV opportunities | 0 | 4 |

The four resulting EV targets were one ProphetX, one Underdog and two PrizePicks offers. Existing website eligibility rules still apply, including its college PrizePicks exclusion. These historical results demonstrate improved matching and do not predict the number of current opportunities.

Regression coverage verifies differing provider IDs, absent IDs, school acronyms, punctuation, opposing namesakes, ambiguous school aliases and SQL/Redis public response consistency.

## NCAAB recheck on November 3, 2026

The basketball-specific audit compared all 6,001 collected PropLine prop outcomes directly with the saved source selections. Prices, lines, sides and normalized complete player names were preserved, with no school outside its fixture and no inconsistent descriptions within a resolved player identity. Of 5,113 school-qualified outcomes, 5,094 reused player IDs whose explicit Unabated roster school agreed with the output; the remaining 19 relied on source school tags. The 146 distinct player records include 114 with school context and 32 retained through the fixture-scoped fallback.

An independent check against ESPN's 2026–27 rosters found exact normalized names for 110 of those 114 school-qualified players. The other four differ only by a suffix omitted in the odds feeds: Patrick Ngongba II, Jeremy Fears Jr., Robert Wright III and Bruce Branch III. This audit did not add suffix stripping or infer affiliations for the other 32 players.

The recheck found that the original five-minute event window dropped BYU–Ohio State: PropLine reported November 3 at 01:00 UTC, while Unabated reported 02:00 UTC. [Ohio State's official preview](https://ohiostatebuckeyes.com/news/2026/10/31/mens-basketball-buckeyes-open-season-monday-vs-no-25-byu) confirms November 2 at 9 p.m. Eastern, agreeing with the canonical start. A NCAAB-only fallback now accepts a one-hour discrepancy (within five minutes) when both schools are recognized and exactly one fixture matches. The normal five-minute match takes priority; other time gaps and ambiguous fixtures remain rejected. Canonical IDs and start times are preserved, and fresh quotes expire by the earlier reported start. This restores 47 Underdog and 55 standard PrizePicks outcomes in the capture without changing the four qualifying EV results.

The live source check at November 3, 11:01 p.m. Eastern found no upcoming NCAAB player props at either provider. Unabated returned zero prop quotes; PropLine's only remaining prop board was 147 Courtside outcomes for Iowa–Lipscomb, which had already started at 8 p.m. Eastern and was correctly excluded. Production reported a successful NCAAB collection; its stored game lines must not be counted as player props. The captured replay verifies normalization and coverage, while current prop availability still depends on what providers publish.

## Retrieval and market normalization audit on November 4, 2026

At 9:58 a.m. Eastern the direct provider check and eight upcoming API fixtures again contained no CBB props. The production collector had successfully retrieved 116 PropLine events at 9:53 a.m., but all 2,920 stored outcomes were game lines. PropLine's `X-PropLine-Missing-Markets` header listed every requested basketball player-prop market. Removing the book filter in a separate bulk check still returned no props. Unabated returned HTTP 200 with `success:false`, no data, and the message "Unexpected error while retrieving odds for the provided filter." A second read using its documented discovered-bet-type filter failed the same way. This establishes an upstream operation failure, not its internal cause or an account entitlement diagnosis.

The audit also found and fixed independent integration gaps:

- Unabated's actual discovery labels `Points and Rebounds`, `Points Rebounds Assists`, `Points Assists`, `Rebounds Assists`, `Player Turnovers` and `Steals Blocks` now map to the same public market keys used by PropLine. The previous labels containing `+` missed these offers. Main lines, alternates, prices, player identities and periods retain their source terms.
- Discovered Yes/No first-basket, double-double and triple-double bets retain their categorical sides and do not require a numeric line. Conventional over/under double-double counts still require their source line; a source's explicit bet-side definition distinguishes the shapes.
- NCAAB now uses the [documented all-book bulk response](https://prop-line.com/docs) instead of an older book allowlist. The audit found 10 additional college books: bet-at-home, BetOnline, Danske Spil, LowVig, Mise-o-jeu, Pame Stoixima, Sazka, Veikkaus, Stoiximan and Unibet. Collection still uses one bulk request per active sport with no per-event fanout. Returned DraftKings Pick6 props are collected and use one public book name across feeds.
- Redis collection reads fixtures and trusted player identities from one batch of stored event documents. It skips retained PropLine prices before reconstructing quote objects and timestamps. SQL retains its existing fallback. Quote freshness, replacement rules and request limits are preserved.
- `/v1/status` → `propline.leagues.ncaab_basketball` now distinguishes `source_empty`, `filtered` and `available` prop coverage. Counts separate `source_player_prop_outcomes`, `stored_player_prop_outcomes`, `stored_game_outcomes` and stored props per book. Fetch, normalization and save timings identify collection bottlenecks. A successful game-line fetch no longer implies available props.

Replaying the original CBB Unabated capture expands normalization from 1,466 to 2,885 outcomes: **1,419 additional outcomes, including 1,277 available prices and 142 suspended offers**. All 1,466 previously normalized quotes are exactly preserved. The added markets are points+rebounds (347), points+assists (327), PRA (362), rebounds+assists (183), turnovers (100), first basket (90) and steals+blocks (10). The captured PropLine board retains 6,001 prop outcomes with no price, line, side or school-assignment discrepancies in the audit. These are replay results, not newly available live quotes.

The replay's remaining unsupported records are explicitly flagged. `Milestone-Alt` records without structured thresholds cannot safely become ordinary over/under lines, and `Player Fantasy Points` lacks confirmed scoring rules for cross-book comparison. No thresholds, scoring rules or live prices are invented to populate an empty board. Unabated's [response and status contract](https://docs.unabated.com/guides/response-concepts) and [error handling guidance](https://docs.unabated.com/guides/errors-and-limits) remain the basis for those distinctions.
