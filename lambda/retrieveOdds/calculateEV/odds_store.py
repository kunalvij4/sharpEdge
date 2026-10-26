"""Fetch fresh odds directly from the in-house API for EV calculation."""

import os
from datetime import datetime, timezone

from retrieveOdds.dynamo_client import DynamoDBClient
from retrieveOdds.odds_api import OddsAPI
from retrieveOdds.player_props import fetch_and_attach_player_props


SPORT_KEYS = OddsAPI.league_keys


def load_sport(sport):
    retrieved_at = datetime.now(timezone.utc).isoformat()
    api = OddsAPI(
        api_key=os.environ["ODDS_API_KEY"],
        base_url=os.environ["ODDS_API_BASE_URL"],
    )
    games = api.get_games_with_props_events(SPORT_KEYS[sport])
    games = fetch_and_attach_player_props(api, games)
    db = DynamoDBClient(table_name=os.environ["TABLE_NAME"])
    for game_id, game in games.items():
        db.store_item({
            "game_id": game_id,
            "retrieved_at": retrieved_at,
            "league": sport,
            **game,
        })
    return games


def load_market(sport, market, games=None):
    if games is None:
        games = load_sport(sport)
    return {"games": {
        game_id: {
            "sport": game.get("sport"),
            "home_team": game.get("home_team"),
            "away_team": game.get("away_team"),
            "commence_time": game.get("commence_time"),
            "market": market,
            "data": game["markets"][market],
        }
        for game_id, game in games.items()
        if market in (game.get("markets") or {})
    }}
