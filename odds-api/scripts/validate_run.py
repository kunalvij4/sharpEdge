"""Observe persisted event transitions; never requests upstream data."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.repository import SqlRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=7200)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--output", type=Path, default=Path("validation.json"))
    args = parser.parse_args()
    if args.seconds <= 0 or args.interval <= 0:
        parser.error("seconds and interval must be positive")
    settings = Settings()
    repository = SqlRepository(settings.database_url, settings.leagues)
    started, deadline, seen = datetime.now(UTC), time.monotonic() + args.seconds, {}
    try:
        while True:
            for sport in settings.leagues:
                for event in repository.events(sport):
                    seen.setdefault(event["id"], set()).add(event["status"])
            now = datetime.now(UTC)
            complete = [eid for eid, states in seen.items() if {"pregame", "live", "final"} <= states]
            report = {
                "started_at": started.isoformat(),
                "observed_at": now.isoformat(),
                "events": {eid: sorted(states) for eid, states in seen.items()},
                "pregame_live_final_events": complete,
                "status": repository.status(now, settings.collected_ttl, settings.source_ttl),
            }
            args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(args.interval, remaining))
    finally:
        repository.close()


if __name__ == "__main__":
    main()
