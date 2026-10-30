import asyncio
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from odds_api.application.services import CollectionService, OddsQueryService, QueryError
from odds_api.domain.models import Availability


def query(repo, clock):
    return OddsQueryService(repo, clock, 90, 3600, {"h2h", "player_points", "player_points_alternate"})


async def test_collection_orchestrates_without_network(repo, board, clock):
    provider = AsyncMock()
    provider.fetch.return_value = board()
    await CollectionService(provider, repo, clock).collect("nba_basketball", "moneyline")
    assert len(repo.quotes("nba_basketball")) == 2


async def test_collection_outage_preserves_cache_and_logs_no_secret(repo, board, clock, caplog):
    repo.save(board())
    provider = AsyncMock()
    provider.fetch.side_effect = RuntimeError("provider key should-never-be-logged")
    await CollectionService(provider, repo, clock).collect("nba_basketball", "moneyline")
    assert len(repo.quotes("nba_basketball")) == 2
    assert "should-never-be-logged" not in caplog.text


async def test_cancelled_collection_is_logged_as_cancelled_and_preserves_cache(repo, board, clock, caplog):
    import logging

    repo.save(board())
    provider = AsyncMock()
    provider.fetch.side_effect = asyncio.CancelledError
    caplog.set_level(logging.INFO)
    with pytest.raises(asyncio.CancelledError):
        await CollectionService(provider, repo, clock).collect("nba_basketball", "props")
    record = next(record for record in caplog.records if record.message == "collection")
    assert record.outcome == "cancelled"
    assert record.error_type == "CancelledError"
    assert len(repo.quotes("nba_basketball")) == 2


async def test_collection_logs_safe_provider_context(repo, clock, caplog):
    import json
    import logging

    from odds_api.infrastructure.logging import JsonFormatter
    from odds_api.infrastructure.provider import ProviderError

    failure = ProviderError("provider_operation_failed", http_status=200)
    failure.provider_path = "/market/nba/props/people"
    provider = AsyncMock()
    provider.fetch.side_effect = failure
    caplog.set_level(logging.INFO)
    await CollectionService(provider, repo, clock).collect("nba_basketball", "props")
    record = next(record for record in caplog.records if record.message == "collection")
    rendered = json.loads(JsonFormatter().format(record))
    assert rendered["provider_path"] == "/market/nba/props/people"
    assert rendered["provider_http_status"] == 200
    assert rendered["outcome"] == "provider_operation_failed"


async def test_partial_collection_preserves_missing_prices_and_is_queryable(repo, board, clock):
    snapshot = board()
    repo.save(snapshot)
    provider = AsyncMock()
    provider.fetch.return_value = replace(
        snapshot,
        complete=False,
        quotes=snapshot.quotes[:1],
        warnings=("event_discovery_unavailable:/event/nba/upcoming:provider_operation_failed",),
    )
    await CollectionService(provider, repo, clock).collect("nba_basketball", "moneyline")
    result = query(repo, clock).odds("nba_basketball", odds_format="american")
    assert len(result[0]["bookmakers"][0]["markets"][0]["outcomes"]) == 2
    scope = next(
        scope
        for scope in repo.status(clock.now(), 90, 3600)["scopes"]
        if scope["league"] == "nba_basketball" and scope["kind"] == "moneyline"
    )
    assert scope["outcome"] == "partial" and scope["warnings"]


def test_queries_convert_and_filter(repo, board, clock):
    repo.save(board())
    repo.save(board("props"))
    service = query(repo, clock)
    assert len(service.events("nba_basketball")) == 1
    event_id = board().events[0].id
    response = service.odds(
        "nba_basketball",
        event_id=event_id,
        markets="player_points",
        bookmakers="unabated_901",
        odds_format="american",
    )
    assert response["bookmakers"][0]["markets"][0]["outcomes"][0]["description"] == "Sample Player"
    decimal = service.odds("nba_basketball")
    assert decimal[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] == 2.2
    assert service.events("nba_basketball", start=clock.now() + timedelta(days=2)) == []


@pytest.mark.parametrize(
    "options",
    [
        {"markets": "wrong"},
        {"bookmakers": "missing"},
        {"markets": "h2h,"},
        {"odds_format": "fractional"},
        {"event_id": "unknown"},
    ],
)
def test_invalid_queries_are_explicit(repo, board, clock, options):
    repo.save(board())
    with pytest.raises(QueryError):
        query(repo, clock).odds("nba_basketball", **options)


def test_unknown_sport_and_invalid_time_bounds(repo, clock):
    service = query(repo, clock)
    with pytest.raises(QueryError, match="Unknown sport"):
        service.events("unknown")
    with pytest.raises(QueryError, match="precede"):
        service.events("nba_basketball", start=clock.now(), end=clock.now() - timedelta(days=1))


def test_stale_and_terminal_event_quotes_are_excluded(repo, board, clock):
    snapshot = board()
    repo.save(snapshot)
    service = query(repo, clock)
    clock.value = 91
    assert service.odds("nba_basketball") == []
    clock.value = 0
    repo.save(replace(snapshot, events=(replace(snapshot.events[0], status="final"),)))
    assert service.events("nba_basketball") == []
    assert service.odds("nba_basketball") == []
    assert service.odds("nba_basketball", event_id=snapshot.events[0].id)["bookmakers"] == []


def test_list_endpoint_limits_props_to_event_endpoint(repo, clock):
    with pytest.raises(QueryError, match="event odds endpoint"):
        query(repo, clock).moneylines("nba_basketball", markets="player_points")


@pytest.mark.parametrize("blocker", ["source_age", "expiry", "suspended", "removed", "final"])
def test_cached_props_never_override_source_expiry_or_unavailable_states(repo, board, clock, blocker):
    snapshot = board("props")
    quotes = []
    for quote in snapshot.quotes:
        change = {
            "source_age": {"source_updated_at": clock.now() - timedelta(hours=2)},
            "expiry": {"expires_at": clock.now() + timedelta(seconds=90)},
            "suspended": {"state": Availability.SUSPENDED},
            "removed": {"state": Availability.REMOVED},
            "final": {},
        }[blocker]
        quotes.append(replace(quote, **change))
    events = (replace(snapshot.events[0], status="final"),) if blocker == "final" else snapshot.events
    repo.save(replace(snapshot, quotes=tuple(quotes), events=events))
    clock.value = 91
    payload = query(repo, clock).props("nba_basketball", snapshot.events[0].id)
    assert payload["bookmakers"] == []
    assert payload["freshness"]["status"] == "unavailable"


def test_cached_props_are_bounded_without_mutating_stored_timestamps(repo, board, clock):
    snapshot = board("props")
    snapshot = replace(snapshot, quotes=tuple(replace(q, source_updated_at=None) for q in snapshot.quotes))
    repo.save(snapshot)
    service = query(repo, clock)
    clock.value = 3600
    cached = service.props("nba_basketball", snapshot.events[0].id)
    assert cached["freshness"]["status"] == "stale"
    assert cached["freshness"]["stale_outcomes"] == 3
    assert all(r["quote"].collected_at == snapshot.collected_at for r in repo.quotes("nba_basketball"))
    clock.value += 0.001
    assert service.props("nba_basketball", snapshot.events[0].id)["bookmakers"] == []


def test_cached_props_can_be_disabled_by_configuration(repo, board, clock):
    snapshot = board("props")
    repo.save(snapshot)
    service = OddsQueryService(repo, clock, 90, 3600, {"player_points"}, props_cache_ttl=0)
    clock.value = 91
    assert service.props("nba_basketball", snapshot.events[0].id)["bookmakers"] == []
