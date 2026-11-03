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
| Source events that failed the canonical fixture join | 84 | 40 |
| Collected player-prop outcomes | 5,899 | 5,899 |
| Qualifying player-prop EV opportunities | 0 | 4 |

The four resulting EV targets were one ProphetX, one Underdog and two PrizePicks offers. Existing website eligibility rules still apply, including its college PrizePicks exclusion. These historical results demonstrate improved matching and do not predict the number of current opportunities.

Regression coverage verifies differing provider IDs, absent IDs, school acronyms, punctuation, opposing namesakes, ambiguous school aliases and SQL/Redis public response consistency.
