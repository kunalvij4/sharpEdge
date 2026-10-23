"""Verify live event props and cache labels through our API, without provider calls."""

import json
import urllib.request
from collections import Counter
from datetime import UTC, datetime

from odds_api.domain.models import Availability
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.repository import SqlRepository


def main():
    settings, now = Settings(), datetime.now(UTC)
    key = next(value.strip() for value in settings.api_keys.get_secret_value().split(",") if value.strip())

    def get(path):
        request = urllib.request.Request("http://127.0.0.1:8000" + path, headers={"X-API-Key": key})
        with urllib.request.urlopen(request, timeout=40) as response:
            return json.load(response), response.headers.get("X-Odds-Data-Status")

    def summarize(path):
        payload, header = get(path)
        outcomes = [o for b in payload["bookmakers"] for m in b["markets"] for o in m["outcomes"]]
        assert all("freshness" in outcome for outcome in outcomes)
        assert all(
            o["freshness"]["actionable"] is False for o in outcomes if o["freshness"]["status"] == "stale"
        )
        report = {
            "path": path,
            "event": payload["away_team"] + " at " + payload["home_team"],
            "bookmakers": len(payload["bookmakers"]),
            "market_keys": sorted({m["key"] for b in payload["bookmakers"] for m in b["markets"]}),
            "outcomes": len(outcomes),
            "freshness": payload.get("freshness"),
            "freshness_header": header,
        }
        print(json.dumps(report), flush=True)
        return outcomes

    repository = SqlRepository(settings.database_url, settings.leagues)
    try:
        target = "275f9649fc6e5e69b4e35ccd890aa8e8"
        path = "/v1/events/" + target
        assert summarize(path + "/odds?markets=player_points&oddsFormat=american"), (
            "Target points still empty"
        )
        assert summarize(path + "/props?oddsFormat=american"), "NBA all-props endpoint empty"
        summarize(path + "/props?freshOnly=true&oddsFormat=american")
        for sport in ("nfl_football",):
            eligible = Counter()
            for row in repository.quotes(sport):
                q = row["quote"]
                if q.player_id and q.state == Availability.AVAILABLE:
                    if (now - q.collected_at).total_seconds() <= settings.props_cache_ttl:
                        if (
                            not q.source_updated_at
                            or (now - q.source_updated_at).total_seconds() <= settings.source_ttl
                        ):
                            eligible[q.event_id] += 1
            assert eligible, "No eligible NFL props are currently stored"
            event_id = eligible.most_common(1)[0][0]
            assert summarize("/v1/events/" + event_id + "/props?oddsFormat=american")
        status, _ = get("/v1/status")
        print(
            json.dumps(
                {
                    "observed_at": status["observed_at"],
                    "collector_healthy": status["collector_healthy"],
                    "provider_metrics": status["provider_metrics"],
                }
            ),
            flush=True,
        )
    finally:
        repository.close()


if __name__ == "__main__":
    main()
