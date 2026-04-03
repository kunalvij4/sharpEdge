import json
import gzip
import boto3
from datetime import datetime

from sharpedge_model import SharpEdge
from nfl_weights import NFLWeightingEngine

# ✅ NEW IMPORT (your props file)
from sharpedge_props import process_props_sport

s3 = boto3.client("s3")

BUCKET = "retrieve-odds-stack-oddscachebucket-1wl5a0lcdm9v"

# SPORTS = ["NBA", "NFL", "NHL", "MLB"]
SPORTS = ["NBA", "MLB"]


def kelly_fraction(prob, odds):
    b = odds - 1
    if b <= 0:
        return 0
    q = 1 - prob
    return max((b * prob - q) / b, 0)


def load_odds(sport):
    key = f"cache/{sport}/moneyline.json.gz"

    obj = s3.get_object(Bucket=BUCKET, Key=key)

    with gzip.GzipFile(fileobj=obj["Body"]) as gz:
        return json.load(gz)


def process_sport(sport):

    print(f"Processing {sport}")

    data = load_odds(sport)

    weighting = NFLWeightingEngine()  # TODO: swap per sport later

    ev_bets = []
    bet_id = 0

    for game_id, game in data["games"].items():

        try:

            odds_data = {}
            available_books = list(game["data"]["odds_data"].keys())

            # Build format for SharpEdge
            for book, odds in game["data"]["odds_data"].items():
                odds_data[book] = (odds["home_odds"], odds["away_odds"])

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
                        "sport": sport,
                        "match": f"{away} vs {home}",
                        "market": "moneyline",
                        "bet": home,
                        "opposite_bet": away,
                        "wager_display": f"{home} ML",
                        "opposite_wager_display": f"{away} ML",
                        "book": book,
                        "odds": home_odds,
                        "away_odds": away_odds,
                        "ev": home_ev,
                        "kelly": kelly_fraction(fair_prob, home_odds),
                        "time": game["commence_time"],
                        "other_books": other_books_home,
                        "away_other_books": other_books_away
                    })
                    bet_id += 1

                if away_ev > 0:
                    ev_bets.append({
                        "id": bet_id,
                        "sport": sport,
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

    ev_bets.sort(key=lambda x: x["ev"], reverse=True)

    print(f"{sport}: Found {len(ev_bets)} +EV bets")

    # Save per sport
    dest_key = f"ev/{sport}/moneyline_ev.json"

    s3.put_object(
        Bucket=BUCKET,
        Key=dest_key,
        Body=json.dumps(ev_bets).encode(),
        ContentType="application/json"
    )

    return len(ev_bets)


def lambda_handler(event, context):

    total_bets = 0
    total_props = 0

    for sport in SPORTS:
        try:
            # ✅ EXISTING MONEYLINE (UNCHANGED)
            count = process_sport(sport)
            total_bets += count

            # ✅ NEW PROPS PIPELINE
            props_count = process_props_sport(sport)
            total_props += props_count

        except Exception as e:
            print(f"Failed {sport}: {str(e)}")

    return {
        "status": "complete",
        "moneyline_bets_found": total_bets,
        "props_bets_found": total_props,
        "total_bets_found": total_bets + total_props
    }