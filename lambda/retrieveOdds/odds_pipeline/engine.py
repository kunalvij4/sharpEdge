"""Calculate EV and arbitrage from the same freshly collected prices."""

from collections import defaultdict
import hashlib
import json

from .models.nfl_weights import NFLWeightingEngine
from .models.player_props_model import PlayerPropsModel
from .models.sharpedge_model import SharpEdge

from .markets import CATEGORIES, bet_key, group_key, iter_quotes


def kelly(probability, odds):
    return max((odds * probability - 1) / (odds - 1), 0)


def display(quote):
    if quote["category"] == "moneyline":
        return f"{quote['selection']} ML"
    if quote["category"] == "spreads":
        return f"{quote['selection']} {quote['line']:+g}"
    prefix = f"{quote['player']} " if quote["player"] else ""
    return f"{prefix}{quote['selection']} {quote['line']:g}"


def _fair_probability(category, quotes, sides):
    by_book = defaultdict(dict)
    for quote in quotes:
        by_book[quote["book"]][quote["side"]] = quote
    pairs = {
        book: (prices[sides[0]]["odds"], prices[sides[1]]["odds"])
        for book, prices in by_book.items() if all(side in prices for side in sides)
    }
    if category == "props":
        model = PlayerPropsModel(min_books=2)
        data = {
            book: {"over_odds": odds[0], "under_odds": odds[1], "line": quotes[0]["line"]}
            for book, odds in pairs.items() if min(odds) > 1.01
        }
        analysis = model.analyze_over_under_prop(data, quotes[0]["player"], quotes[0]["market"].removeprefix("player_"))
        return analysis["fair_over_prob"], model
    weights = NFLWeightingEngine().get_nfl_weights(category, list(pairs))
    model = SharpEdge(weights, exchange_weights={})
    return model.get_fair_odds_and_ev(pairs)["fair_prob"], model


def _base(quote):
    return {
        "event_id": quote["event_id"], "sport": quote["league"],
        "match": f"{quote['away_team']} vs {quote['home_team']}",
        "market": quote["market"], "time": quote["commence_time"],
    }


def calculate(league, games):
    ev = {category: [] for category in CATEGORIES}
    arbitrage = {category: [] for category in CATEGORIES}
    groups = defaultdict(list)
    for game in games.values():
        for quote in iter_quotes(league, game):
            groups[group_key(quote)].append(quote)

    for identity, quotes in groups.items():
        category = quotes[0]["category"]
        sides = ("home", "away") if category in ("moneyline", "spreads") else ("over", "under")
        by_side = {side: [quote for quote in quotes if quote["side"] == side] for side in sides}
        if not all(by_side.values()):
            continue

        # Arbitrage is calculated from raw quotes, independently of EV filters.
        best = [max(by_side[side], key=lambda quote: quote["odds"]) for side in sides]
        inverse_total = sum(1 / quote["odds"] for quote in best)
        if inverse_total < 1:
            first, second = best
            arbitrage[category].append({
                **_base(first),
                "id": hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest(),
                "side1": first["selection"], "side2": second["selection"],
                "book1": first["book"], "book2": second["book"],
                "odds1": first["odds"], "odds2": second["odds"],
                "line1": first["line"], "line2": second["line"],
                "player": first["player"], "line": identity[-1],
                "arb_margin": round((1 - inverse_total) * 100, 3),
            })

        try:
            fair_first, model = _fair_probability(category, quotes, sides)
        except (ValueError, ArithmeticError):
            # A market can have an arb without enough qualifying books for EV.
            continue

        for index, side in enumerate(sides):
            probability = fair_first if index == 0 else 1 - fair_first
            opposite = sides[1 - index]
            for quote in by_side[side]:
                value = model.calculate_ev(quote["odds"], probability)
                if value <= 0 or (category == "props" and value < 0.5):
                    continue
                opposite_quote = by_side[opposite][0]
                others = [
                    {"book": other["book"], "odds": other["odds"]}
                    for other in by_side[side] if other["book"] != quote["book"]
                ]
                opposite_books = [
                    {"book": other["book"], "odds": other["odds"]}
                    for other in by_side[opposite] if other["book"] != quote["book"]
                ]
                result = {
                    **_base(quote), "id": bet_key(quote), "book": quote["book"],
                    "bet": quote["selection"], "opposite_bet": opposite_quote["selection"],
                    "wager_display": display(quote), "opposite_wager_display": display(opposite_quote),
                    "line": quote["line"], "odds": quote["odds"], "ev": value,
                    "kelly": kelly(probability, quote["odds"]), "fair_prob": probability,
                    "other_books": others,
                }
                if category == "moneyline" and side == "home":
                    same_book_away = next((other for other in by_side[opposite] if other["book"] == quote["book"]), opposite_quote)
                    result.update(away_odds=same_book_away["odds"], away_other_books=opposite_books)
                if category == "props":
                    weight = model._get_dynamic_weights([other["book"] for other in quotes]).get(quote["book"], 0)
                    result.update(
                        player=quote["player"], bet_type=side.upper(),
                        book_tier="Sharp" if weight >= 0.15 else "Recreational" if weight > 0 else "Unweighted",
                        over_other_books=[{"book": other["book"], "odds": other["odds"]} for other in by_side["over"]],
                        under_other_books=[{"book": other["book"], "odds": other["odds"]} for other in by_side["under"]],
                    )
                ev[category].append(result)

    for rows in ev.values():
        rows.sort(key=lambda row: row["ev"], reverse=True)
    for rows in arbitrage.values():
        rows.sort(key=lambda row: row["arb_margin"], reverse=True)
    return ev, arbitrage
