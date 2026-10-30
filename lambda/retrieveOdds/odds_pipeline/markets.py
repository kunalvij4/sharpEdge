"""Normalize bookmaker quotes without conflating events, players, or lines."""

import hashlib
import json
import math


CATEGORIES = ("moneyline", "spreads", "totals", "props")


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return (result or 0.0) if math.isfinite(result) else None


def bet_key(quote):
    line = number(quote["line"]) if quote["line"] is not None else None
    identity = [quote["event_id"], quote["market"], quote["player"], line, quote["book"], quote["side"]]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def iter_quotes(league, game):
    event_id = game.get("event_id")
    if not event_id:
        raise ValueError("Provider event_id is required")
    common = {
        "event_id": event_id,
        "league": league,
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "commence_time": game["commence_time"],
    }

    def make(category, market, book, side, selection, price, line=None, player=None, liquidity=None):
        odds = number(price)
        if not book or odds is None or odds <= 1:
            return None
        return {
            **common, "category": category, "market": market, "book": book,
            "side": side, "selection": selection, "odds": odds,
            "line": line, "player": player, "liquidity": number(liquidity),
        }

    for category, data in game.get("markets", {}).items():
        if category in ("moneyline", "spreads", "totals"):
            for book, prices in data.get("odds_data", {}).items():
                if category == "totals":
                    sides = []
                    for side in ("over", "under"):
                        line = number(prices.get(f"{side}_point", prices.get("point")))
                        if line is not None:
                            sides.append((side, side.title(), f"{side}_odds", line))
                else:
                    sides = []
                    for side in ("home", "away"):
                        line = number(prices.get(f"{side}_point")) if category == "spreads" else None
                        if category == "spreads" and line is None:
                            continue
                        sides.append((side, game[f"{side}_team"], f"{side}_odds", line))
                for side, selection, price_key, line in sides:
                    quote = make(category, category, book, side, selection, prices.get(price_key), line,
                                 liquidity=prices.get(price_key.replace("_odds", "_liquidity")))
                    if quote is not None:
                        yield quote
        elif category == "props":
            for market, players in data.items():
                for player, lines in players.items():
                    for line_text, books in lines.items():
                        line = number(line_text)
                        if line is None or not player:
                            continue
                        for book, prices in books.items():
                            for side in ("over", "under"):
                                quote = make("props", market, book, side, side.title(), prices.get(f"{side}_odds"), line, player,
                                             liquidity=prices.get(f"{side}_liquidity"))
                                if quote is not None:
                                    yield quote


def group_key(quote):
    # Home -3.5 and away +3.5 are complements. Home -4.5 is a different bet.
    line = quote["line"]
    if quote["category"] == "spreads" and quote["side"] == "away":
        line = -line
    return quote["event_id"], quote["category"], quote["market"], quote["player"], line
