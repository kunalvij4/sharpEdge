from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import fakeredis
import httpx
from fastapi.testclient import TestClient

from odds_api.collector import CombinedCollection
from odds_api.http.app import create_app
from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings
from odds_api.infrastructure.provider import UnabatedClient
from odds_api.infrastructure.rate_limit import RateLimiter
from odds_api.infrastructure.redis_repository import RedisRepository
from odds_api.infrastructure.storage import collector_lease


def future_board(board, clock):
    source = board()
    clock.origin = datetime.now(UTC)
    event = replace(source.events[0], start=clock.now() + timedelta(days=1))
    return replace(
        source,
        events=(event,),
        collected_at=clock.now(),
        quotes=tuple(
            replace(q, collected_at=clock.now(), source_updated_at=clock.now()) for q in source.quotes
        ),
    )


def test_redis_shared_reads_refresh_preservation_and_expiry(board, clock):
    server = fakeredis.FakeServer()
    writer = RedisRepository(
        "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(server=server, decode_responses=True)
    )
    reader = RedisRepository(
        "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(server=server, decode_responses=True)
    )
    source = future_board(board, clock)
    writer.save(source)
    event = source.events[0]
    assert reader.event(event.id)["id"] == event.id
    assert reader.quotes(source.league.key)
    assert writer.client.ttl(writer.key("event:" + event.id)) > 0
    original = reader.quotes(source.league.key)[0]["quote"]
    clock.value += 10
    writer.save(replace(source, quotes=(), collected_at=clock.now()))
    assert reader.quotes(source.league.key)[0]["quote"] == original
    changed = replace(original, price=150, collected_at=clock.now(), source_updated_at=clock.now())
    writer.save(replace(source, quotes=(changed,), collected_at=clock.now()))
    assert (
        next(
            r["quote"]
            for r in reader.quotes(source.league.key)
            if r["quote"].selection_id == changed.selection_id
        ).price
        == 150
    )
    settings = Settings(_env_file=None, api_keys="test-key")
    with TestClient(create_app(settings, reader, clock)) as client:
        response = client.get("/v1/sports/nba_basketball/odds", headers={"X-API-Key": "test-key"})
        assert response.status_code == 200 and response.json()[0]["bookmakers"]
        assert client.get("/v1/status", headers={"X-API-Key": "test-key"}).status_code == 200
    clock.value += 86400
    assert reader.events(source.league.key) == []
    assert reader.quotes(source.league.key) == []
    assert writer.prune_started() == 1


async def test_metadata_only_never_requests_unabated_odds(raw, clock, repo, tmp_path):
    paths = []
    payloads = {"/league": raw["leagues"], "/team/nba": raw["teams"], "/event/nba/upcoming": raw["events"]}

    def handler(request):
        paths.append(request.url.path)
        assert request.url.path in payloads
        return httpx.Response(200, json={"success": True, "data": payloads[request.url.path]})

    settings = Settings(
        _env_file=None,
        leagues_json='{"nba_basketball":{"title":"NBA","route":"nba"}}',
        propline_output_dir=str(tmp_path),
    )
    http = httpx.AsyncClient(base_url="https://data.unabated.com", transport=httpx.MockTransport(handler))
    provider = UnabatedClient(settings, clock, RateLimiter(clock, 0, 0), http)
    collection = CombinedCollection(settings, clock, repo, provider, Mock(), Mock())
    await collection.collect("unabated")
    assert set(paths) == set(payloads)
    assert repo.events("nba_basketball")
    assert repo.quotes("nba_basketball") == []
    await provider.close()


def test_redis_collector_lease_excludes_second_owner(clock):
    repository = RedisRepository(
        "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(decode_responses=True)
    )
    import pytest

    with collector_lease(repository) as lease:
        lease.ping()
        with pytest.raises(RuntimeError):
            with collector_lease(repository):
                pass
    with collector_lease(repository):
        pass


async def test_redis_cold_start_joins_propline_after_metadata(board, clock, tmp_path):
    from test_propline_integration import snapshot

    from odds_api.infrastructure.propline import ProplineClient

    raw = snapshot(board, clock)
    source = future_board(board, clock)
    for market in raw[0]["bookmakers"][0]["markets"]:
        market["last_update"] = clock.now().isoformat()
        for outcome in market["outcomes"]:
            if "last_seen_at" in outcome:
                outcome["last_seen_at"] = clock.now().isoformat()
    repository = RedisRepository(
        "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(decode_responses=True)
    )
    raw[0]["commence_time"] = source.events[0].start.isoformat()
    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(200, json=raw)

    class Catalog:
        async def fetch_catalog(self, sport):
            return replace(source, quotes=(), books=())

        async def fetch(self, *_):
            raise AssertionError("Unabated odds must not be requested")

    settings = Settings(
        _env_file=None,
        api_keys="test",
        propline_api_key="test",
        propline_output_dir=str(tmp_path),
        leagues_json='{"nba_basketball":{"title":"NBA","route":"nba"}}',
    )
    http = httpx.AsyncClient(base_url="https://api.prop-line.com", transport=httpx.MockTransport(handler))
    client = ProplineClient(settings, clock, http)
    collection = CombinedCollection(settings, clock, repository, Catalog(), client, Mock())
    await collection.collect("propline")
    assert repository.events("nba_basketball") == []
    clock.value = 240
    await collection.collect("unabated")
    assert len(requests) == 1
    assert len(repository.quotes("nba_basketball")) == 7
    assert repository.bookmakers() == {"propline_draftkings"}
    with TestClient(create_app(settings, repository, clock)) as api:
        response = api.get("/v1/sports/nba_basketball/odds", headers={"X-API-Key": "test"})
        assert response.status_code == 200
        assert response.json()[0]["id"] == source.events[0].id
        props = api.get("/v1/events/" + source.events[0].id + "/props", headers={"X-API-Key": "test"})
        assert props.status_code == 200 and props.json()["bookmakers"]
    await client.close()
