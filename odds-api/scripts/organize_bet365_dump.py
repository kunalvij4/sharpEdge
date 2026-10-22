"""Organize captured public protocol records into a verification-only odds dump."""

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

LEAGUES = {"NBA": "basketball_nba", "NFL": "americanfootball_nfl", "MLB": "baseball_mlb"}
QUICK_PICK = {"Points", "Assists", "Rebounds", "Threes Made", "Double Double", "Triple Double"}


def prices(raw):
    ratio = Fraction(1) if raw.upper() in {"EVS", "EVENS"} else Fraction(raw)
    if ratio <= 0:
        raise ValueError("Odds must be positive")
    american = ratio * 100 if ratio >= 1 else -100 / ratio
    rounded = (Decimal(american.numerator) / Decimal(american.denominator)).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return {"fractional": raw, "decimal": round(1 + float(ratio), 8), "american": int(rounded)}


def route_event(value):
    match = re.search(r"#F(\d+)(?:#|$)", value)
    return match[1] if match else None


def event_data(identifier, league, name, start=None):
    teams = name.split(" @ ", 1)
    return {
        "source_event_id": identifier,
        "name": name,
        "away_team": teams[0] if len(teams) == 2 else None,
        "home_team": teams[1] if len(teams) == 2 else None,
        "start_time_source": start,
        "start_time_utc": None,
        "start_timezone_verified": False,
        "phase": "unverified",
        "moneyline": None,
        "player_props": [],
    }


def organize(messages, pages=(), prop_views=(), region="va"):
    events = {league: {} for league in LEAGUES}
    unmatched = {league: {} for league in LEAGUES}
    excluded = Counter()
    labels = {}
    for message in messages:
        for row in message["records"]:
            f, kind = row["fields"], row["type"]
            if f.get("TL") and f.get("NA") and not f.get("OD"):
                labels[f["TL"]] = f["NA"]
            league = f.get("L3")
            if league not in LEAGUES:
                continue
            identifier = None
            name = None
            if kind == "PA" and f.get("FD") and f.get("OI"):
                identifier, name = f["OI"], f["FD"]
            elif kind == "MG" and f.get("SY") == "ppg":
                identifier, name = route_event(f.get("PD", "")), f.get("NA")
            if identifier and name:
                target = events[league].setdefault(identifier, event_data(identifier, league, name))
                target["start_time_source"] = f.get("BC") or target["start_time_source"]
                target["source_flags"] = {k: f[k] for k in ("FS", "IA", "SU") if k in f}

    prop_buckets = {}
    for message_index, message in enumerate(messages):
        group = {}
        market = {}
        player = {}
        event_row = {}
        side_counters = Counter()
        column_players, column_cursor, column = [], 0, {}
        for record_index, row in enumerate(message["records"]):
            f, kind = row["fields"], row["type"]
            if kind in {"CL", "EV"}:
                group, market, player = {}, {}, {}
                event_row = f if kind == "EV" else {}
                continue
            if kind == "MG":
                group, market, player = f, {}, {}
                column_players, column_cursor, column = [], 0, {}
                continue
            if kind == "MA":
                market, player = f, f
                continue
            if kind == "CO":
                column, column_cursor = f, 0
                continue
            if kind == "PA" and group.get("SY") == "pps":
                if not f.get("OD") and re.search(r"#P\d+#", f.get("PD", "")):
                    column_players.append(f)
                elif f.get("OD") and column_cursor < len(column_players):
                    player = column_players[column_cursor]
                    column_cursor += 1
            if kind != "PA" or not f.get("OD"):
                continue
            try:
                price = prices(f["OD"])
            except (ValueError, ZeroDivisionError):
                excluded["invalid_price"] += 1
                continue
            source = {
                "message_index": message_index,
                "record_index": record_index,
                "received_at": message["received_at"],
                "source_url": message["source_url"],
                "stage": message["stage"],
            }
            league = f.get("L3") or market.get("L3") or group.get("L3") or event_row.get("L3")
            if market.get("SY") == "cpce" and market.get("NA") == "Money":
                identifier = f.get("OI")
                if league not in events or identifier not in events[league]:
                    excluded["unresolved_moneyline_event"] += 1
                    continue
                event = events[league][identifier]
                side = side_counters[(league, identifier)]
                side_counters[(league, identifier)] += 1
                if side >= 2 or not event["away_team"]:
                    excluded["unresolved_moneyline_side"] += 1
                    continue
                if event["moneyline"] is None:
                    event["moneyline"] = {
                        "source_label": "Money",
                        "type": "two_way_moneyline",
                        "outcomes": {},
                        "settlement_rules_verified": False,
                    }
                team = event["away_team"] if side == 0 else event["home_team"]
                event["moneyline"]["outcomes"][team] = {
                    "name": team,
                    "side": "away" if side == 0 else "home",
                    "price": price,
                    "source_selection_id": f.get("ID"),
                    "source_market_instance_id": f.get("FI"),
                    "source_market_type_id": market.get("MA"),
                    "source_suspended": f.get("SU"),
                    "source": source,
                }
                continue

            quick = group.get("NA") in QUICK_PICK and event_row.get("IT", "").startswith("#QP#")
            prop = group.get("SY") in {"pmm", "pps"} or quick
            player_match = re.search(r"#P(\d+)(?:#|$)", player.get("PD", ""))
            if not prop or league not in events or not player.get("NA") or not player_match:
                excluded["outside_supported_player_or_moneyline_structure"] += 1
                continue
            identifier = route_event(group.get("IT", ""))
            event = events[league].get(identifier)
            if event is None and player.get("N2"):
                name = player["N2"]
                matches = [e for e in events[league].values() if e["name"] == name]
                if len(matches) == 1:
                    event = matches[0]
                elif " @ " in name:
                    key = "unresolved:" + name
                    event = events[league].setdefault(key, event_data(None, league, name))
            title = group.get("NA")
            if not title or title == "Player / Last 5":
                topic = group.get("IT", "")
                matching_labels = [key for key in labels if topic.startswith(key)]
                title = (
                    labels[max(matching_labels, key=len)]
                    if matching_labels
                    else (title or "Unlabeled source market")
                )
            bucket_key = (league, identifier or player.get("N2"), title, player_match[1])
            if bucket_key not in prop_buckets:
                bucket = {
                    "source_label": title,
                    "source_market_type_id": f.get("MA") or group.get("ID", "").removeprefix("M"),
                    "player": player["NA"],
                    "offering_context": "homepage_quick_pick" if quick else "homepage_same_game_parlay_plus",
                    "standalone_bet_availability_verified": False,
                    "source_player_id": player_match[1],
                    "settlement": "source_threshold_or_yes_selection; verify displayed rules",
                    "mapped_api_market": None,
                    "player_fixture_association_verified": False,
                    "selections": {},
                }
                prop_buckets[bucket_key] = bucket
                if event is not None:
                    event["player_props"].append(bucket)
                else:
                    unmatched[league][bucket_key] = bucket
            bucket = prop_buckets[bucket_key]
            label = f.get("NA") or f.get("ED") or column.get("NA")
            try:
                threshold = float(label.rstrip("+")) if label is not None else None
            except ValueError:
                threshold = None
            selection = {
                "source_selection_label": label,
                "threshold": threshold,
                "comparison": None,
                "price": price,
                "source_selection_id": f.get("ID"),
                "source_market_instance_id": f.get("FI"),
                "source_suspended": f.get("SU"),
                "source": source,
            }
            bucket["selections"][f.get("ID") or str(record_index)] = selection

    all_text = "\n".join(p["text"] for p in pages)
    leagues = []
    for league, key in LEAGUES.items():
        league_events = list(events[league].values())
        for event in league_events:
            if event["moneyline"]:
                market = event["moneyline"]
                market["outcomes"] = list(market["outcomes"].values())
                display = [f"{o['price']['american']:+d}" for o in market["outcomes"]]
                pattern = (
                    re.escape(event["away_team"] or "")
                    + r"[\s\S]{0,100}?"
                    + re.escape(event["home_team"] or "")
                )
                excerpts = [
                    all_text[m.start() : m.start() + 600].split("Stats", 1)[0]
                    for m in re.finditer(pattern, all_text)
                ]
                matching = [
                    excerpt for excerpt in excerpts if len(display) == 2 and "\n".join(display) in excerpt
                ]
                excerpt = matching[0] if matching else (excerpts[0] if excerpts else "")
                market["page_text_price_pair_matches"] = bool(matching)
                market["page_text_excerpt"] = excerpt or None
            for bucket in event["player_props"]:
                bucket["selections"] = list(bucket["selections"].values())
        for bucket in unmatched[league].values():
            bucket["selections"] = list(bucket["selections"].values())
        league_events = [e for e in league_events if e["moneyline"] or e["player_props"]]
        leagues.append(
            {
                "key": key,
                "title": league,
                "events": league_events,
                "unmatched_player_props": list(unmatched[league].values()),
                "summary": {
                    "events": len(league_events),
                    "moneyline_events": sum(bool(e["moneyline"]) for e in league_events),
                    "moneyline_events_ui_price_matched": sum(
                        e["moneyline"]["page_text_price_pair_matches"]
                        for e in league_events
                        if e["moneyline"]
                    ),
                    "unresolved_event_associations": sum(e["source_event_id"] is None for e in league_events),
                    "moneyline_outcomes": sum(
                        len(e["moneyline"]["outcomes"]) for e in league_events if e["moneyline"]
                    ),
                    "player_prop_groups": sum(len(e["player_props"]) for e in league_events),
                    "player_prop_selections": sum(
                        len(b["selections"]) for e in league_events for b in e["player_props"]
                    ),
                    "unmatched_prop_selections": sum(
                        len(b["selections"]) for b in unmatched[league].values()
                    ),
                },
            }
        )
    return {
        "schema": "bet365-verification-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": {
            "bookmaker": "Bet365",
            "region": region,
            "site": f"https://www.{region}.bet365.com/",
            "browser_mode": "headed",
            "capture": "public HTTP snapshots",
        },
        "verification_only": True,
        "production_api_modified": False,
        "coverage_complete": False,
        "notes": [
            "Snapshot prices are historical observations, not executable or current quotes.",
            "Only observed homepage structures are extracted; this is not every event or prop offered.",
            "Threshold labels are preserved; no milestone is relabeled as a half-point over/under.",
            "Props come from homepage Quick Pick/SGP widgets; standalone availability and equivalent standalone prices are unverified.",
            "Null comparison and mapped_api_market mean settlement mapping requires verification.",
            "Source BC timestamps have no verified timezone; no UTC start time is invented.",
            "Source IDs for fixture, market instance, market type and player are kept separately.",
        ],
        "summary": {k: sum(item["summary"][k] for item in leagues) for k in leagues[0]["summary"]},
        "leagues": leagues,
        "ui_tab_evidence": [{k: v for k, v in p.items() if k != "text"} for p in prop_views],
        "excluded_record_counts": dict(excluded),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--region", choices=("va", "nj"), default="va")
    parser.add_argument("--additional-input-dir", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    def read(name):
        rows = []
        for directory in [args.input_dir, *args.additional_input_dir]:
            path = directory / name
            if path.exists():
                rows.extend(json.loads(path.read_text(encoding="utf-8")))
        return rows

    messages = sorted(read("messages.json"), key=lambda m: m["received_at"])
    result = organize(messages, read("pages.json"), read("prop-views.json"), args.region)
    output = args.output or args.input_dir / "odds.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    records_output = output.with_name(output.stem + "-source-records.json")
    result["source_records_file"] = records_output.name
    records_output.write_text(json.dumps(messages, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": result["summary"]}), flush=True)


if __name__ == "__main__":
    main()
