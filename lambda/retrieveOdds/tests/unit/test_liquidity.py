import pytest

from odds_pipeline.models.liquidity import apply_liquidity_boost, liquidity_multiplier
from odds_pipeline.models.player_props_model import PlayerPropsModel
from odds_pipeline.models.sharpedge_model import SharpEdge


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv("LIQUIDITY_REWEIGHTING", "true")


def test_disabled_by_default_keeps_base_weights(monkeypatch):
    monkeypatch.delenv("LIQUIDITY_REWEIGHTING")
    weights = {"NoVig": 0.1, "FanDuel": 0.3}
    assert apply_liquidity_boost(weights, {"NoVig": (3000, 3000)}) == weights
    assert apply_liquidity_boost(weights, {"NoVig": (30, 30)}) == weights


@pytest.mark.parametrize("sides,expected", [
    ((100, 100), 1.0),
    ((99, 5000), 0.0),
    ((30, 30), 0.0),
    ((500, 5000), 1.5),
    ((2000, 2000), 2.0),
    ((10000, 400), 1.0),
    ((10000, None), 1.0),
    (None, 1.0),
    ((float("nan"), 5000), 1.0),
    ((-5, 5000), 1.0),
])
def test_liquidity_multiplier_tiers(sides, expected):
    assert liquidity_multiplier(sides) == expected


def test_boost_only_applies_to_exchanges():
    weights = {"NoVig": 0.1, "FanDuel": 0.3}
    boosted = apply_liquidity_boost(weights, {"NoVig": (3000, 3000), "FanDuel": (3000, 3000)})
    assert boosted == {"NoVig": 0.2, "FanDuel": 0.3}


def test_no_liquidity_keeps_base_weights():
    weights = {"NoVig": 0.1, "FanDuel": 0.3}
    assert apply_liquidity_boost(weights, None) == weights
    assert apply_liquidity_boost(weights, {}) == weights


def test_props_deep_exchange_pulls_fair_probability_toward_it():
    data = {
        "FanDuel": {"over_odds": 1.8, "under_odds": 2.0, "line": 20.5},
        "DraftKings": {"over_odds": 1.8, "under_odds": 2.0, "line": 20.5},
        "NoVig": {"over_odds": 2.2, "under_odds": 1.7, "line": 20.5},
    }
    model = PlayerPropsModel(min_books=2)
    base = model.analyze_over_under_prop(data, "P", "points")["fair_over_prob"]
    deep = model.analyze_over_under_prop(data, "P", "points", liquidity={"NoVig": (5000, 5000)})["fair_over_prob"]
    thin = model.analyze_over_under_prop(data, "P", "points", liquidity={"NoVig": (150, 5000)})["fair_over_prob"]
    dropped = model.analyze_over_under_prop(data, "P", "points", liquidity={"NoVig": (30, 5000)})
    assert dropped["fair_over_prob"] == pytest.approx(
        (1 / 1.8) / (1 / 1.8 + 1 / 2.0))
    assert dropped["books_used"] == 2
    novig_prob = (1 / 2.2) / (1 / 2.2 + 1 / 1.7)
    fanduel_prob = (1 / 1.8) / (1 / 1.8 + 1 / 2.0)
    assert thin == pytest.approx(base)
    assert abs(deep - novig_prob) < abs(base - novig_prob)
    assert min(novig_prob, fanduel_prob) < deep < max(novig_prob, fanduel_prob)


def test_sharpedge_boost_changes_weight_and_reports_multiplier():
    model = SharpEdge({"Pinnacle": 0.5, "NoVig": 0.1}, exchange_weights={})
    odds = {"Pinnacle": (1.8, 2.0), "NoVig": (2.2, 1.7)}
    base = model.get_fair_odds_and_ev(odds)
    deep = model.get_fair_odds_and_ev(odds, liquidity={"NoVig": (2500, 3000)})
    assert deep["book_contributions"]["NoVig"]["liquidity_multiplier"] == pytest.approx(2.0)
    assert deep["book_contributions"]["Pinnacle"]["liquidity_multiplier"] == pytest.approx(1.0)
    assert deep["fair_prob"] < base["fair_prob"]  # NoVig prices this side lower than Pinnacle
