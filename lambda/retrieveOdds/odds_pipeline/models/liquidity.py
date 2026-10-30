"""Liquidity-based reweighting for exchange books (Novig, ProphetX).

Liquidity is the stake available at the quoted price on each side of a market.
An exchange only earns extra weight when both sides are deep, so the smaller
side decides the tier; under MIN_LIQUIDITY the book is dropped. Missing
liquidity keeps the base weight.

Disabled by default: set LIQUIDITY_REWEIGHTING=true to turn it on once a
liquidity feed exists. While disabled, every book keeps its base weight.
"""

import math
import os

BOOSTED_BOOKS = frozenset({"NoVig", "ProphetX"})


def reweighting_enabled():
    return os.environ.get("LIQUIDITY_REWEIGHTING", "").strip().lower() in {"1", "true", "yes", "on"}

# Below this on the thinner side, a boosted book is ignored entirely.
MIN_LIQUIDITY = 100

# (minimum liquidity on the thinner side, weight multiplier), highest tier first.
LIQUIDITY_TIERS = ((2000, 2.0), (500, 1.5), (MIN_LIQUIDITY, 1.0))


def _usable(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def liquidity_multiplier(sides, tiers=LIQUIDITY_TIERS):
    """Return the weight multiplier for a book given its per-side liquidity."""
    if not sides:
        return 1.0
    values = [_usable(side) for side in sides]
    if len(values) < 2 or any(value is None for value in values):
        return 1.0
    thinnest = min(values)
    for minimum, multiplier in tiers:
        if thinnest >= minimum:
            return multiplier
    return 0.0


def apply_liquidity_boost(weights, liquidity, boosted_books=BOOSTED_BOOKS):
    """Return a copy of weights with boosted books scaled by their liquidity tier.

    liquidity maps book name -> (side_a_liquidity, side_b_liquidity). The result
    is not normalised; callers divide by the total weight as they already do.
    """
    if not liquidity or not reweighting_enabled():
        return dict(weights)
    return {
        book: weight * (liquidity_multiplier(liquidity.get(book)) if book in boosted_books else 1.0)
        for book, weight in weights.items()
    }
