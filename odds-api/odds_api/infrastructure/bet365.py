"""Match verified public Bet365 snapshots to the existing canonical odds catalog.

Only explicit full-game O/U markets are comparable. Milestones and SGP prices
are deliberately excluded; neither their lines nor their settlement are inferred.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from odds_api.domain.models import Availability, Board, Event, Quote, Sportsbook, utc

BOOK = Sportsbook("bet365", "Bet365", "bet365")
MARKETS = {
    "NBA": {
        "Points O/U": "player_points",
        "Rebounds O/U": "player_rebounds",
        "Assists O/U": "player_assists",
        "Threes Made O/U": "player_threes",
        "Points, Assists & Rebounds O/U": "player_points_rebounds_assists",
        "Points & Rebounds O/U": "player_points_rebounds",
        "Points & Assists O/U": "player_points_assists",
        "Assists & Rebounds O/U": "player_rebounds_assists",
    },
    "NFL": {
        "Pass Yds O/U": "player_pass_yds",
        "Rush Yds O/U": "player_rush_yds",
        "Receiving Yds O/U": "player_reception_yds",
        "Rush Attempts O/U": "player_rush_attempts",
        "Pass Attempts O/U": "player_pass_attempts",
        "Pass Completions O/U": "player_pass_completions",
        "Passing Yards O/U": "player_pass_yds",
        "Passing TDs O/U": "player_pass_tds",
        "Passing Attempts O/U": "player_pass_attempts",
        "Passing Completions O/U": "player_pass_completions",
        "Rushing Yards O/U": "player_rush_yds",
        "Rushing Attempts O/U": "player_rush_attempts",
        "Receiving Yards O/U": "player_reception_yds",
        "Receptions O/U": "player_receptions",
    },
    "MLB": {
        "Pitcher Outs O/U": "pitcher_outs",
        "Pitcher Hits Allowed O/U": "pitcher_hits_allowed",
        "Pitcher Earned Runs O/U": "pitcher_earned_runs",
        "Batter Walks O/U": "batter_walks",
        "Hits O/U": "batter_hits",
        "Total Bases O/U": "batter_total_bases",
        "RBIs O/U": "batter_rbis",
        "Home Runs O/U": "batter_home_runs",
        "Pitcher Strikeouts O/U": "pitcher_strikeouts",
        "Outs Recorded O/U": "pitcher_outs",
    },
}


def normalized(value):
    return re.sub(
        r"[^a-z0-9]", "", unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    )


def same_team(source, canonical):
    if normalized(source) == normalized(canonical):
        return True
    # Public US boards abbreviate cities (CLE Cavaliers, PHI 76ers). Match
    # the complete nickname after a city abbreviation, never a fuzzy substring.
    words = source.split()
    return (
        len(words) > 1
        and words[0].isupper()
        and 2 <= len(words[0]) <= 3
        and normalized(canonical).endswith(normalized(" ".join(words[1:])))
    )


def match_event(source, events, now):
    candidates = [
        e
        for e in events
        if e["status"] == "pregame"
        and now < e["start"] < now + timedelta(days=14)
        and same_team(source.get("home_team") or "", e["home"])
        and same_team(source.get("away_team") or "", e["away"])
    ]
    # BC's timezone is unverified. Use it only to reject distant fixtures,
    # never to fabricate a kickoff timestamp or choose an ambiguous doubleheader.
    raw = source.get("start_time_source")
    if raw:
        try:
            wall = datetime.strptime(raw, "%Y%m%d%H%M%S")
        except ValueError:
            return None
        candidates = [
            e
            for e in candidates
            if abs((e["start"].replace(tzinfo=None) - wall).total_seconds()) <= 18 * 3600
        ]
    return candidates[0] if len(candidates) == 1 else None


def captured_at(selection, now, max_age):
    value = selection.get("source", {}).get("received_at")
    if not value:
        return None
    try:
        timestamp = utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None
    return timestamp if -5 <= (now - timestamp).total_seconds() <= max_age else None


def boards(report, repository, now, *, max_age=150, support_age=3600, coverage=None):
    """Return canonical boards and discard counts. All timestamps retain provenance.

    coverage maps league keys to successfully captured public markets. Failure in
    one tab must not remove another tab's last good prices.
    """
    if report.get("normalization_issues"):
        raise ValueError("Unverified Bet365 normalization")
    result, counts = [], Counter()
    leagues = {league.key: league for league in repository.leagues()}
    for source_league in report["leagues"]:
        key = source_league["key"]
        if key not in leagues:
            continue
        league = leagues[key]
        events = repository.events(key)
        supported = {}
        for row in repository.quotes(key):
            q = row["quote"]
            if row["book_key"] == "bet365" or not q.player_id or q.state != Availability.AVAILABLE:
                continue
            age = (now - q.collected_at).total_seconds()
            if age > support_age or (q.expires_at and q.expires_at <= now):
                continue
            if q.source_updated_at and (now - q.source_updated_at).total_seconds() > support_age:
                continue
            if q.period != "full" or q.alternate:
                continue
            token = (q.event_id, q.market, normalized(q.description or ""), q.point, q.name.lower())
            supported.setdefault(token, {})[q.player_id] = q
        quotes = {"moneyline": {}, "props": {}}
        matched_events = {}
        for source in source_league["events"]:
            event = match_event(source, events, now)
            if event is None:
                counts["unmatched_or_ambiguous_events"] += 1
                continue
            eid = event["id"]
            matched_events[eid] = Event(
                event["source_id"], key, event["start"], event["home"], event["away"], event["status"]
            )
            money = source.get("moneyline")
            if money and money["type"] == "two_way_moneyline":
                for selection in money["outcomes"]:
                    when = captured_at(selection, now, max_age)
                    side = selection.get("side")
                    if when is None or side not in {"home", "away"}:
                        counts["stale_or_invalid_selections"] += 1
                        continue
                    q = Quote(
                        eid,
                        BOOK.id,
                        "h2h",
                        "full",
                        None,
                        None,
                        False,
                        event[side],
                        None,
                        str(selection.get("source_market_instance_id") or source["source_event_id"]),
                        str(selection["source_selection_id"]),
                        selection["price"]["american"],
                        Availability.SUSPENDED
                        if selection.get("source_suspended") not in {None, "", "0"}
                        else Availability.AVAILABLE,
                        when,
                        expires_at=min(event["start"], when + timedelta(seconds=max_age)),
                    )
                    quotes["moneyline"][q.selection_id] = q
            for prop in source["player_props"]:
                market = MARKETS.get(source_league["title"], {}).get(prop["source_label"])
                if (
                    not market
                    or prop.get("offering_context") not in {"league_player_props", "event_player_props"}
                    or not prop.get("both_sides_present")
                ):
                    counts["unsupported_prop_groups"] += 1
                    continue
                for selection in prop["selections"]:
                    when = captured_at(selection, now, max_age)
                    token = (
                        eid,
                        market,
                        normalized(prop["player"]),
                        Decimal(str(prop["point"])),
                        selection.get("comparison"),
                    )
                    templates = supported.get(token, {})
                    if len(templates) != 1 or when is None:
                        counts["unshared_or_stale_props"] += 1
                        continue
                    template = next(iter(templates.values()))
                    q = replace(
                        template,
                        book_id=BOOK.id,
                        source_market_id=str(selection["source_market_instance_id"]),
                        source_selection_id=str(selection["source_selection_id"]),
                        price=selection["price"]["american"],
                        state=Availability.SUSPENDED
                        if selection.get("source_suspended") not in {None, "", "0"}
                        else Availability.AVAILABLE,
                        collected_at=when,
                        source_updated_at=None,
                        deep_link=None,
                        expires_at=min(event["start"], when + timedelta(seconds=max_age)),
                    )
                    quotes["props"][q.selection_id] = q
        covered = (
            coverage.get(key, ())
            if coverage is not None
            else ("h2h", *MARKETS.get(source_league["title"], {}).values())
        )
        for kind in ("moneyline", "props"):
            markets = tuple(m for m in covered if (m == "h2h") == (kind == "moneyline"))
            if not markets:
                continue
            selected = tuple(q for q in quotes[kind].values() if q.market in markets)
            result.append(
                Board(
                    league,
                    kind,
                    tuple(matched_events.values()),
                    (BOOK,),
                    selected,
                    now,
                    True,
                    provider="bet365",
                    covered_markets=markets,
                )
            )
            counts[kind + "_selections"] += len(selected)
    return result, dict(counts)
