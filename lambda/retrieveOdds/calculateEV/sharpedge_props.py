import json
import gzip
import boto3
from datetime import datetime

from player_props_model import PlayerPropsModel

s3 = boto3.client("s3")

BUCKET = "retrieve-odds-stack-oddscachebucket-1wl5a0lcdm9v"


def kelly_fraction(prob, odds):
    b = odds - 1
    if b <= 0:
        return 0
    q = 1 - prob
    return max((b * prob - q) / b, 0)


def load_props(sport):
    key = f"cache/{sport}/props.json.gz"

    obj = s3.get_object(Bucket=BUCKET, Key=key)

    with gzip.GzipFile(fileobj=obj["Body"]) as gz:
        return json.load(gz)


def process_props_sport(sport):

    print(f"Processing PROPS for {sport}")

    data = load_props(sport)
    model = PlayerPropsModel(min_books=2)

    ev_bets = []
    bet_id = 0

    for game_id, game in data["games"].items():

        try:
            props = game["data"]

            for stat, players in props.items():

                prop_type = stat.replace("player_", "")

                for player, lines in players.items():

                    for line_str, books in lines.items():

                        try:
                            line = float(line_str)

                            # 🔥 ONLY KEEP VALID BOOKS
                            prop_data = {}

                            for book, odds in books.items():
                                if (
                                    "over_odds" in odds
                                    and "under_odds" in odds
                                    and odds["over_odds"] > 1.01
                                    and odds["under_odds"] > 1.01
                                ):
                                    prop_data[book] = {
                                        "over_odds": odds["over_odds"],
                                        "under_odds": odds["under_odds"],
                                        "line": line
                                    }

                            # 🔥 REQUIRE MULTIPLE BOOKS ON SAME LINE
                            if len(prop_data) < 2:
                                continue

                            # 🔥 RUN MODEL
                            analysis = model.analyze_over_under_prop(
                                prop_data,
                                player,
                                prop_type
                            )

                            opportunities = model.find_prop_ev_opportunities(
                                analysis,
                                prop_data,
                                min_ev=0.5
                            )

                            for opp in opportunities:

                                ev_bets.append({
                                    "id": bet_id,
                                    "sport": sport,
                                    "match": f"{game['away_team']} vs {game['home_team']}",
                                    "market": stat,
                                    "player": player,
                                    "bet_type": opp["bet_type"],
                                    "line": line,
                                    "book": opp["book_name"],
                                    "odds": opp["offered_odds"],
                                    "ev": opp["ev_percentage"],
                                    "kelly": kelly_fraction(
                                        opp["fair_prob"],
                                        opp["offered_odds"]
                                    ),
                                    "time": game["commence_time"],
                                    "book_tier": opp["book_tier"]
                                })

                                bet_id += 1

                        except Exception:
                            continue

        except Exception as e:
            print(f"Skipping props for {game_id}: {str(e)}")
            continue

    ev_bets.sort(key=lambda x: x["ev"], reverse=True)

    print(f"{sport}: Found {len(ev_bets)} +EV PROP bets")

    dest_key = f"ev/{sport}/props_ev.json"

    s3.put_object(
        Bucket=BUCKET,
        Key=dest_key,
        Body=json.dumps(ev_bets).encode(),
        ContentType="application/json"
    )

    return len(ev_bets)