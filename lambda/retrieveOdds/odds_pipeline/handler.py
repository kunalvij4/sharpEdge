"""One five-minute run: fetch, calculate in memory, and publish results."""

from datetime import datetime, timezone
import logging
import os

from odds_pipeline.collect import fetch_and_attach_player_props
from odds_pipeline.engine import calculate
from odds_pipeline.leagues import ACTIVE_LEAGUE_SPORT_KEYS
from odds_pipeline.results import ResultsPublisher
from .provider import OddsAPI


logger = logging.getLogger(__name__)


def utc_now():
    return datetime.now(timezone.utc)


def lambda_handler(event, context):
    api = OddsAPI(os.environ["ODDS_API_KEY"], os.environ["ODDS_API_BASE_URL"])
    publisher = ResultsPublisher()
    summary = {
        "status": "complete", "events_fetched": 0,
        "ev_bets_found": 0, "arbitrage_found": 0, "failed_leagues": [],
        "props_failed_events": {}, "publish_failures": [],
    }

    for league, sport_key in ACTIVE_LEAGUE_SPORT_KEYS.items():
        try:
            raw = api.get_odds(sport_key, markets="h2h,spreads")
            observed_at = utc_now()
            games = api.parse_all_markets_odds(raw)
            # Some events have player props without actionable game lines.
            for event_id, game in api.parse_all_markets_odds(api.get_events(sport_key)).items():
                games.setdefault(event_id, game)
            summary["events_fetched"] += len(games)
            failures = []
            fetch_and_attach_player_props(
                api, sport_key, games, failed_events=failures,
            )
            if failures:
                summary["props_failed_events"][league] = failures
            ev, arbitrage = calculate(league, games)
            summary["ev_bets_found"] += sum(map(len, ev.values()))
            summary["arbitrage_found"] += sum(map(len, arbitrage.values()))
            summary["publish_failures"].extend(publisher.publish(
                league, ev, arbitrage, observed_at.isoformat(), include_props=not failures,
            ))
        except Exception as error:
            logger.warning("Pipeline failed for %s (%s)", league, type(error).__name__)
            summary["failed_leagues"].append(league)
    if any(summary[key] for key in ("failed_leagues", "props_failed_events", "publish_failures")):
        summary["status"] = "partial"
    return summary
