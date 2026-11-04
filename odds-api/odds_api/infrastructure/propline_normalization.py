"""Join PropLine snapshots to the canonical pregame catalog without changing event IDs."""

from collections import Counter
from datetime import timedelta
from decimal import Decimal

from odds_api.domain.college import COLLEGE_LEAGUES, SCHOOL_LABELS, CollegePlayers, name_key, player_parts
from odds_api.domain.models import Availability, Board, Event, Quote, Sportsbook, identity
from odds_api.infrastructure.bet365 import normalized, same_team
from odds_api.infrastructure.college_teams import COLLEGE_SPORTS, school_key
from odds_api.infrastructure.normalization import link_with_partner, resolve_duplicates
from odds_api.infrastructure.propline import COLLECTED_DFS_BOOKS, DFS_BOOKS, GAME_MARKETS, PROP_MARKETS

MARKET_ALIASES = {"batter_runs": "batter_runs_scored"}
NAMED_PLAYER_BOOKS = COLLECTED_DFS_BOOKS | {"sportzino"}
PERIODS = {
    None: "full",
    "q1": "q1",
    "q2": "q2",
    "q3": "q3",
    "q4": "q4",
    "h1": "h1",
    "h2": "h2",
    "p1": "p1",
    "p2": "p2",
    "p3": "p3",
    "f3": "1st_3_innings",
    "f5": "1st_5_innings",
    "f7": "1st_7_innings",
    **{
        f"i{i}": f"{i}{'st' if i == 1 else 'nd' if i == 2 else 'rd' if i == 3 else 'th'}_1_innings"
        for i in range(1, 10)
    },
}


def public_markets():
    bases = set(GAME_MARKETS) | {MARKET_ALIASES.get(m, m) for ms in PROP_MARKETS.values() for m in ms}
    return {
        base + alt + suffix
        for base in bases
        for alt in ("", "_alternate")
        for suffix in ("", *("_" + period for period in PERIODS.values() if period != "full"))
    }


def teams_match(left, right, sport_key=None):
    if sport_key in COLLEGE_SPORTS:
        return school_key(left) == school_key(right)
    # Either feed can use the abbreviated city (e.g. LA Clippers).
    return same_team(left, right) or same_team(right, left)


def match_event(source, events):
    # NBA books commonly publish tipoff ten minutes after the advertised start.
    # The saved live capture confirms this offset; require one exact team pairing.
    tolerance = 900 if source.sport_key == "basketball_nba" else 300
    fixtures = [
        event
        for event in events
        if event["status"] == "pregame"
        and (
            (
                teams_match(source.home_team, event["home"], source.sport_key)
                and teams_match(source.away_team, event["away"], source.sport_key)
            )
            or (
                teams_match(source.home_team, event["away"], source.sport_key)
                and teams_match(source.away_team, event["home"], source.sport_key)
            )
        )
    ]
    matches = [
        event
        for event in fixtures
        if abs((event["start"] - source.commence_time).total_seconds()) <= tolerance
    ]
    if matches:
        return matches[0] if len(matches) == 1 else None
    # The captured BYU–Ohio State board has a one-hour provider offset.
    # Allow this narrow NCAAB fallback only for two recognized schools and
    # a unique fixture; retain the canonical event ID and advertised start.
    schools = {school_key(source.home_team), school_key(source.away_team)}
    if source.sport_key != "basketball_ncaab" or len(schools) != 2 or not schools <= SCHOOL_LABELS.keys():
        return None
    matches = [
        event
        for event in fixtures
        if abs(abs((event["start"] - source.commence_time).total_seconds()) - 3600) <= 300
    ]
    return matches[0] if len(matches) == 1 else None


def boards(result, repository, *, max_age=900, collected_ttl=600, discover_events=False):
    now, league_key = result.collected_at, result.league
    league = next(league for league in repository.leagues() if league.key == league_key)
    events = [event for event in repository.events(league_key) if event["start"] > now]
    candidates, matched, books, counts = {"moneyline": {}, "props": {}}, {}, {}, Counter()
    # Reuse existing player identities only for a unique, complete name on this fixture.
    players = {}
    college = league_key in COLLEGE_LEAGUES
    college_players = {
        event["id"]: CollegePlayers(event["home"], event["away"]) for event in events if college
    }
    event_matches = {source.id: match_event(source, events) for source in result.events} if college else {}

    def observe_college_players(source, resolver):
        for book in source.bookmakers:
            if book.key in DFS_BOOKS - COLLECTED_DFS_BOOKS or book.pregame_only:
                continue
            for market in book.markets:
                if (
                    market.key not in PROP_MARKETS[league_key]
                    or market.period not in PERIODS
                    or market.suspended_at
                    or market.last_update is None
                    or not -5 <= (now - market.last_update).total_seconds() <= max_age
                ):
                    continue
                for outcome in market.outcomes:
                    if outcome.description and (
                        not outcome.last_seen_at or outcome.last_seen_at >= market.last_update
                    ):
                        resolver.add(outcome.description)

    for row in repository.quotes(league_key):
        q = row["quote"]
        if not row["book_key"].startswith("propline_") and q.player_id and q.description:
            players.setdefault((q.event_id, normalized(q.description)), set()).add(q.player_id)
            if q.event_id in college_players:
                college_players[q.event_id].add(q.description, q.player_id)
    # A school tag supplied by one book can identify the same complete name at
    # another book on this fixture, even before Unabated posts that player's prop.
    for source in result.events if college else ():
        event = event_matches[source.id]
        if event is None or source.live or source.completed or source.commence_time <= now:
            continue
        resolver = college_players[event["id"]]
        observe_college_players(source, resolver)
    for source in result.events:
        if (
            source.live
            or source.completed
            or source.commence_time <= now
            or source.model_extra.get("is_outright")
        ):
            counts["commenced_or_outright_events"] += 1
            continue
        event = event_matches[source.id] if college else match_event(source, events)
        if event is None and discover_events:
            discovered = Event(
                "propline:" + source.id,
                league_key,
                source.commence_time,
                source.home_team,
                source.away_team,
                "pregame",
            )
            event = {**vars(discovered), "id": discovered.id}
            counts["discovered_events"] += 1
        if event is None:
            counts["unmatched_or_ambiguous_events"] += 1
            continue
        if college and abs((event["start"] - source.commence_time).total_seconds()) > 300:
            counts["one_hour_start_offset_events"] += 1
        eid = event["id"]
        if college and eid not in college_players:
            college_players[eid] = CollegePlayers(event["home"], event["away"])
            observe_college_players(source, college_players[eid])
        matched[eid] = Event(
            event["source_id"], league_key, event["start"], event["home"], event["away"], event["status"]
        )
        for book in source.bookmakers:
            if (book.key in DFS_BOOKS - COLLECTED_DFS_BOOKS) or book.pregame_only:
                counts["excluded_dfs_or_frozen_book_blocks"] += 1
                continue
            canonical_book = Sportsbook(book.key, book.title, "propline")
            books[canonical_book.id] = canonical_book
            for market in book.markets:
                period = PERIODS.get(market.period)
                if period is None or market.key not in (*GAME_MARKETS, *PROP_MARKETS[league_key]):
                    counts["unsupported_markets"] += 1
                    continue
                if (
                    market.suspended_at
                    or market.last_update is None
                    or not -5 <= (now - market.last_update).total_seconds() <= max_age
                ):
                    counts["suspended_stale_or_undated_markets"] += 1
                    continue
                base = MARKET_ALIASES.get(market.key, market.key)
                source_market_id = identity(
                    "propline_market",
                    source.id,
                    book.key,
                    market.key,
                    market.period,
                    market.model_extra.get("description", ""),
                )
                for outcome in market.outcomes:
                    # PrizePicks goblin/demon payouts differ from its standard
                    # entry schedule. Keep standard projections in this API.
                    if book.key == "prizepicks" and outcome.model_extra.get("dfs_odds_type") != "standard":
                        counts["excluded_nonstandard_prizepicks_outcomes"] += 1
                        continue
                    if outcome.last_seen_at and outcome.last_seen_at < market.last_update:
                        counts["withdrawn_outcomes"] += 1
                        continue
                    is_game = market.key in GAME_MARKETS
                    player, description = None, None
                    name = outcome.name
                    if is_game:
                        side = outcome.model_extra.get("side")
                        team = {"home": source.home_team, "away": source.away_team}.get(side, name)
                        sides = [s for s in ("home", "away") if teams_match(team, event[s], source.sport_key)]
                        if market.key == "h2h" and (side == "draw" or name.casefold() == "draw"):
                            name = "Draw"
                        elif len(sides) != 1:
                            counts["unoriented_game_outcomes"] += 1
                            continue
                        else:
                            name = event[sides[0]]
                    else:
                        # Preserve O/U, Yes/No and N+ names verbatim, including null milestone lines.
                        if outcome.name in {"Over", "Under"} and outcome.point is None:
                            counts["props_without_required_line"] += 1
                            continue
                        description = outcome.description or (name if outcome.point is None else None)
                        if not description:
                            counts["props_without_player_context"] += 1
                            continue
                        resolver = college_players.get(eid)
                        school = None
                        if resolver:
                            resolved = resolver.resolve(description)
                            if resolved is None:
                                counts["ambiguous_or_conflicting_college_players"] += 1
                                continue
                            description, school, known = resolved
                            if school:
                                counts["school_matched_player_outcomes"] += 1
                            # Retain the legacy unique-name match while stored
                            # quotes are upgraded to school-qualified names.
                            if not known:
                                known = players.get((eid, normalized(description)), set()) or players.get(
                                    (eid, normalized(player_parts(description)[0])), set()
                                )
                        else:
                            known = players.get((eid, normalized(description)), set())
                        if len(known) > 1:
                            counts["ambiguous_players"] += 1
                            continue
                        named_player_fallback = (
                            book.key in NAMED_PLAYER_BOOKS or source.sport_key in COLLEGE_SPORTS
                        )
                        if not known and not outcome.player_id and not named_player_fallback:
                            counts["props_without_confirmed_player_id"] += 1
                            continue
                        if known:
                            player = next(iter(known))
                        elif school:
                            player = identity(
                                "college_player", league_key, school, name_key(player_parts(description)[0])
                            )
                        elif outcome.player_id:
                            player = identity("propline_player", league_key, outcome.player_id)
                        else:
                            # Some college boards provide names but no player ID.
                            # Scope the private identity to the matched fixture.
                            player = identity(
                                "propline_player_name", league_key, eid, normalized(description)
                            )
                    line_type = outcome.model_extra.get("line_type") or market.model_extra.get("line_type")
                    alternate = line_type == "alternate"
                    public = base + ("_alternate" if alternate else "")
                    if period != "full":
                        public += "_" + period
                    quote = Quote(
                        eid,
                        canonical_book.id,
                        public,
                        period,
                        player,
                        Decimal(str(outcome.point)) if outcome.point is not None else None,
                        alternate,
                        name,
                        description,
                        source_market_id,
                        str(
                            outcome.model_extra.get("outcome_id")
                            or identity("propline_selection", source_market_id, player, name, outcome.point)
                        ),
                        outcome.price,
                        Availability.AVAILABLE,
                        now,
                        market.last_update,
                        min(
                            event["start"],
                            source.commence_time,
                            now + timedelta(seconds=collected_ttl),
                            market.last_update + timedelta(seconds=max_age),
                        ),
                        link_with_partner(book.model_extra.get("link"), ""),
                    )
                    kind = "moneyline" if is_game else "props"
                    candidates[kind].setdefault(quote.selection_id, []).append(quote)
    output = []
    for kind, selections in candidates.items():
        resolved, warnings = [], []
        for selection_id, choices in selections.items():
            quote, ambiguous = resolve_duplicates(choices)
            resolved.append(quote)
            if ambiguous:
                warnings.append("conflicting_selection:" + selection_id)
                counts["conflicting_selections"] += 1
        coverage = GAME_MARKETS if kind == "moneyline" else PROP_MARKETS[league_key]
        output.append(
            Board(
                league,
                kind,
                tuple(matched.values()),
                tuple(books.values()),
                tuple(resolved),
                now,
                not warnings,
                tuple(warnings),
                "propline",
                tuple(coverage),
            )
        )
    counts["matched_events"] = len(matched)
    counts["stored_outcomes"] = sum(len(board.quotes) for board in output)
    for board in output:
        for quote in board.quotes:
            if quote.state == Availability.AVAILABLE:
                counts["stored_outcomes:" + books[quote.book_id].source_id] += 1
    return output, dict(counts)
