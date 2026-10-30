from odds_pipeline.engine import calculate
from odds_pipeline.models.nfl_weights import NFLWeightingEngine


def test_no_weights_when_too_few_weighted_books():
    engine = NFLWeightingEngine()
    assert engine.get_nfl_weights("moneyline", ["Kalshi", "Polymarket", "Novig"]) == {}
    assert engine.get_nfl_weights("moneyline", ["Pinnacle", "Circa"]) == {}
    assert engine.get_nfl_weights("spreads", ["Kalshi"]) == {}


def test_weights_still_returned_when_enough_books():
    weights = NFLWeightingEngine().get_nfl_weights("moneyline", ["Pinnacle", "Circa", "BetOnline"])
    assert set(weights) == {"Pinnacle", "Circa", "BetOnline"}
    assert abs(sum(weights.values()) - 1) < 1e-9


def test_engine_offers_no_ev_without_weighted_books_but_keeps_arbitrage():
    game = {
        "event_id": "e1", "home_team": "A", "away_team": "B", "commence_time": "2026-10-30T00:00:00Z",
        "markets": {"moneyline": {"odds_data": {
            "Kalshi": {"home_odds": 2.5, "away_odds": 1.5},
            "Polymarket": {"home_odds": 1.5, "away_odds": 2.5},
        }}},
    }
    ev, arbitrage = calculate("NBA", {"e1": game})
    assert ev["moneyline"] == []
    assert len(arbitrage["moneyline"]) == 1
