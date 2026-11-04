import pytest

from odds_pipeline.models.player_props_model import COLLEGE_PROP_WEIGHTS, PlayerPropsModel


def prop(over, under, line=20.5):
    return {"over_odds": over, "under_odds": under, "line": line}


def college():
    return PlayerPropsModel.for_league("NCAAB", min_books=2)


def test_college_weights_sum_to_one_and_rank():
    assert sum(COLLEGE_PROP_WEIGHTS.values()) == pytest.approx(1.0)
    w = COLLEGE_PROP_WEIGHTS
    assert w["NoVig"] > w["Kalshi"] > w["ProphetX"] > w["FanDuel"] > w["DraftKings"]


def test_full_weights_when_all_books_present():
    data = {book: prop(1.9, 1.9) for book in COLLEGE_PROP_WEIGHTS}
    weights = college()._get_dynamic_weights(list(data))
    assert weights == pytest.approx(COLLEGE_PROP_WEIGHTS)


def test_other_and_fantasy_books_get_zero_weight():
    weights = college()._get_dynamic_weights(["NoVig", "Kalshi", "Caesars", "Underdog"])
    assert set(weights) == {"NoVig", "Kalshi"}
    assert weights["NoVig"] == pytest.approx(0.35 / 0.575)


def test_requires_an_anchor_exchange():
    data = {"FanDuel": prop(1.9, 1.9), "DraftKings": prop(1.9, 1.9)}
    with pytest.raises(ValueError):
        college().analyze_over_under_prop(data, "Player", "points")


def test_retail_book_does_not_count_toward_minimum():
    data = {"NoVig": prop(1.9, 1.9), "Caesars": prop(1.8, 2.0)}
    with pytest.raises(ValueError):
        college().analyze_over_under_prop(data, "Player", "points")


def test_retail_book_does_not_move_fair_value():
    base = {"NoVig": prop(1.9, 1.9), "Kalshi": prop(1.9, 1.9)}
    with_retail = {**base, "Caesars": prop(1.5, 2.8)}
    a = college().analyze_over_under_prop(base, "Player", "points")
    b = college().analyze_over_under_prop(with_retail, "Player", "points")
    assert a["fair_over_prob"] == pytest.approx(b["fair_over_prob"])


def test_pro_leagues_keep_original_weights():
    model = PlayerPropsModel.for_league("NBA", min_books=2)
    assert model.prop_weights["FanDuel"] == 0.35
    assert model.min_tier_books == 2
