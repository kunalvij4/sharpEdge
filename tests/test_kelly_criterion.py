import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.kelly_criterion import (
    kelly_fraction,
    recommend_stake,
    batch_recommend,
    MAX_BET_PERCENT,
)


def test_kelly_fraction_basic():
    # Fair coin at +100 (2.0 decimal) = 0% edge, kelly = 0
    assert kelly_fraction(0.5, 2.0) == 0.0

    # 55% edge at +100 (2.0 decimal) = kelly 10%
    kf = kelly_fraction(0.55, 2.0)
    assert abs(kf - 0.10) < 0.001

    # 60% win prob at -150 (1.667 decimal)
    kf = kelly_fraction(0.60, 1.667)
    assert kf > 0


def test_kelly_fraction_no_edge():
    assert kelly_fraction(0.40, 2.0) == 0.0


def test_kelly_fraction_invalid_odds():
    assert kelly_fraction(0.5, 1.0) == 0.0
    assert kelly_fraction(0.5, 0.5) == 0.0


def test_recommend_stake_quarter_kelly():
    rec = recommend_stake(prob=0.55, decimal_odds=2.0, bankroll=1000.0)
    # Full kelly = 10%, quarter kelly = 2.5%
    assert abs(rec.full_kelly - 0.10) < 0.001
    assert abs(rec.fractional_kelly - 0.025) < 0.001
    assert abs(rec.recommended_stake - 25.0) < 0.01
    assert rec.capped is False


def test_recommend_stake_capped():
    # High edge scenario where quarter kelly exceeds 5% cap
    rec = recommend_stake(prob=0.75, decimal_odds=2.5, bankroll=1000.0)
    # Full kelly = (1.5*0.75 - 0.25) / 1.5 = 0.583
    # Quarter kelly = 0.146 > 5% cap
    assert rec.capped is True
    assert rec.stake_percent <= MAX_BET_PERCENT
    assert rec.recommended_stake == round(MAX_BET_PERCENT * 1000, 2)


def test_batch_recommend_respects_exposure_limit():
    bets = [
        {"fair_prob": 0.60, "odds": 2.0},
        {"fair_prob": 0.60, "odds": 2.0},
        {"fair_prob": 0.60, "odds": 2.0},
        {"fair_prob": 0.60, "odds": 2.0},
        {"fair_prob": 0.60, "odds": 2.0},
    ]
    recs = batch_recommend(bets, bankroll=1000.0, max_total_exposure=0.10)
    total = sum(r.stake_percent for r in recs)
    assert total <= 0.10 + 0.0001


def test_batch_recommend_normal_case():
    bets = [
        {"fair_prob": 0.55, "odds": 2.0},
        {"fair_prob": 0.53, "odds": 2.1},
    ]
    recs = batch_recommend(bets, bankroll=1000.0)
    assert len(recs) == 2
    assert all(r.recommended_stake > 0 for r in recs)


if __name__ == "__main__":
    test_kelly_fraction_basic()
    test_kelly_fraction_no_edge()
    test_kelly_fraction_invalid_odds()
    test_recommend_stake_quarter_kelly()
    test_recommend_stake_capped()
    test_batch_recommend_respects_exposure_limit()
    test_batch_recommend_normal_case()
    print("All Kelly Criterion tests passed!")
