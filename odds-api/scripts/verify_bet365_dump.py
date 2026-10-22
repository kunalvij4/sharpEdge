"""Check exported prices and player/column references against captured records."""

import argparse
import json
import re
from pathlib import Path

from scripts.organize_bet365_dump import prices


def verify(report, messages):
    checked, ou_checked, errors = 0, 0, []

    def fields(reference):
        return messages[reference["message_index"]]["records"][reference["record_index"]]["fields"]

    for league in report["leagues"]:
        for event in league["events"]:
            groups = event["player_props"]
            selections = [(None, s) for s in (event.get("moneyline") or {}).get("outcomes", [])]
            selections.extend((group, s) for group in groups for s in group["selections"])
            for group, selection in selections:
                checked += 1
                problems = []
                try:
                    source = fields(selection["source"])
                    if source.get("ID") != selection["source_selection_id"]:
                        problems.append("selection_id_mismatch")
                    if (
                        source.get("OD") != selection["price"]["fractional"]
                        or prices(source["OD"]) != selection["price"]
                    ):
                        problems.append("price_mismatch")
                    if selection.get("comparison") in {"over", "under"}:
                        ou_checked += 1
                        if float(source.get("HA") or source.get("HD")) != selection["threshold"]:
                            problems.append("line_mismatch")
                        player = fields(selection["player_source"])
                        player_id = re.search(r"#P(\d+)(?:#|$)", player.get("PD", ""))
                        if (
                            player.get("NA") != group["player"]
                            or player.get("ID") != group["source_player_descriptor_id"]
                            or (
                                group["source_player_id"] is not None
                                and (player_id is None or player_id[1] != group["source_player_id"])
                            )
                        ):
                            problems.append("player_descriptor_mismatch")
                        column = fields(selection["column_source"])
                        if column.get("NA", "").lower() != selection["comparison"]:
                            problems.append("side_column_mismatch")
                        ref = selection["column_source"]
                        rows = messages[ref["message_index"]]["records"]
                        cells = []
                        for index in range(ref["record_index"] + 1, len(rows)):
                            if rows[index]["type"] in {"MA", "MG", "EV", "CL", "CO"}:
                                break
                            if rows[index]["type"] == "PA":
                                cells.append(index)
                        if cells[selection["column_row_index"]] != selection["source"]["record_index"]:
                            problems.append("column_row_mismatch")
                except (IndexError, KeyError, TypeError, ValueError, ZeroDivisionError) as error:
                    problems.append(type(error).__name__)
                if problems:
                    errors.append(
                        {
                            "league": league["title"],
                            "event_id": event["source_event_id"],
                            "selection_id": selection.get("source_selection_id"),
                            "errors": problems,
                        }
                    )
    return {
        "source_references_checked": checked,
        "over_under_references_checked": ou_checked,
        "moneyline_pairs_matching_page_text": report["summary"]["moneyline_events_ui_price_matched"],
        "errors": errors,
        "source_checks_passed": not errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    args = parser.parse_args()
    report = json.loads((args.input_dir / "odds.json").read_text(encoding="utf-8"))
    messages = json.loads((args.input_dir / "messages.json").read_text(encoding="utf-8"))
    result = verify(report, messages)
    (args.input_dir / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
