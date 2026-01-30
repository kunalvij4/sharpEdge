import os
import json
from datetime import datetime, timezone

from odds_api import OddsAPI
from dynamo_client import DynamoDBClient


ODDS_API_KEY = os.environ["ODDS_API_KEY"]          # required
TABLE_NAME = os.environ["TABLE_NAME"]              # required


def lambda_handler(event, context):
    retrieved_at = datetime.now(timezone.utc).isoformat()

    odds = OddsAPI(api_key=ODDS_API_KEY)
    db = DynamoDBClient(table_name=TABLE_NAME)

    # Pull both leagues (all moneyline spreads totals)
    nfl = odds.get_nfl_all_markets()
    nba = odds.get_nba_all_markets()

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

    write_games(nfl, "NFL")
    write_games(nba, "NBA")

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "ok": True,
                "retrieved_at": retrieved_at,
                "items_written": total_items,
                "nfl_games": len(nfl),
                "nba_games": len(nba),
            }
        ),
    }
