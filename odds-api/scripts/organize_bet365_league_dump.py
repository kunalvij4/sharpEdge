"""Export headed league captures with explicit O/U sides and source evidence.

Only HTTP snapshots are normalized. WebSocket deltas require a separate stateful
reducer and are deliberately not treated as complete market tables.
"""

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from scripts.organize_bet365_dump import event_data, organize, prices

GAME_LINE_LABELS = {
    "Money": "Money",
    "Spread": "Spread",
    "Total": "Total",
    "Ganador": "Money",
    "Línea": "Spread",
    "LÃ\u00adnea": "Spread",
    "L\u00c3\u0192\u00c2\u00adnea": "Spread",
}

# These full-game event tables expose an explicit 1+ column, not an O/U line.
NHL_NATIVE_MARKETS = {
    "170600": ("Shots on Goal", "player_shots_on_goal_1plus", "player_shots_on_goal"),
    "170601": ("Points", "player_points_1plus", "player_points"),
    "170602": ("Assists", "player_assists_1plus", "player_assists"),
}


def source_ref(message, message_index, record_index):
    return {
        "message_index": message_index,
        "record_index": record_index,
        **{key: message[key] for key in ("received_at", "source_url", "stage")},
    }


def blocks(rows):
    """Keep descriptors and every cell, including empty/suspended placeholders."""
    group, columns, current = None, [], None
    for index, row in enumerate(rows):
        kind, fields = row["type"], row["fields"]
        if kind in {"MG", "CL", "EV"}:
            if group:
                yield group, columns
            group, columns, current = (index, fields) if kind == "MG" else None, [], None
        elif kind == "MA" and group:
            current = {"index": index, "fields": fields, "cells": []}
            columns.append(current)
        elif kind == "PA" and current is not None:
            current["cells"].append((index, fields))
    if group:
        yield group, columns


def organize_leagues(messages, pages=(), region="nj", prop_views=()):
    if any(message.get("transport") == "websocket" for message in messages):
        raise ValueError("Normalize HTTP snapshots only; remove WebSocket deltas first")
    expected_host = f"www.{region}.bet365.com"
    if any(urlsplit(message["source_url"]).hostname != expected_host for message in messages):
        raise ValueError("Capture region/host mismatch")
    report = organize(messages, pages, prop_views=prop_views, region=region)
    report["source"]["capture"] = "public HTTP homepage and league snapshots"
    report["websocket_deltas_applied"] = False
    issues = []
    unavailable_moneylines = []
    events = {
        league["title"]: {e["source_event_id"]: e for e in league["events"]} for league in report["leagues"]
    }
    labels = {}

    def event(league, identifier, name, start=None):
        if league not in events or not identifier or " @ " not in name:
            return None
        result = events[league].setdefault(identifier, event_data(identifier, league, name, start))
        if start:
            result["start_time_source"] = start
        return result

    # Resolve fixtures and menu labels before reading price columns.
    for message in messages:
        league = None
        for row in message["records"]:
            f = row["fields"]
            league = f.get("L3") or f.get("CC") or league
            if row["type"] == "MA" and f.get("PD") and f.get("NA"):
                match = re.search(r"#E([^#]+)#", f["PD"])
                if match and "#D19#" not in f["PD"]:
                    labels[match[1]] = f["NA"]
            if row["type"] == "EV" and f.get("N2") and f.get("N3"):
                event(league, f.get("OI"), f["N2"] + " @ " + f["N3"], f.get("BC"))
            if row["type"] == "MG" and f.get("SY") == "fe":
                event(league, f.get("FI"), f.get("NA", ""), f.get("BC"))
        for _, columns in blocks(message["records"]):
            for column in columns:
                if column["fields"].get("SY") == "ef":
                    for _, f in column["cells"]:
                        if f.get("NA") and f.get("N2"):
                            event(league, f.get("OI") or f.get("FI"), f["NA"] + " @ " + f["N2"], f.get("BC"))

    buckets = {}
    for mi, message in enumerate(messages):
        if "/contentdata/" not in message["source_url"]:
            continue
        rows = message["records"]
        league = next(
            (
                r["fields"].get("L3") or r["fields"].get("CC")
                for r in rows
                if (r["fields"].get("L3") or r["fields"].get("CC")) in events
            ),
            None,
        )
        if league is None:
            continue
        for (gi, group), columns in blocks(rows):
            for column in columns:
                market = column["fields"]
                label = GAME_LINE_LABELS.get(market.get("NA"))
                if market.get("SY") not in {"eo", "eb"} or label not in {"Spread", "Total"}:
                    continue
                pairs = defaultdict(list)
                for ri, cell in column["cells"]:
                    if cell.get("OI"):
                        pairs[cell["OI"]].append((ri, cell))
                for identifier, pair in pairs.items():
                    target = events[league].get(identifier)
                    if target is None or len(pair) != 2 or not all(f.get("OD") for _, f in pair):
                        continue
                    try:
                        points = [float(cell.get("HA")) for _, cell in pair]
                        if not all(math.isfinite(point) for point in points):
                            raise ValueError("Invalid line")
                        if label == "Spread":
                            if points[0] != -points[1]:
                                raise ValueError("Spread sides do not agree")
                            sides = ("away", "home")
                        else:
                            sides = tuple(cell.get("HD", "").split(" ", 1)[0] for _, cell in pair)
                            if set(sides) != {"O", "U"} or points[0] != points[1]:
                                raise ValueError("Total sides do not agree")
                            sides = tuple("over" if side == "O" else "under" for side in sides)
                        selections = [
                            {
                                "side": side,
                                "point": point,
                                "price": prices(cell["OD"]),
                                "source_selection_id": cell.get("ID"),
                                "source_market_instance_id": cell.get("FI"),
                                "source_suspended": cell.get("SU"),
                                "source": source_ref(message, mi, ri),
                            }
                            for ((ri, cell), side, point) in zip(pair, sides, points, strict=True)
                        ]
                    except (TypeError, ValueError, ZeroDivisionError):
                        issues.append({"message_index": mi, "type": "invalid_game_line_pair"})
                        continue
                    market_key = "spreads" if label == "Spread" else "totals"
                    target["game_lines"] = [g for g in target["game_lines"] if g["market"] != market_key]
                    target["game_lines"].append({"market": market_key, "outcomes": selections})
            # League Game Lines lists away/home fixtures, then paired price cells.
            for column in columns:
                market = column["fields"]
                if market.get("SY") not in {"eo", "eb"} or GAME_LINE_LABELS.get(market.get("NA")) != "Money":
                    continue
                pairs = defaultdict(list)
                for ri, cell in column["cells"]:
                    if cell.get("OI"):
                        pairs[cell["OI"]].append((ri, cell))
                for identifier, pair in pairs.items():
                    target = events[league].get(identifier)
                    if target is not None and len(pair) == 2 and not any(f.get("OD") for _, f in pair):
                        unavailable_moneylines.append(
                            {
                                "message_index": mi,
                                "league": league,
                                "event_id": identifier,
                                "reason": "both_prices_unavailable",
                                "source_suspended": [f.get("SU") for _, f in pair],
                            }
                        )
                        continue
                    if target is None or len(pair) != 2 or not all(f.get("OD") for _, f in pair):
                        issues.append(
                            {"message_index": mi, "type": "invalid_moneyline_pair", "event_id": identifier}
                        )
                        continue
                    outcomes = []
                    for (ri, cell), side in zip(pair, ("away", "home"), strict=True):
                        outcomes.append(
                            {
                                "name": target[side + "_team"],
                                "side": side,
                                "price": prices(cell["OD"]),
                                "source_selection_id": cell.get("ID"),
                                "source_market_instance_id": cell.get("FI"),
                                "source_market_type_id": market.get("MA"),
                                "source_suspended": cell.get("SU"),
                                "source": source_ref(message, mi, ri),
                            }
                        )
                    target["moneyline"] = {
                        "source_label": "Money",
                        "type": "two_way_moneyline",
                        "settlement_rules_verified": False,
                        "outcomes": outcomes,
                    }

            if group.get("SY") not in {"fe", "mgi", "mgh"}:
                continue
            market_type = group.get("MA") or group.get("ID")
            title = labels.get(market_type) if group.get("SY") == "fe" else group.get("NA")
            if not title or not title.endswith("O/U"):
                continue
            descriptor = next((c for c in columns if c["fields"].get("SY") == "dp"), None)
            sides = {
                c["fields"].get("NA"): c
                for c in columns
                if c["fields"].get("SY") == "dc" and c["fields"].get("NA") in {"Over", "Under"}
            }
            if descriptor is None or not sides:
                continue
            players = descriptor["cells"]
            if any(len(c["cells"]) != len(players) for c in sides.values()):
                issues.append({"message_index": mi, "record_index": gi, "type": "column_length_mismatch"})
                continue
            over = sides.get("Over")
            if over and any(
                cell.get("OD") and player.get("ID", "").removeprefix("PC").removeprefix("P") != cell.get("ID")
                for (_, player), (_, cell) in zip(players, over["cells"], strict=True)
            ):
                issues.append({"message_index": mi, "record_index": gi, "type": "player_order_mismatch"})
                continue
            identifier = group.get("FI") if group.get("SY") == "fe" else descriptor["fields"].get("PF")
            target = events[league].get(identifier)
            if target is None:
                issues.append({"message_index": mi, "record_index": gi, "type": "unresolved_ou_context"})
                continue
            for position, (pi, player) in enumerate(players):
                player_id = re.search(r"#P(\d+)(?:#|$)", player.get("PD", ""))
                if not player.get("NA") or not player.get("ID"):
                    issues.append(
                        {"message_index": mi, "record_index": pi, "type": "missing_player_descriptor"}
                    )
                    continue
                for side, column in sides.items():
                    ri, cell = column["cells"][position]
                    if not cell.get("OD"):
                        continue
                    point_raw = cell.get("HA") or cell.get("HD")
                    try:
                        point = float(point_raw)
                        price = prices(cell["OD"])
                    except (TypeError, ValueError, ZeroDivisionError):
                        issues.append(
                            {"message_index": mi, "record_index": ri, "type": "invalid_ou_line_or_price"}
                        )
                        continue
                    identity = player_id[1] if player_id else "descriptor:" + player["ID"]
                    key = (league, identifier, market_type, identity, point)
                    if key not in buckets:
                        buckets[key] = {
                            "source_label": title,
                            "source_market_type_id": market_type,
                            "player": player["NA"],
                            "source_player_id": player_id[1] if player_id else None,
                            "source_player_descriptor_id": player.get("ID"),
                            "offering_context": "league_player_props"
                            if group.get("SY") == "fe"
                            else "event_player_props",
                            "standalone_bet_availability_verified": False,
                            "settlement": "explicit_over_under; rules_and_period_unverified",
                            "mapped_api_market": None,
                            "player_fixture_association_verified": False,
                            "point": point,
                            "player_source": source_ref(message, mi, pi),
                            "selections": {},
                        }
                        target["player_props"].append(buckets[key])
                    buckets[key]["selections"][side] = {
                        "source_selection_label": side,
                        "comparison": side.lower(),
                        "threshold": point,
                        "line_source": point_raw,
                        "price": price,
                        "source_selection_id": cell.get("ID"),
                        "source_market_instance_id": cell.get("FI") or column["fields"].get("FI"),
                        "source_suspended": cell.get("SU"),
                        "source": source_ref(message, mi, ri),
                        "player_source": source_ref(message, mi, pi),
                        "column_source": source_ref(message, mi, column["index"]),
                        "column_row_index": position,
                    }

    native = {}
    for mi, message in enumerate(messages):
        if not message["stage"].startswith("nhl_event_"):
            continue
        rows = message["records"]
        for (gi, group), columns in blocks(rows):
            definition = NHL_NATIVE_MARKETS.get(group.get("ID"))
            if not definition or group.get("NA") != definition[0] or group.get("SY") != "mgh":
                continue
            descriptor = next((c for c in columns if c["fields"].get("SY") == "dv"), None)
            column = next((c for c in columns if c["fields"].get("SY") == "dw"), None)
            if not descriptor or not column:
                continue
            target = events["NHL"].get(descriptor["fields"].get("PF"))
            if target is None:
                continue
            cells, column_index = [], None
            for ri in range(column["index"] + 1, len(rows)):
                row = rows[ri]
                if row["type"] in {"MA", "MG", "EV", "CL"}:
                    break
                if row["type"] == "CO":
                    if column_index is not None:
                        break
                    if row["fields"].get("NA") == "1" and row["fields"].get("SY") == "ipg":
                        column_index = ri
                elif row["type"] == "PA" and column_index is not None:
                    cells.append((ri, row["fields"]))
            if column_index is None:
                continue
            players = descriptor["cells"]
            if len(players) != len(cells) or any(
                cell.get("OD") and player.get("ID", "").removeprefix("PC") != cell.get("ID")
                for (_, player), (_, cell) in zip(players, cells)
            ):
                issues.append(
                    {"message_index": mi, "record_index": gi, "type": "native_player_order_mismatch"}
                )
                continue
            for position, ((pi, player), (ri, cell)) in enumerate(zip(players, cells, strict=True)):
                if not cell.get("OD"):
                    continue
                key = (target["source_event_id"], group["ID"], player["ID"])
                selection = {
                    "source_selection_label": "1+",
                    "threshold": 1,
                    "comparison": None,
                    "price": prices(cell["OD"]),
                    "source_selection_id": cell["ID"],
                    "source_market_instance_id": cell.get("FI"),
                    "source_suspended": cell.get("SU"),
                    "source": source_ref(message, mi, ri),
                    "player_source": source_ref(message, mi, pi),
                    "column_source": source_ref(message, mi, column_index),
                    "column_row_index": position,
                }
                if key not in native:
                    native[key] = {
                        "source_label": definition[0],
                        "native_market": definition[1],
                        "support_market": definition[2],
                        "source_market_type_id": group["ID"],
                        "player": player["NA"],
                        "source_player_descriptor_id": player["ID"],
                        "offering_context": "event_player_milestone",
                        "both_sides_present": False,
                        "threshold": 1,
                        "selections": [],
                    }
                    target["player_props"].append(native[key])
                native[key]["selections"] = [selection]

    text = "\n".join(p["text"] for p in pages)
    for bucket in buckets.values():
        bucket["selections"] = list(bucket["selections"].values())
        bucket["both_sides_present"] = {s["comparison"] for s in bucket["selections"]} == {"over", "under"}
    for league in report["leagues"]:
        league["events"] = [
            event
            for event in events[league["title"]].values()
            if event["moneyline"] or event["player_props"] or event["game_lines"]
        ]
        counts = Counter(
            dict.fromkeys(
                (
                    "moneyline_events",
                    "game_line_outcomes",
                    "moneyline_outcomes",
                    "moneyline_events_ui_price_matched",
                    "player_prop_groups",
                    "player_prop_selections",
                    "over_under_player_lines",
                    "over_under_selections",
                    "over_under_complete_pairs",
                ),
                0,
            )
        )
        counts["events"] = len(league["events"])
        for target in league["events"]:
            counts["game_line_outcomes"] += sum(len(g["outcomes"]) for g in target["game_lines"])
            moneyline = target["moneyline"]
            if moneyline:
                outcomes = moneyline["outcomes"]
                pattern = re.escape(target["away_team"]) + r"[\s\S]{0,100}?" + re.escape(target["home_team"])
                excerpts = [text[m.start() : m.start() + 700] for m in re.finditer(pattern, text)]
                pair = "\n".join(f"{o['price']['american']:+d}" for o in outcomes)
                match = next((excerpt for excerpt in excerpts if pair in excerpt), None)
                moneyline["page_text_price_pair_matches"] = match is not None
                moneyline["page_text_excerpt"] = match
                counts.update(
                    moneyline_events=1,
                    moneyline_outcomes=len(outcomes),
                    moneyline_events_ui_price_matched=int(match is not None),
                )
            counts["player_prop_groups"] += len(target["player_props"])
            for bucket in target["player_props"]:
                counts["player_prop_selections"] += len(bucket["selections"])
                if "point" in bucket:
                    counts["over_under_player_lines"] += 1
                    counts["over_under_selections"] += len(bucket["selections"])
                    counts["over_under_complete_pairs"] += int(bucket["both_sides_present"])
        league["summary"] = dict(counts)
    report["summary"] = {
        key: sum(league["summary"][key] for league in report["leagues"])
        for key in report["leagues"][0]["summary"]
    }
    report["normalization_issues"] = issues
    report["source_unavailable_moneylines"] = unavailable_moneylines
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", nargs="+", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--region", choices=("va", "nj"), default="nj")
    args = parser.parse_args()
    messages, pages, prop_views = [], [], []
    for directory in args.input_dir:
        captured = json.loads((directory / "messages.json").read_text(encoding="utf-8"))
        messages.extend(
            {**m, "source_capture": directory.name} for m in captured if m.get("transport") != "websocket"
        )
        pages.extend(
            {**p, "source_capture": directory.name}
            for p in json.loads((directory / "pages.json").read_text(encoding="utf-8"))
        )
        views_file = directory / "prop-views.json"
        if views_file.exists():
            prop_views.extend(json.loads(views_file.read_text(encoding="utf-8")))
    report = organize_leagues(messages, pages, args.region, prop_views)
    report["source_capture_directories"] = [directory.name for directory in args.input_dir]
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    exports = {
        "odds": report,
        "messages": messages,
        "pages": pages,
        "prop-views": prop_views,
        "summary": {
            "source": report["source"],
            "summary": report["summary"],
            "leagues": [{"title": league["title"], **league["summary"]} for league in report["leagues"]],
            "normalization_issues": report["normalization_issues"],
        },
    }
    for league in report["leagues"]:
        exports[league["title"].lower()] = {
            "source": report["source"],
            "verification_only": True,
            "coverage_complete": False,
            **league,
        }
    for name, data in exports.items():
        (output / (name + ".json")).write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "output": str(output / "odds.json"),
                "summary": report["summary"],
                "normalization_issues": len(report["normalization_issues"]),
            }
        )
    )


if __name__ == "__main__":
    main()
