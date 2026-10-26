import os
import json
from datetime import datetime, time, timezone
from player_props import fetch_and_attach_player_props

from odds_api import OddsAPI
from dynamo_client import DynamoDBClient


ODDS_API_KEY = os.environ["ODDS_API_KEY"]          # required
ODDS_API_BASE_URL = os.environ["ODDS_API_BASE_URL"]  # required; custom in-house API origin
TABLE_NAME = os.environ["TABLE_NAME"]              # required
def lambda_handler(event, context):
    retrieved_at = datetime.now(timezone.utc).isoformat()

    odds = OddsAPI(api_key=ODDS_API_KEY, base_url=ODDS_API_BASE_URL)
    db = DynamoDBClient(table_name=TABLE_NAME)

    total_items = 0

    def write_games(games_dict: dict, league: str):
        nonlocal total_items
        for game_id, payload in games_dict.items():
            item = {
                "game_id": game_id,              # PK
                "retrieved_at": retrieved_at,    # SK
                "league": league,
                **payload,                       # sport/home/away/commence_time/markets...
            }
            db.store_item(item)
            total_items += 1

    game_counts = {}
    for league, sport_key in OddsAPI.league_keys.items():
        games = odds.get_games_with_props_events(sport_key)
        games = fetch_and_attach_player_props(odds, games)
        write_games(games, league)
        game_counts[f"{league.lower()}_games"] = len(games)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "ok": True,
                "retrieved_at": retrieved_at,
                "items_written": total_items,
                **game_counts,
            }
        ),
    }
