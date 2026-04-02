import os
import json
from datetime import datetime, timezone
import gzip
import boto3
from concurrent.futures import ThreadPoolExecutor, as_completed

from odds_api import OddsAPI
from dynamo_client import DynamoDBClient


ODDS_API_KEY = os.environ["ODDS_API_KEY"]          # required
TABLE_NAME = os.environ["TABLE_NAME"]              # required
s3 = boto3.client("s3")

def _s3_put_json_gz(bucket: str, key: str, payload: dict) -> None:
    body = gzip.compress(json.dumps(payload).encode("utf-8"))
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        ContentEncoding="gzip",
    )

def fetch_and_attach_player_props(odds_api, sport_key: str, games: dict) -> dict:
    """
    Parallel fetch player props per event and structure as:
    stat -> player -> line -> books
    """

    PLAYER_PROP_MARKETS = os.environ.get(
        "PLAYER_PROPS_MARKETS",
        "player_points,player_rebounds,player_assists,player_threes"
    )

    MAX_WORKERS = int(os.environ.get("PROP_FETCH_THREADS", 8))

    def fetch_single_event(game_id, game):
        try:
            event_odds = odds_api.get_event_odds(
                sport_key=sport_key,
                event_id=game_id,
                markets=PLAYER_PROP_MARKETS
            )

            structured = {}

            for bookmaker in event_odds.get("bookmakers", []):
                book_name = bookmaker.get("title")

                for market in bookmaker.get("markets", []):
                    stat = market.get("key")  # e.g. player_points

                    for outcome in market.get("outcomes", []):
                        player = outcome.get("description") or outcome.get("name")
                        if not player:
                            continue

                        line = outcome.get("point")
                        price = outcome.get("price")
                        outcome_type = outcome.get("name", "").lower()

                        if line is None:
                            continue

                        # INIT TREE
                        structured.setdefault(stat, {})
                        structured[stat].setdefault(player, {})
                        structured[stat][player].setdefault(line, {})
                        structured[stat][player][line].setdefault(book_name, {})

                        # ASSIGN ODDS
                        if "over" in outcome_type:
                            structured[stat][player][line][book_name]["over_odds"] = price
                        elif "under" in outcome_type:
                            structured[stat][player][line][book_name]["under_odds"] = price
                        elif "yes" in outcome_type:
                            structured[stat][player][line][book_name]["yes_odds"] = price
                        elif "no" in outcome_type:
                            structured[stat][player][line][book_name]["no_odds"] = price

            return game_id, structured

        except Exception as e:
            print(f"[ERROR] Props fetch failed for {game_id}: {e}")
            return game_id, None

    # 🚀 THREADPOOL EXECUTION
    futures = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for game_id, game in games.items():
            futures.append(executor.submit(fetch_single_event, game_id, game))

        for future in as_completed(futures):
            game_id, structured_props = future.result()

            if structured_props:
                games[game_id].setdefault("markets", {})
                games[game_id]["markets"]["props"] = structured_props

    return games

def _extract_market(games: dict, market: str) -> dict:
    """
    games is your parsed dict keyed by game_id.
    market is like 'moneyline' / 'spreads' / 'totals' / 'props'.
    Returns a dict with only that market for each game (if present).
    """
    out = {}
    for game_id, g in games.items():
        markets = (g.get("markets") or {})
        if market in markets:
            out[game_id] = {
                "sport": g.get("sport"),
                "home_team": g.get("home_team"),
                "away_team": g.get("away_team"),
                "commence_time": g.get("commence_time"),
                "market": market,
                "data": markets[market],
            }
    return out


def write_s3_cache_for_league(league: str, retrieved_at: str, all_games: dict) -> None:
    """
    Writes:
      cache/<LEAGUE>/moneyline.json.gz
      cache/<LEAGUE>/props.json.gz
    """
    bucket = os.environ["CACHE_BUCKET"]
    prefix = os.environ.get("CACHE_PREFIX", "cache").rstrip("/")

    # Moneyline cache (moneyline market only)
    moneyline_only = _extract_market(all_games, "moneyline")

    # Props cache (placeholder until you add props markets)
    props_only = _extract_market(all_games, "props")  # will be {} for now

    _s3_put_json_gz(
        bucket=bucket,
        key=f"{prefix}/{league}/moneyline.json.gz",
        payload={"retrieved_at": retrieved_at, "league": league, "wager_type": "moneyline", "games": moneyline_only},
    )

    _s3_put_json_gz(
        bucket=bucket,
        key=f"{prefix}/{league}/props.json.gz",
        payload={"retrieved_at": retrieved_at, "league": league, "wager_type": "props", "games": props_only},
    )

def lambda_handler(event, context):
    retrieved_at = datetime.now(timezone.utc).isoformat()

    odds = OddsAPI(api_key=ODDS_API_KEY)
    db = DynamoDBClient(table_name=TABLE_NAME)

    # Pull both leagues (all moneyline spreads totals)
    # nfl = odds.get_nfl_all_markets()
    nba = odds.get_nba_all_markets()
    mlb = odds.get_mlb_all_markets()
    # nhl = odds.get_nhl_all_markets()

    nba = fetch_and_attach_player_props(odds, "basketball_nba", nba)
    # mlb = fetch_and_attach_player_props(odds, "baseball_mlb", mlb)

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

    # Write S3 latest caches (league -> wager type)
    # write_s3_cache_for_league("NFL", retrieved_at, nfl)
    write_s3_cache_for_league("NBA", retrieved_at, nba)
    write_s3_cache_for_league("MLB", retrieved_at, mlb)
    # write_s3_cache_for_league("NHL", retrieved_at, nhl)

    # write_games(nfl, "NFL")
    write_games(nba, "NBA")
    write_games(mlb, "MLB")
    # write_games(nhl, "NHL")

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "ok": True,
                "retrieved_at": retrieved_at,
                "items_written": total_items,
                # "nfl_games": len(nfl),
                "nba_games": len(nba),
                "mlb_games": len(mlb),
                # "nhl_games": len(nhl),
            }
        ),
    }
