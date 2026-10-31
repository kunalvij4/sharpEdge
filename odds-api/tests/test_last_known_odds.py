from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import fakeredis
import pytest
from fastapi.testclient import TestClient
from test_redis_storage import future_board

from odds_api.domain.models import Availability, Sportsbook
from odds_api.http.app import create_app
from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings
from odds_api.infrastructure.redis_repository import RedisRepository


@pytest.mark.parametrize("backend", ["sql", "redis"])
@pytest.mark.parametrize("kind", ["moneyline", "props"])
@pytest.mark.parametrize("incoming", ["fresher", "empty", "older_source", "missing_source", "suspended"])
def test_delayed_unabated_pull_only_changes_exact_fresher_sportsbook_selection(
    repo, board, clock, backend, kind, incoming
):
    repository = (
        repo
        if backend == "sql"
        else RedisRepository(
            "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(decode_responses=True)
        )
    )
    source = future_board(lambda: board(kind), clock)
    dk = Sportsbook("draftkings", "DraftKings", "propline")
    fd = Sportsbook("fanduel", "FanDuel", "propline")
    original = replace(
        source.quotes[0], book_id=dk.id, price=175, expires_at=clock.now() + timedelta(seconds=600)
    )
    peer = replace(original, book_id=fd.id)
    other_line = replace(original, point=(original.point or Decimal(0)) + 1)
    propline = replace(
        source,
        books=(dk, fd),
        quotes=(original, peer, other_line),
        provider="propline",
        covered_markets=(original.market,),
    )
    repository.save(propline)
    # The normal alternating schedule can exceed ten minutes when scopes are slow.
    clock.value = 900
    unabated_book = Sportsbook("91", "Draft Kings")
    update = replace(
        original,
        book_id=unabated_book.id,
        price=150,
        player_id="unabated-player" if original.player_id else None,
        collected_at=clock.now(),
        source_updated_at=clock.now(),
        expires_at=clock.now() + timedelta(seconds=600),
    )
    if incoming == "older_source":
        update = replace(update, source_updated_at=original.source_updated_at - timedelta(seconds=1))
    if incoming == "missing_source":
        update = replace(update, source_updated_at=None)
    if incoming == "suspended":
        update = replace(update, state=Availability.SUSPENDED, price=None)
    refresh = replace(
        source,
        books=(unabated_book,),
        quotes=() if incoming == "empty" else (update,),
        collected_at=clock.now(),
    )
    settings = Settings(_env_file=None, api_keys="test-key", props_cache_ttl=0)
    path = f"/v1/events/{source.events[0].id}/{'props' if kind == 'props' else 'odds'}?oddsFormat=american"
    headers = {"X-API-Key": "test-key"}
    with TestClient(create_app(settings, repository, clock)) as client:
        before = client.get(path, headers=headers)
        assert before.status_code == 200
        assert {b["key"] for b in before.json()["bookmakers"]} == {"draftkings", "fanduel"}
        repository.save(refresh)
        after = client.get(path, headers=headers)
        assert after.status_code == 200
        books = {b["key"]: b for b in after.json()["bookmakers"]}
        assert books["fanduel"] == next(b for b in before.json()["bookmakers"] if b["key"] == "fanduel")
        outcomes = [o for m in books["draftkings"]["markets"] for o in m["outcomes"]]
        assert len(outcomes) == 2
        assert sorted(o["price"] for o in outcomes) == ([150, 175] if incoming == "fresher" else [175, 175])
        retained = [o for o in outcomes if o["price"] == 175]
        assert all(o["freshness"]["status"] == "stale" and not o["freshness"]["actionable"] for o in retained)
        clock.value = 7200
        aged = client.get(path, headers=headers)
        assert {b["key"] for b in aged.json()["bookmakers"]} == {"draftkings", "fanduel"}
        assert sorted(
            o["price"] for b in aged.json()["bookmakers"] for m in b["markets"] for o in m["outcomes"]
        ) == ([150, 175, 175] if incoming == "fresher" else [175, 175, 175])
        assert client.get(path + "&freshOnly=true", headers=headers).json()["bookmakers"] == []
    saved = {r["quote"].selection_id: r["quote"] for r in repository.quotes(source.league.key)}
    assert all(saved[q.selection_id] == q for q in propline.quotes)
