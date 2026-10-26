"""One five-minute run: fetch, archive eligible prices, calculate, and publish."""

from datetime import datetime, timezone
import logging
import os

from odds_pipeline.archive import ClosingOddsStore
from odds_pipeline.collect import fetch_and_attach_player_props
from odds_pipeline.engine import calculate
from odds_pipeline.leagues import LEAGUE_SPORT_KEYS
from odds_pipeline.results import ResultsPublisher
from .provider import OddsAPI


logger = logging.getLogger(__name__)


def utc_now():
    return datetime.now(timezone.utc)


def lambda_handler(event, context):
    api = OddsAPI(os.environ["ODDS_API_KEY"])
    archive = ClosingOddsStore()
    publisher = ResultsPublisher()
    summary = {
        "status": "complete", "events_fetched": 0, "closing_prices_written": 0,
        "ev_bets_found": 0, "arbitrage_found": 0, "failed_leagues": [],
        "archive_failed_events": [], "props_failed_events": {}, "publish_failures": [],
    }

    def record_prices(league, game, observed_at):
        try:
            summary["closing_prices_written"] += archive.store_event(league, game, observed_at)
        except Exception as error:
            logger.warning("Closing-price write failed for %s (%s)", game["event_id"], type(error).__name__)
            summary["archive_failed_events"].append(game["event_id"])

    for league, sport_key in LEAGUE_SPORT_KEYS.items():
        try:
            raw = api.get_odds(sport_key, markets="h2h,spreads,totals")
            observed_at = utc_now()
            games = api.parse_all_markets_odds(raw)
            summary["events_fetched"] += len(games)
            # Archive game lines as soon as observed, before props can cross the
            # start-time boundary. Prop quotes use their own response timestamps.
            for game in games.values():
                record_prices(league, game, observed_at)
            failures = []
            fetch_and_attach_player_props(
                api, sport_key, games, failed_events=failures,
                on_event=lambda game, captured_at: record_prices(league, game, captured_at), clock=utc_now,
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
    summary["archive_failed_events"] = sorted(set(summary["archive_failed_events"]))
    if any(summary[key] for key in ("failed_leagues", "archive_failed_events", "props_failed_events", "publish_failures")):
        summary["status"] = "partial"
    return summary
