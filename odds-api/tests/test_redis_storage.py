from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient

from odds_api.collector import CombinedCollection
from odds_api.domain.models import Sportsbook
from odds_api.http.app import create_app
from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings
from odds_api.infrastructure.provider import UnabatedClient
from odds_api.infrastructure.rate_limit import RateLimiter
from odds_api.infrastructure.redis_repository import (
    DOCUMENT_PREFIX,
    SHRINK_DOCUMENT,
    RedisRepository,
    decode_document,
    encode,
)
from odds_api.infrastructure.storage import collector_lease


class ScriptFlagRedis(fakeredis.FakeRedis):
    def eval(self, script, *args):
        # fakeredis runs Lua but does not parse Redis 7's shebang flags.
        # The real Redis/OOM behavior is exercised by the container smoke test.
        if script.startswith("#!lua flags=allow-oom\n"):
            script = script.split("\n", 1)[1]
        return super().eval(script, *args)


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
        unabated_odds_enabled=False,
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
    with collector_lease(repository) as lease:
        lease.ping()
        with pytest.raises(RuntimeError):
            with collector_lease(repository):
                pass
    with collector_lease(repository):
        pass


@pytest.mark.parametrize("refresh", ["complete", "partial", "empty"])
def test_redis_unabated_refresh_preserves_propline_bets(board, clock, refresh):
    repository = RedisRepository(
        "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(decode_responses=True)
    )
    source = future_board(board, clock)
    # Identical bookmaker names and source IDs must still retain provider identity.
    books = {book.id: Sportsbook(book.source_id, book.title, "propline") for book in source.books}
    propline_quotes = tuple(replace(q, book_id=books[q.book_id].id, price=150) for q in source.quotes)
    repository.save(source)
    repository.save(
        replace(
            source,
            provider="propline",
            books=tuple(books.values()),
            quotes=propline_quotes,
            covered_markets=("h2h",),
        )
    )
    clock.value += 10
    updated = tuple(
        replace(q, price=180, collected_at=clock.now(), source_updated_at=clock.now()) for q in source.quotes
    )
    repository.save(
        replace(
            source,
            quotes=() if refresh == "empty" else updated,
            collected_at=clock.now(),
            complete=refresh != "partial",
        )
    )
    rows = repository.quotes(source.league.key)
    assert {r["quote"].selection_id: r["quote"] for r in rows if r["book_key"].startswith("propline_")} == {
        q.selection_id: q for q in propline_quotes
    }
    assert {r["quote"].selection_id: r["quote"] for r in rows if r["book_key"].startswith("unabated_")} == {
        q.selection_id: q for q in (source.quotes if refresh == "empty" else updated)
    }


def test_compaction_preserves_both_providers_and_exact_expiry(board, clock):
    repository = RedisRepository(
        "", DEFAULT_LEAGUES, clock=clock, client=ScriptFlagRedis(decode_responses=True)
    )
    source = future_board(board, clock)
    books = {book.id: Sportsbook(book.source_id, book.title, "propline") for book in source.books}
    repository.save(source)
    repository.save(
        replace(
            source,
            provider="propline",
            books=tuple(books.values()),
            quotes=tuple(replace(q, book_id=books[q.book_id].id) for q in source.quotes),
            covered_markets=("h2h",),
        )
    )
    key = repository.key("event:" + source.events[0].id)
    legacy = encode(decode_document(repository.client.get(key)))
    repository.client.set(key, legacy, keepttl=True)
    expiry = repository.client.pexpiretime(key)
    before = repository.quotes(source.league.key)
    counts = repository.compact_event_documents()
    packed = repository.client.get(key)
    assert counts["compressed_events"] == 1
    assert counts["bytes_after"] < counts["bytes_before"] / 2
    assert packed.startswith(DOCUMENT_PREFIX)
    assert decode_document(packed) == decode_document(legacy)
    assert repository.client.pexpiretime(key) == expiry
    assert repository.quotes(source.league.key) == before
    assert {r["book_key"].split("_", 1)[0] for r in before} == {"unabated", "propline"}
    assert repository.compact_event_documents()["compressed_events"] == 0


@pytest.mark.parametrize("race", ["updated", "expired"])
def test_compaction_cannot_overwrite_a_concurrent_update_or_resurrect_expiry(board, clock, monkeypatch, race):
    repository = RedisRepository(
        "", DEFAULT_LEAGUES, clock=clock, client=ScriptFlagRedis(decode_responses=True)
    )
    source = future_board(board, clock)
    repository.save(source)
    key = repository.key("event:" + source.events[0].id)
    document = decode_document(repository.client.get(key))
    repository.client.set(key, encode(document), keepttl=True)
    next(iter(document["quotes"].values()))["quote"]["price"] = 155
    updated = encode(document)
    original_eval = repository.client.eval

    def concurrent_change(*args):
        if race == "updated":
            repository.client.set(key, updated, keepttl=True)
        else:
            repository.client.delete(key)
        return original_eval(*args)

    monkeypatch.setattr(repository.client, "eval", concurrent_change)
    assert repository.compact_event_documents()["compressed_events"] == 0
    assert repository.client.get(key) == (updated if race == "updated" else None)


@pytest.mark.parametrize("packed", [DOCUMENT_PREFIX + "x" * 10000, "bad"], ids=["growing", "unknown"])
def test_memory_recovery_script_refuses_growth_and_unknown_encoding(packed):
    client = ScriptFlagRedis(decode_responses=True)
    original = '{"quotes":{}}'
    client.set("event", original)
    assert client.eval(SHRINK_DOCUMENT, 1, "event", original, packed) == -1
    assert client.get("event") == original


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
        unabated_odds_enabled=False,
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
