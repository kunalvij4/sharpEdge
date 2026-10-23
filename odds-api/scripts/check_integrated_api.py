"""Verify the real HTTP responses and persist a credential-free review artifact."""

import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from odds_api.infrastructure.config import Settings

s = Settings()
headers = {"X-API-Key": s.api_keys.get_secret_value().split(",")[0].strip()}


def get(path):
    request = urllib.request.Request("http://127.0.0.1:8000" + path, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


result = {
    "observed_at": datetime.now(UTC).isoformat(),
    "ready": get("/health/ready"),
    "status": get("/status"),
    "leagues": {},
}
for league in s.leagues:
    money = get(f"/v4/sports/{league}/odds?oddsFormat=american")
    matched = [e for e in money if any(b["key"] == "bet365" for b in e["bookmakers"])]
    props = []
    for event in matched:
        response = get(f"/v4/sports/{league}/events/{event['id']}/props?oddsFormat=american")
        if any(b["key"] == "bet365" for b in response["bookmakers"]):
            props.append(response)
    result["leagues"][league] = {
        "moneyline_events": len(money),
        "bet365_moneyline_events": len(matched),
        "existing_books": sorted({b["key"] for e in money for b in e["bookmakers"] if b["key"] != "bet365"}),
        "moneyline_sample": matched[:1],
        "props": props,
    }
path = Path("/app/artifacts/integration-api.json")
path.write_text(json.dumps(result, indent=2, default=str) + "\n")
print(
    json.dumps(
        {
            "ready": result["ready"],
            "collector_healthy": result["status"]["collector_healthy"],
            "collector_heartbeat": result["status"]["collector_heartbeat"],
            "leagues": {
                k: {
                    "moneyline_events": v["moneyline_events"],
                    "bet365_moneyline_events": v["bet365_moneyline_events"],
                    "existing_books": len(v["existing_books"]),
                    "events_with_bet365_props": len(v["props"]),
                    "bet365_prop_outcomes": sum(
                        len(m["outcomes"])
                        for e in v["props"]
                        for b in e["bookmakers"]
                        if b["key"] == "bet365"
                        for m in b["markets"]
                    ),
                }
                for k, v in result["leagues"].items()
            },
        }
    )
)
