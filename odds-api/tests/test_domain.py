from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from odds_api.domain.models import Availability, american_odds, decimal_odds


@pytest.mark.parametrize("american,decimal", [(100, "2"), (-100, "2"), (150, "2.5"), (-200, "1.5")])
def test_odds_conversion(american, decimal):
    assert decimal_odds(american) == Decimal(decimal)
    assert american_odds(Decimal(decimal)) == (100 if american == -100 else american)


@pytest.mark.parametrize("price", [0, 99, -99, True])
def test_invalid_american(price):
    with pytest.raises(ValueError):
        decimal_odds(price)


@pytest.mark.parametrize("price", ["1", "0", "NaN", "Infinity"])
def test_invalid_decimal(price):
    with pytest.raises(ValueError):
        american_odds(Decimal(price))


def test_event_identity_is_not_names_or_schedule(board):
    event = board().events[0]
    assert replace(event, start=event.start + timedelta(days=1), home="Renamed").id == event.id
    assert replace(event, source_id="other").id != event.id


def test_quote_identity_includes_line_player_period_and_book(board):
    quote = board("props").quotes[0]
    for changed in (
        replace(quote, point=Decimal("99.5")),
        replace(quote, player_id="different"),
        replace(quote, period="q1"),
        replace(quote, book_id="another"),
        replace(quote, alternate=not quote.alternate),
    ):
        assert changed.market_id != quote.market_id
    assert replace(quote, source_selection_id="relisted").selection_id == quote.selection_id


def test_missing_source_time_and_freshness(board, clock):
    quote = replace(board().quotes[0], source_updated_at=None)
    assert quote.availability(clock.now(), 90, 1) == Availability.AVAILABLE
    assert quote.availability(clock.now() + timedelta(seconds=91), 90, 1) == Availability.STALE
    assert replace(quote, expires_at=clock.now()).availability(clock.now(), 90, 1) == Availability.STALE
    assert (
        replace(quote, state=Availability.SUSPENDED).availability(clock.now() + timedelta(days=5), 90, 1)
        == Availability.SUSPENDED
    )


def test_source_freshness_has_separate_threshold(board, clock):
    quote = board().quotes[0]
    assert quote.availability(clock.now(), 90, 30) == Availability.STALE


def test_naive_timestamp_rejected(board):
    with pytest.raises(ValueError):
        replace(board().quotes[0], collected_at=datetime(2026, 1, 1))


def test_domain_timestamps_are_canonical_utc(board):
    from datetime import UTC, timezone

    original = board().events[0]
    shifted = original.start.astimezone(timezone(timedelta(hours=5)))
    assert replace(original, start=shifted).start.tzinfo == UTC
