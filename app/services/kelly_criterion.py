from dataclasses import dataclass


KELLY_FRACTION = 0.25
MAX_BET_PERCENT = 0.05
MIN_BET_PERCENT = 0.005


@dataclass
class KellyRecommendation:
    full_kelly: float
    fractional_kelly: float
    recommended_stake: float
    stake_percent: float
    capped: bool


def kelly_fraction(prob: float, decimal_odds: float) -> float:
    b = decimal_odds - 1
    if b <= 0:
        return 0.0
    q = 1 - prob
    return max((b * prob - q) / b, 0.0)


def recommend_stake(
    prob: float,
    decimal_odds: float,
    bankroll: float,
    fraction: float = KELLY_FRACTION,
    max_percent: float = MAX_BET_PERCENT,
) -> KellyRecommendation:
    full = kelly_fraction(prob, decimal_odds)
    fractional = full * fraction
    capped = fractional > max_percent
    stake_percent = min(fractional, max_percent)
    recommended_stake = round(stake_percent * bankroll, 2)

    return KellyRecommendation(
        full_kelly=round(full, 6),
        fractional_kelly=round(fractional, 6),
        recommended_stake=recommended_stake,
        stake_percent=round(stake_percent, 6),
        capped=capped,
    )


def batch_recommend(
    bets: list,
    bankroll: float,
    fraction: float = KELLY_FRACTION,
    max_percent: float = MAX_BET_PERCENT,
    max_total_exposure: float = 0.20,
) -> list:
    recommendations = []
    total_allocated = 0.0

    for bet in bets:
        rec = recommend_stake(
            prob=bet["fair_prob"],
            decimal_odds=bet["odds"],
            bankroll=bankroll,
            fraction=fraction,
            max_percent=max_percent,
        )

        if total_allocated + rec.stake_percent > max_total_exposure:
            remaining = max(0, max_total_exposure - total_allocated)
            rec = KellyRecommendation(
                full_kelly=rec.full_kelly,
                fractional_kelly=rec.fractional_kelly,
                recommended_stake=round(remaining * bankroll, 2),
                stake_percent=round(remaining, 6),
                capped=True,
            )

        total_allocated += rec.stake_percent
        recommendations.append(rec)

    return recommendations
