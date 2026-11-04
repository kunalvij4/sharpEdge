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
