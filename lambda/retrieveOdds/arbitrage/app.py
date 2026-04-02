import json
import boto3
from collections import defaultdict

s3 = boto3.client("s3")

BUCKET = "retrieve-odds-stack-oddscachebucket-1wl5a0lcdm9v"
# SPORTS = ["NBA","NFL","NHL","MLB","NCAAB"]
SPORTS = ["NBA","MLB"]

def decimal_to_implied_prob(odds):
    return 1 / odds


def find_arbitrage(bets):

    games = defaultdict(list)

    for bet in bets:
        key = f"{bet['match']}|{bet['market']}"
        games[key].append(bet)

    arbitrage_opportunities = []

    for key, game_bets in games.items():

        sides = {}

        for bet in game_bets:
            sides[bet["bet"]] = bet

        if len(sides) != 2:
            continue

        side1, side2 = list(sides.values())

        best_side1 = side1["odds"]
        best_side2 = side2["odds"]

        best_book1 = side1["book"]
        best_book2 = side2["book"]

        for book in side1.get("other_books", []):
            if book["odds"] > best_side1:
                best_side1 = book["odds"]
                best_book1 = book["book"]

        for book in side2.get("other_books", []):
            if book["odds"] > best_side2:
                best_side2 = book["odds"]
                best_book2 = book["book"]

        arb_check = decimal_to_implied_prob(best_side1) + decimal_to_implied_prob(best_side2)

        if arb_check < 1:

            arbitrage_opportunities.append({
                "match": side1["match"],
                "market": side1["market"],
                "side1": side1["bet"],
                "side2": side2["bet"],
                "book1": best_book1,
                "book2": best_book2,
                "odds1": best_side1,
                "odds2": best_side2,
                "arb_margin": round((1 - arb_check) * 100, 3),
                "time": side1["time"]
            })

    return arbitrage_opportunities


def lambda_handler(event, context):

    for sport in SPORTS:

        key = f"ev/{sport}/moneyline_ev.json"

        try:
            obj = s3.get_object(Bucket=BUCKET, Key=key)
            data = json.loads(obj["Body"].read())

            arbs = find_arbitrage(data)

            save_key = f"arbitrage/{sport}/moneyline_arb.json"

            s3.put_object(
                Bucket=BUCKET,
                Key=save_key,
                Body=json.dumps(arbs),
                ContentType="application/json"
            )

            print(f"{sport}: {len(arbs)} arbitrage opportunities saved")

        except Exception as e:
            print(f"Error processing {sport}", e)

    return {"status": "done"}