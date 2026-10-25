from dataclasses import replace
from datetime import timedelta

import pytest

from odds_api.domain.models import Availability, Sportsbook


@pytest.mark.parametrize("provider", ["unabated", "propline"])
@pytest.mark.parametrize(
    "incoming",
    [
        "missing",
        "partial_missing",
        "older",
        "equal",
        "older_source",
        "missing_source",
        "suspended",
        "removed",
        "expired",
        "future_collection",
        "future_source",
        "stale_source",
        "stale_collection",
        "valid",
    ],
)
def test_only_valid_fresher_replacements_change_existing_quote(repo, board, clock, provider, incoming):
    original = board()
    repo.save(replace(original, quotes=()))
    quote = replace(
        original.quotes[0],
        source_updated_at=clock.now() - timedelta(seconds=30),
        expires_at=clock.now() + timedelta(seconds=600),
    )
    if provider == "propline":
        book = Sportsbook("draftkings", "DraftKings", "propline")
        quote = replace(quote, book_id=book.id)
        original = replace(
            original, provider="propline", books=(book,), quotes=(quote,), covered_markets=("h2h",)
        )
    original = replace(original, quotes=(quote,))
    repo.save(original)
    clock.value = 4000 if incoming in {"stale_source", "stale_collection"} else 10
    updated = replace(
        quote,
        price=150,
        collected_at=clock.now(),
        source_updated_at=clock.now(),
        expires_at=clock.now() + timedelta(seconds=600),
        source_selection_id="replacement",
    )
    if incoming in {"missing", "partial_missing"}:
        refresh = replace(original, quotes=(), complete=incoming == "missing")
    else:
        changes = {
            "older": {"collected_at": quote.collected_at - timedelta(seconds=1)},
            "equal": {"collected_at": quote.collected_at},
            "older_source": {"source_updated_at": quote.source_updated_at - timedelta(seconds=1)},
            "missing_source": {"source_updated_at": None},
            "suspended": {"state": Availability.SUSPENDED, "price": None},
            "removed": {"state": Availability.REMOVED, "price": None},
            "expired": {"expires_at": clock.now()},
            "future_collection": {"collected_at": clock.now() + timedelta(seconds=6)},
            "future_source": {"source_updated_at": clock.now() + timedelta(seconds=6)},
            "stale_source": {"source_updated_at": clock.now() - timedelta(seconds=3601)},
            "stale_collection": {"collected_at": clock.now() - timedelta(seconds=601)},
            "valid": {},
        }
        refresh = replace(original, quotes=(replace(updated, **changes[incoming]),))
    repo.save(refresh)
    saved = next(
        r["quote"] for r in repo.quotes("nba_basketball") if r["quote"].selection_id == quote.selection_id
    )
    assert saved == (updated if incoming == "valid" else quote)


def test_fresher_price_updates_one_selection_without_refreshing_absent_peer(repo, board, clock):
    original = board()
    repo.save(original)
    clock.value = 10
    newer = replace(original.quotes[0], price=150, collected_at=clock.now(), source_updated_at=clock.now())
    repo.save(replace(original, collected_at=clock.now(), quotes=(newer,)))
    saved = {r["quote"].selection_id: r["quote"] for r in repo.quotes("nba_basketball")}
    assert saved[newer.selection_id] == newer
    assert saved[original.quotes[1].selection_id] == original.quotes[1]
    clock.value = 601
    repo.save(replace(original, collected_at=clock.now(), quotes=()))
    retained = {r["quote"].selection_id: r["quote"] for r in repo.quotes("nba_basketball")}
    assert retained == saved
    assert (
        retained[original.quotes[1].selection_id].availability(clock.now(), 600, 3600) == Availability.STALE
    )
