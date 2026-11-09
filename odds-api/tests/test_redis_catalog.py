from dataclasses import replace

import fakeredis
from test_redis_storage import future_board

from odds_api.infrastructure.config import DEFAULT_LEAGUES
from odds_api.infrastructure.redis_repository import RedisRepository


def repository(clock):
    return RedisRepository(
        "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(decode_responses=True)
    )


def test_event_and_book_filters_never_decode_unrelated_stored_prices(board, clock, monkeypatch):
    repo = repository(clock)
    snapshot = future_board(board, clock)
    repo.save(snapshot)

    def no_prices(*args, **kwargs):
        raise AssertionError("Catalog reads must not decompress retained prices")

    monkeypatch.setattr("odds_api.infrastructure.redis_repository.decode_document", no_prices)
    assert repo.events(snapshot.league.key)[0]["id"] == snapshot.events[0].id
    assert repo.bookmakers() == {"fixturebook"}
    events, support = repo.bet365_context(snapshot.league.key, set(), str.lower)
    assert len(events) == 1 and support == []


def test_legacy_catalog_upgrades_once_and_does_not_retain_deleted_events(board, clock, monkeypatch):
    import odds_api.infrastructure.redis_repository as module

    repo = repository(clock)
    snapshot = future_board(board, clock)
    repo.save(snapshot)
    repo.client.delete(repo.key("catalog:" + snapshot.league.key))
    original = module.decode_document
    decoded = []

    def decode(value):
        decoded.append(True)
        return original(value)

    monkeypatch.setattr(module, "decode_document", decode)
    assert len(repo.events(snapshot.league.key)) == 1
    assert repo.bookmakers() == {"fixturebook"}
    assert len(decoded) == 1
    repo.client.delete(repo.key("event:" + snapshot.events[0].id))
    assert repo.events(snapshot.league.key) == []
    assert repo.bookmakers() == set()


def test_catalog_tracks_rescheduling_and_prunes_with_event_index(board, clock):
    from datetime import timedelta

    repo = repository(clock)
    snapshot = future_board(board, clock)
    repo.save(snapshot)
    event = replace(snapshot.events[0], start=clock.now() + timedelta(hours=2))
    repo.save(replace(snapshot, events=(event,)))
    assert repo.events(snapshot.league.key)[0]["start"] == event.start
    clock.value += 7201
    assert repo.prune_started() == 1
    assert repo.client.hlen(repo.key("catalog:" + snapshot.league.key)) == 0
