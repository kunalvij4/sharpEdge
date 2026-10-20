"""Read-only, credential-safe provider diagnostics; stop the collector first."""

import argparse
import asyncio
import json
from collections import Counter

import httpx

from odds_api.infrastructure.clock import SystemClock
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.normalization import values
from odds_api.infrastructure.repository import SqlRepository


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mlb-recovery", action="store_true", help="Try the intermittent MLB board up to three times"
    )
    args = parser.parse_args()
    settings, clock = Settings(), SystemClock()
    repository = SqlRepository(settings.database_url, settings.leagues)
    try:
        status = repository.status(clock.now(), settings.collected_ttl, settings.source_ttl)
        print(json.dumps({"provider_metrics": status["provider_metrics"]}), flush=True)
    finally:
        repository.close()
    async with httpx.AsyncClient(
        base_url=settings.unabated_api_base_url,
        headers={"X-Api-Key": settings.unabated_api_key.get_secret_value()},
        timeout=25,
    ) as http:

        async def get(path):
            started = clock.monotonic()
            response = await http.get(path)
            body = response.json() if response.status_code == 200 else {}
            # Raw messages and HTTP headers may contain secrets. Report only a known classification.
            messages = body.get("messages") or []
            known_error = "An error occurred while processing your request."
            reason = "provider_processing_error" if known_error in json.dumps(body) else "other_or_no_message"
            print(
                json.dumps(
                    {
                        "path": path,
                        "status": response.status_code,
                        "success": body.get("success"),
                        "reason": reason,
                        "messages_type": type(messages).__name__,
                        "messages_present": bool(messages),
                        "message_present": bool(body.get("message")),
                        "duration": round(clock.monotonic() - started, 3),
                    }
                ),
                flush=True,
            )
            return body.get("data") if body.get("success") is True else None

        bets = values(await get("/bettype"))
        wanted = {
            1,
            14,
            17,
            18,
            19,
            73,
            85,
            122,
            123,
            124,
            126,
            133,
            135,
            136,
            137,
            138,
            140,
            142,
            173,
            1656,
            1657,
        }
        print(
            json.dumps(
                {
                    "bet_definitions": [
                        {k: b.get(k) for k in ("id", "name", "description", "abbreviation") if k in b}
                        for b in bets
                        if b["id"] in wanted
                    ]
                }
            ),
            flush=True,
        )
        for route in ("nba", "nfl", "mlb"):
            periods = values(await get("/period-type/" + route))
            print(json.dumps({"league": route, "period_definitions": periods}), flush=True)
        for route in ("mlb",) * 3 if args.mlb_recovery else ("mlb", "nba", "nfl"):
            await asyncio.sleep(6)
            data = await get("/market/" + route + "/props/odds")
            if data is None:
                continue
            counts = Counter()
            for league in values(data.get("odds")):
                for period in values(league.get("periodTypes")):
                    for phase in ("pregame", "live"):
                        for group in values(period.get(phase)):
                            subtype = str(group.get("betSubType"))
                            if len(subtype) > 64 or settings.unabated_api_key.get_secret_value() in subtype:
                                subtype = "redacted"
                            counts[(group["betTypeId"], period["periodTypeId"], subtype)] += 1
            print(
                json.dumps(
                    {
                        "league": route,
                        "group_counts": [
                            {"bet": b, "period": p, "subtype": s, "count": count}
                            for (b, p, s), count in sorted(counts.items())
                        ],
                    }
                ),
                flush=True,
            )
            if args.mlb_recovery:
                break


if __name__ == "__main__":
    asyncio.run(main())
