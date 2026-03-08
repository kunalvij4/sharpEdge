import json
import gzip
import boto3
from datetime import datetime

from sharpedge_model import SharpEdge
from nfl_weights import NFLWeightingEngine

s3 = boto3.client("s3")

SOURCE_BUCKET = "retrieve-odds-stack-oddscachebucket-1wl5a0lcdm9v"
SOURCE_KEY = "cache/NBA/moneyline.json.gz"

DEST_BUCKET = "ev-output-bucket"
DEST_KEY = "ev/NBA/moneyline_ev.json"


def kelly_fraction(prob, odds):
    b = odds - 1
    if b <= 0:
        return 0
    q = 1 - prob
    return max((b * prob - q) / b, 0)


def load_odds():
    obj = s3.get_object(Bucket=SOURCE_BUCKET, Key=SOURCE_KEY)

    with gzip.GzipFile(fileobj=obj["Body"]) as gz:
        return json.load(gz)


def lambda_handler(event, context):

    print("Loading odds from S3")

    data = load_odds()

    weighting = NFLWeightingEngine()

    ev_bets = []
    bet_id = 0

    for game_id, game in data["games"].items():

        try:

            odds_data = {}
            available_books = list(game["data"]["odds_data"].keys())

            # Build odds tuple format required by SharpEdge
            for book, odds in game["data"]["odds_data"].items():
                odds_data[book] = (odds["home_odds"], odds["away_odds"])

            # Get dynamic weights based on available books
            weights = weighting.get_nfl_weights("moneyline", available_books)

            model = SharpEdge(weights, exchange_weights={})

            result = model.get_fair_odds_and_ev(odds_data)

            fair_prob = result["fair_prob"]

            home = game["home_team"]
            away = game["away_team"]

            for book, odds in game["data"]["odds_data"].items():

                home_odds = odds["home_odds"]
                away_odds = odds["away_odds"]

                home_ev = model.calculate_ev(home_odds, fair_prob)
                away_ev = model.calculate_ev(away_odds, 1 - fair_prob)

                # Build comparison odds for frontend
                other_books_home = []
                other_books_away = []

                for other_book, other_odds in game["data"]["odds_data"].items():
                    if other_book != book:

                        other_books_home.append({
                            "book": other_book,
                            "odds": other_odds["home_odds"]
                        })

                        other_books_away.append({
                            "book": other_book,
                            "odds": other_odds["away_odds"]
                        })

                if home_ev > 0:
                    ev_bets.append({
                        "id": bet_id,
                        "sport": game["sport"],
                        "match": f"{away} vs {home}",
                        "market": "moneyline",
                        "bet": home,
                        "opposite_bet": away,
                        "wager_display": f"{home} ML",
                        "opposite_wager_display": f"{away} ML",
                        "book": book,
                        "odds": home_odds,
                        "ev": home_ev,
                        "kelly": kelly_fraction(fair_prob, home_odds),
                        "time": game["commence_time"],
                        "other_books": other_books_home
                    })

                    bet_id += 1

                if away_ev > 0:
                    ev_bets.append({
                        "id": bet_id,
                        "sport": game["sport"],
                        "match": f"{away} vs {home}",
                        "market": "moneyline",
                        "bet": away,
                        "opposite_bet": home,
                        "wager_display": f"{away} ML",
                        "opposite_wager_display": f"{home} ML",
                        "book": book,
                        "odds": away_odds,
                        "ev": away_ev,
                        "kelly": kelly_fraction(1 - fair_prob, away_odds),
                        "time": game["commence_time"],
                        "other_books": other_books_away
                    })

                    bet_id += 1

        except Exception as e:
            print(f"Skipping game {game_id}: {str(e)}")
            continue

    # Sort by EV descending
    ev_bets.sort(key=lambda x: x["ev"], reverse=True)

    print(f"Found {len(ev_bets)} +EV bets")

    s3.put_object(
        Bucket=DEST_BUCKET,
        Key=DEST_KEY,
        Body=json.dumps(ev_bets).encode(),
        ContentType="application/json"
    )

    return {
        "status": "complete",
        "bets_found": len(ev_bets)
    }