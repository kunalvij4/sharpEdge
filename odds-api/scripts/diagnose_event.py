"""Explain stored market availability for an event without contacting the provider."""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from types import SimpleNamespace

from odds_api.application.services import OddsQueryService
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.repository import SqlRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event_id")
    parser.add_argument("--sport", default="basketball_nba")
    parser.add_argument("--market", default="player_points")
    args = parser.parse_args()
    settings, now = Settings(), datetime.now(UTC)
    repository = SqlRepository(settings.database_url, settings.leagues)
    try:
        events = repository.events(args.sport)
        event = next((e for e in events if e["id"] == args.event_id), None)
        rows = repository.quotes(args.sport)
        target = [r["quote"] for r in rows if r["quote"].event_id == args.event_id]
        quotes = [q for q in target if q.market == args.market]
        all_market = [r["quote"] for r in rows if r["quote"].market == args.market]
        last_collected = max((q.collected_at for q in quotes), default=None)
        replay = None
        if event and last_collected:
            service = OddsQueryService(
                repository,
                SimpleNamespace(now=lambda: last_collected),
                settings.collected_ttl,
                settings.source_ttl,
                {args.market},
            )
            payload = service.odds(args.sport, event_id=args.event_id, markets=args.market)
            replay = {
                "observed_at": last_collected,
                "bookmakers": len(payload["bookmakers"]),
                "outcomes": sum(len(m["outcomes"]) for b in payload["bookmakers"] for m in b["markets"]),
            }
        status = repository.status(now, settings.collected_ttl, settings.source_ttl)
        report = {
            "observed_at": now,
            "event": event,
            "market": args.market,
            "freshness": {"collected_ttl": settings.collected_ttl, "source_ttl": settings.source_ttl},
            "event_stored_markets": dict(Counter(q.market for q in target)),
            "target_market_stored_quotes": len(quotes),
            "target_market_availability": dict(
                Counter(
                    q.availability(now, settings.collected_ttl, settings.source_ttl).value for q in quotes
                )
            ),
            "target_market_stored_states": dict(Counter(q.state.value for q in quotes)),
            "target_market_last_collected": last_collected,
            "diagnostic_replay_at_last_collection": replay,
            "target_market_source_times": {
                "oldest": min((q.source_updated_at for q in quotes if q.source_updated_at), default=None),
                "newest": max((q.source_updated_at for q in quotes if q.source_updated_at), default=None),
            },
            "league_market_stored_quotes": len(all_market),
            "league_market_availability": dict(
                Counter(
                    q.availability(now, settings.collected_ttl, settings.source_ttl).value for q in all_market
                )
            ),
            "league_market_events": len({q.event_id for q in all_market}),
            "scopes": [s for s in status["scopes"] if s["league"] == args.sport],
            "provider_metrics": status["provider_metrics"],
        }
        print(json.dumps(report, indent=2, default=str), flush=True)
    finally:
        repository.close()


if __name__ == "__main__":
    main()
