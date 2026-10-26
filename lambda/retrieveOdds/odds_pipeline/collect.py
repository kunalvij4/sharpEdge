"""Fetch league-specific props and attach them to the current in-memory odds."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import logging
import math
import time

import requests

from .leagues import PROP_MARKETS_BY_SPORT


logger = logging.getLogger(__name__)


def utc_now():
    return datetime.now(timezone.utc)


def fetch_and_attach_player_props(api, sport_key, games, failed_events=None, on_event=None, clock=None):
    markets = PROP_MARKETS_BY_SPORT[sport_key]
    failed_events = failed_events if failed_events is not None else []
    clock = clock or utc_now

    def fetch_single_event(game):
        event_id = game.get("event_id")
        if not event_id:
            raise ValueError("Missing provider event ID")
        for attempt in range(3):
            try:
                event_odds = api.get_event_odds(sport_key, event_id, markets=",".join(markets))
                observed_at = clock()
                break
            except requests.RequestException as error:
                response = error.response
                status = response.status_code if response is not None else None
                transient = isinstance(error, (requests.Timeout, requests.ConnectionError)) or status in {
                    429, 500, 502, 503, 504,
                }
                if not transient or attempt == 2:
                    raise
                delay = 2 ** attempt
                if response is not None:
                    try:
                        delay = max(delay, min(float(response.headers.get("Retry-After", delay)), 30))
                    except (TypeError, ValueError):
                        pass
                time.sleep(delay)
        if not isinstance(event_odds, dict) or not isinstance(event_odds.get("bookmakers"), list):
            raise ValueError("Invalid player-props response")

        structured = {}
        for bookmaker in event_odds["bookmakers"]:
            book_name = bookmaker.get("title")
            if not book_name:
                continue
            for market in bookmaker.get("markets", []):
                stat = market.get("key")
                if stat not in markets:
                    continue
                for outcome in market.get("outcomes", []):
                    player = outcome.get("description")
                    side = outcome.get("name", "").lower()
                    if not player or side not in {"over", "under"}:
                        continue
                    try:
                        line, price = float(outcome["point"]), float(outcome["price"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if not math.isfinite(line) or not math.isfinite(price) or price <= 1:
                        continue
                    books = structured.setdefault(stat, {}).setdefault(player, {}).setdefault(format(line, ".15g"), {})
                    books.setdefault(book_name, {})[f"{side}_odds"] = price
        return structured, observed_at

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_single_event, game): game_id for game_id, game in games.items()}
        for future in as_completed(futures):
            game_id = futures[future]
            try:
                props, observed_at = future.result()
            except Exception as error:
                failed_events.append(games[game_id].get("event_id") or game_id)
                logger.warning("Props fetch failed for %s/%s (%s)", sport_key, game_id, type(error).__name__)
                continue
            games[game_id].setdefault("markets", {})["props"] = props
            if on_event is not None:
                on_event({**games[game_id], "markets": {"props": props}}, observed_at)
    return games
