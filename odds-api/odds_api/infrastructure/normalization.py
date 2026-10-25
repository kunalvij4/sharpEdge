"""Explicit semantic mapping, using discovered IDs rather than composite keys."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from odds_api.domain.models import Availability, Board, Event, League, Quote, Sportsbook, utc
from odds_api.infrastructure.provider_schema import Line, Source

BET_NAMES = {
    "moneyline": "h2h",
    "money line": "h2h",
    "spread": "spreads",
    "point spread": "spreads",
    "puck line": "spreads",
    "run line": "spreads",
    "goals": "player_goals",
    "shots on goal": "player_shots_on_goal",
    "saves": "goalie_saves",
    "goalie saves": "goalie_saves",
    "blocked shots": "player_blocked_shots",
    "power play points": "player_power_play_points",
    "points": "player_points",
    "player points": "player_points",
    "rebounds": "player_rebounds",
    "player rebounds": "player_rebounds",
    "assists": "player_assists",
    "player assists": "player_assists",
    "points + rebounds + assists": "player_points_rebounds_assists",
    "points + rebounds": "player_points_rebounds",
    "points + assists": "player_points_assists",
    "rebounds + assists": "player_rebounds_assists",
    "three pointers made": "player_threes",
    "3 pointers made": "player_threes",
    "steals": "player_steals",
    "blocks": "player_blocks",
    "turnovers": "player_turnovers",
    "passing yards": "player_pass_yds",
    "passing touchdowns": "player_pass_tds",
    "passing attempts": "player_pass_attempts",
    "passing completions": "player_pass_completions",
    "passing interceptions": "player_pass_interceptions",
    "rushing yards": "player_rush_yds",
    "rushing attempts": "player_rush_attempts",
    "receiving yards": "player_reception_yds",
    "receptions": "player_receptions",
    "rushing + receiving yards": "player_rush_reception_yds",
    "hits": "batter_hits",
    "total bases": "batter_total_bases",
    "home runs": "batter_home_runs",
    "runs": "batter_runs_scored",
    "runs batted in": "batter_rbis",
    "rbis": "batter_rbis",
    "pitcher strikeouts": "pitcher_strikeouts",
    "outs recorded": "pitcher_outs",
    "pitcher outs": "pitcher_outs",
    "hits allowed": "pitcher_hits_allowed",
    "pitcher hits allowed": "pitcher_hits_allowed",
    "earned runs": "pitcher_earned_runs",
    "pitcher earned runs": "pitcher_earned_runs",
    "batter walks": "batter_walks",
    "hitter walks": "batter_walks",
}
PERIOD_NAMES = {
    "first period": "p1",
    "second period": "p2",
    "third period": "p3",
    "game": "full",
    "full game": "full",
    "full": "full",
    "first quarter": "q1",
    "1st quarter": "q1",
    "second quarter": "q2",
    "2nd quarter": "q2",
    "third quarter": "q3",
    "3rd quarter": "q3",
    "fourth quarter": "q4",
    "4th quarter": "q4",
    "first half": "h1",
    "1st half": "h1",
    "second half": "h2",
    "2nd half": "h2",
    "first 5 innings": "1st_5_innings",
    "first five innings": "1st_5_innings",
    "first three innings": "1st_3_innings",
    "first seven innings": "1st_7_innings",
    "first inning": "1st_1_innings",
    "second inning": "2nd_1_innings",
    "third inning": "3rd_1_innings",
    "fourth inning": "4th_1_innings",
    "fifth inning": "5th_1_innings",
    "sixth inning": "6th_1_innings",
    "seventh inning": "7th_1_innings",
    "eighth inning": "8th_1_innings",
    "ninth inning": "9th_1_innings",
}
EVENT_STATES = {1: "pregame", 2: "live", 3: "final", 4: "delayed", 5: "postponed", 6: "cancelled"}


def values(obj):
    if obj is None:
        return []
    if isinstance(obj, dict):
        return list(obj.values())
    if isinstance(obj, list):
        return obj
    raise ValueError("Expected provider collection")


def timestamp(value):
    if value in (None, "", 0):
        return None
    # Numeric source timestamps are never guessed to be seconds versus milliseconds.
    if not isinstance(value, str):
        raise ValueError("Expected ISO timestamp")
    return utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def link_with_partner(link, partner):
    if not link:
        return None
    parsed = urlsplit(link)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    if partner and (parsed.hostname == "gambly.com" or parsed.hostname.endswith(".gambly.com")):
        query = dict(parse_qsl(parsed.query))
        query["utm_campaign"] = partner
        return urlunsplit(parsed._replace(query=urlencode(query)))
    return link


def resolve_duplicates(candidates):
    """Use source recency only when it establishes an unambiguous quote."""

    def terms(q):
        return q.price, q.state, q.expires_at, q.description

    if all(q.source_updated_at is not None for q in candidates):
        newest = max(q.source_updated_at for q in candidates)
        candidates = [q for q in candidates if q.source_updated_at == newest]
    chosen = min(candidates, key=repr)
    if len({terms(q) for q in candidates}) == 1:
        return chosen, False
    # Explicitly suspend the conflicting selection so an older cached price
    # cannot remain actionable after a partial refresh.
    return replace(chosen, price=None, state=Availability.SUSPENDED, deep_link=None), True


class Normalizer:
    def __init__(self, bet_overrides=None, period_overrides=None, partner=""):
        self.bet_overrides, self.period_overrides = bet_overrides or {}, period_overrides or {}
        self.partner = partner

    def market_map(self, bets):
        result = {}
        for bet in values(bets):
            key = str(bet["id"])
            target = self.bet_overrides.get(key) or BET_NAMES.get((bet.get("name") or "").strip().lower())
            # Only player bets may map to player props; ambiguous names are rejected by side context below.
            if target:
                result[key] = target
        result.update(self.bet_overrides)
        return result

    def period_map(self, periods):
        result = {
            str(p["id"]): PERIOD_NAMES.get((p.get("name") or "").strip().lower()) for p in values(periods)
        }
        result.update(self.period_overrides)
        return result

    def parse(
        self, league: League, kind, data, sources, bets, periods, events, people, teams, now, complete=True
    ):
        if not isinstance(data, dict) or not isinstance(data.get("odds"), dict):
            raise ValueError("Missing odds board; cannot confirm empty scope")
        event_map, books, quotes, warnings = {}, {}, {}, set()
        market_map, period_map = self.market_map(bets), self.period_map(periods)
        people_map = {
            str(p["id"]): " ".join(filter(None, (p.get("firstName"), p.get("lastName"))))
            for p in values(people)
        }
        team_map = {str(t["id"]): t.get("name") or t.get("fullName") for t in values(teams)}
        source_map = {}
        for raw in values(sources):
            source = Source.model_validate(raw)
            source_map[str(source.id)] = source
            books[str(source.id)] = Sportsbook(str(source.id), source.name)

        def event_from(raw):
            team_sides = {}
            for team in values(raw.get("eventTeams")):
                catalog_name = team_map.get(str(team.get("teamId")))
                # CFB's bulk event list uses abbreviations (e.g. MFL). Use the
                # same provider's team catalog for the confirmed school name.
                name = (
                    (catalog_name or team.get("name"))
                    if league.route == "cfb"
                    else (team.get("name") or catalog_name)
                )
                if name:
                    team_sides[team["sideIndex"]] = name
            eid = str(raw["eventId"])
            previous = event_map.get(eid)
            start = timestamp(raw.get("eventStart")) or (previous.start if previous else None)
            home = team_sides.get(1) or (previous.home if previous else "")
            away = team_sides.get(0) or (previous.away if previous else "")
            state = (
                previous.status
                if previous and raw.get("statusId") is None
                else EVENT_STATES.get(raw.get("statusId"), "unknown")
            )
            if raw.get("isLive") and state == "pregame":
                state = "live"
            if start is None:
                raise ValueError("Missing event start")
            event = Event(eid, league.key, start, home, away, state)
            event_map[eid] = event
            return event

        for raw in values(events):
            if str(raw.get("leagueId")) != league.source_id:
                warnings.add("foreign_catalog_event:" + str(raw.get("eventId", "missing")))
                continue
            try:
                event_from(raw)
            except (ValueError, KeyError, TypeError):
                warnings.add("unresolved_catalog_event:" + str(raw.get("eventId", "missing")))
        for league_board in values(data["odds"]):
            if str(league_board["leagueId"]) != league.source_id:
                raise ValueError("Unexpected league in scoped response")
            for period in values(league_board.get("periodTypes")):
                pid = str(period["periodTypeId"])
                period_key = period_map.get(pid)
                for phase in ("pregame", "live"):
                    for group in values(period.get(phase)):
                        try:
                            event = event_from(group)
                        except ValueError as error:
                            if str(error) not in {
                                "Missing event start",
                                "Event identity and team names are required",
                            }:
                                raise
                            warnings.add("unresolved_event:" + str(group.get("eventId", "missing")))
                            continue
                        if event.start <= now:
                            continue
                        bet_id = str(group["betTypeId"])
                        base = market_map.get(bet_id)
                        if not base or not period_key:
                            warnings.add("unsupported_mapping:bet=" + bet_id + ":period=" + pid)
                            continue
                        if group.get("betSubType"):
                            warnings.add("unsupported_bet_subtype:bet=" + bet_id)
                            continue
                        if league.route == "nhl" and base == "batter_hits":
                            base = "player_hits"
                        if (kind == "moneyline") != (base in {"h2h", "spreads"}):
                            continue
                        for side in values(group.get("sides")):
                            player = str(side["personId"]) if side.get("personId") is not None else None
                            if kind == "props" and not player:
                                warnings.add("unsupported_nonplayer_prop:bet=" + bet_id)
                                continue
                            if base in {"h2h", "spreads"}:
                                name = {0: event.away, 1: event.home, 2: "Draw"}.get(side["sideIndex"])
                                description = None
                            else:
                                # Phase 1 supports conventional over/under props.
                                name = {0: "Over", 1: "Under"}.get(side["sideIndex"])
                                description = people_map.get(player)
                                if not description:
                                    warnings.add("unresolved_player:" + player)
                                    continue
                            if not name:
                                warnings.add("unsupported_side:bet=" + bet_id)
                                continue
                            for raw_line in values(side.get("marketSourceLines")):
                                main = Line.model_validate(raw_line)
                                source_id = str(main.marketSourceId)
                                if source_id not in source_map:
                                    warnings.add("undiscovered_source:" + source_id)
                                    continue
                                source = source_map[source_id]
                                source_status = source.propsStatusId if kind == "props" else source.statusId
                                enabled = source.isActive and source_status in {1, 2}
                                # Market-type IDs are supplied by discovery, never assumed here.
                                disabled = getattr(self, "disabled_sources", set())
                                for is_alt, raw in [
                                    (False, raw_line),
                                    *[(True, a) for a in (main.alternateLines or [])],
                                ]:
                                    # Alternates may inherit identity, but never inherit main price/status/link/timestamp.
                                    item = Line.model_validate(
                                        {
                                            "marketSourceId": main.marketSourceId,
                                            "marketLineId": main.marketLineId,
                                            "marketId": main.marketId,
                                            **raw,
                                        }
                                    )
                                    state = (
                                        Availability.AVAILABLE
                                        if (
                                            item.statusId == 1
                                            and not item.disabled
                                            and enabled
                                            and source_id not in disabled
                                            and item.price is not None
                                            and event.status not in {"final", "cancelled", "unknown"}
                                        )
                                        else Availability.SUSPENDED
                                    )
                                    market = base + ("_alternate" if is_alt else "")
                                    if period_key != "full":
                                        market += "_" + period_key
                                    if (kind == "props" or base == "spreads") and item.points is None:
                                        warnings.add(
                                            "missing_prop_points:bet=" + bet_id + ":source=" + source_id
                                        )
                                        continue
                                    quote = Quote(
                                        event.id,
                                        books[source_id].id,
                                        market,
                                        period_key,
                                        player,
                                        Decimal(str(item.points)) if item.points is not None else None,
                                        is_alt,
                                        name,
                                        description,
                                        str(item.marketId or ""),
                                        str(item.marketLineId),
                                        item.price,
                                        state,
                                        now,
                                        timestamp(item.modifiedOn),
                                        timestamp(item.freshnessExpiresAt),
                                        link_with_partner(item.deepLink, self.partner),
                                    )
                                    quotes.setdefault(quote.selection_id, []).append(quote)
        resolved = []
        for selection_id, candidates in quotes.items():
            quote, ambiguous = resolve_duplicates(candidates)
            resolved.append(quote)
            if ambiguous:
                warnings.add("conflicting_selection:" + selection_id)
        return Board(
            league,
            kind,
            tuple(event_map.values()),
            tuple(books.values()),
            tuple(resolved),
            now,
            complete and not warnings,
            tuple(sorted(warnings)),
        )
