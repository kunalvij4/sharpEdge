"""Read-only verification of the running five-league API; never prints credentials."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

from odds_api.infrastructure.config import DEFAULT_LEAGUES


def verify(base_url="http://127.0.0.1:8000", output="artifacts/collection/api-verification.json"):
    key = os.environ["API_KEYS"].split(",")[0].strip()
    report = {"verified_at": datetime.now(UTC).isoformat(), "leagues": {}}
    with httpx.Client(base_url=base_url, headers={"X-API-Key": key}, timeout=120) as client:

        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        sports = get("/v1/sports")
        report["configured_leagues_correct"] = {s["key"] for s in sports} == set(DEFAULT_LEAGUES)
        status = get("/v1/status")
        report["collector_healthy"] = status["collector_healthy"]
        report["bet365_disabled"] = not status["bet365"]["enabled"]
        report["unabated_scopes"] = status["scopes"]
        report["propline"] = status["propline"]
        for league in DEFAULT_LEAGUES:
            games = get(f"/v1/sports/{league}/odds?markets=h2h,spreads&oddsFormat=american")
            book_keys = {book["key"] for game in games for book in game["bookmakers"]}
            row = {
                "games_with_odds": len(games),
                "books": len(book_keys),
                "unabated_present": any(k.startswith("unabated_") for k in book_keys),
                "propline_present": any(k.startswith("propline_") for k in book_keys),
                "unabated_game_lines_present": any(k.startswith("unabated_") for k in book_keys),
                "propline_game_lines_present": any(k.startswith("propline_") for k in book_keys),
                "bet365_absent": "bet365" not in book_keys,
            }
            common = next(
                (
                    g
                    for g in games
                    if any(b["key"].startswith("propline_") for b in g["bookmakers"])
                    and any(b["key"].startswith("unabated_") for b in g["bookmakers"])
                ),
                None,
            )
            candidates = ([common] if common else []) + games[:3]
            for candidate in candidates:
                props = get(f"/v1/events/{candidate['id']}/props?freshOnly=true")
                prop_books = {b["key"] for b in props["bookmakers"]}
                row["sample_event_id"] = candidate["id"]
                row["sample_prop_books"] = sorted(prop_books)
                row["unabated_present"] |= any(k.startswith("unabated_") for k in prop_books)
                row["propline_present"] |= any(k.startswith("propline_") for k in prop_books)
                row["bet365_absent"] &= "bet365" not in prop_books
                if row["unabated_present"] and row["propline_present"]:
                    break
            report["leagues"][league] = row
    report["passed"] = (
        report["configured_leagues_correct"]
        and report["collector_healthy"]
        and report["bet365_disabled"]
        and all(
            r["unabated_present"] and r["propline_present"] and r["bet365_absent"]
            for r in report["leagues"].values()
        )
    )
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "leagues": report["leagues"]}))
    return report


if __name__ == "__main__":
    raise SystemExit(0 if verify()["passed"] else 1)
