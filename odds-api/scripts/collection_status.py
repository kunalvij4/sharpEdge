"""Summarize the local API and collection status without printing credentials."""

import json
import urllib.request

from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.normalization import BET_NAMES


def main():
    settings = Settings()
    key = next(value.strip() for value in settings.api_keys.get_secret_value().split(",") if value.strip())

    def get(path):
        request = urllib.request.Request("http://127.0.0.1:8000" + path, headers={"X-API-Key": key})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    status = get("/v1/status")
    print(
        json.dumps(
            {
                "service": status["service"],
                "collector_healthy": status["collector_healthy"],
                "observed_at": status["observed_at"],
                "counts": status["counts"],
                "provider_metrics": status["provider_metrics"],
                "scopes": [
                    {
                        key: scope[key]
                        for key in ("league", "kind", "outcome", "selection_count", "last_attempt")
                    }
                    for scope in status["scopes"]
                ],
            }
        ),
        flush=True,
    )
    for sport in settings.leagues:
        odds = get("/v1/sports/" + sport + "/odds?oddsFormat=american")
        print(
            json.dumps(
                {
                    "sport": sport,
                    "actionable_moneyline_events": len(odds),
                    "bookmaker_entries": sum(len(event["bookmakers"]) for event in odds),
                }
            ),
            flush=True,
        )
        if odds:
            event_id = odds[0]["id"]
            markets = ",".join(sorted(set(BET_NAMES.values()) - {"h2h"}))
            props = get("/v1/events/" + event_id + "/odds?freshOnly=true&markets=" + markets)
            print(
                json.dumps(
                    {
                        "sport": sport,
                        "event_id": event_id,
                        "actionable_prop_outcomes": sum(
                            len(market["outcomes"])
                            for book in props["bookmakers"]
                            for market in book["markets"]
                        ),
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
