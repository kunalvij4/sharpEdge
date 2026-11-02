from dataclasses import replace

import fakeredis
import pytest
from fastapi.testclient import TestClient
from test_redis_storage import future_board

from odds_api.domain.models import Sportsbook
from odds_api.domain.sportsbooks import sportsbook_key
from odds_api.http.app import create_app
from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings
from odds_api.infrastructure.redis_repository import RedisRepository


@pytest.mark.parametrize("title", ["DraftKings", "Draft Kings", "DraftKings Sportsbook", "DRAFTKINGS"])
def test_sportsbook_keys_do_not_depend_on_feed(title):
    assert sportsbook_key("unabated_91", title) == sportsbook_key("propline_draftkings", "DraftKings")
    assert sportsbook_key("unabated_91", title) == "draftkings"


@pytest.mark.parametrize("title", ["ProphetX", "Prophet Exchange", "ProphetXchange", "PROPHET EXCHANGE"])
def test_prophet_aliases_share_one_public_key(title):
    assert sportsbook_key("unabated_91", title) == "prophetxchange"
    assert sportsbook_key("propline_prophetx", title) == "prophetxchange"


@pytest.mark.parametrize(
    "unabated_title,propline_title,propline_key,public_key",
    [
        ("Draft Kings", "DraftKings", "draftkings", "draftkings"),
        ("Prophet Exchange", "ProphetX", "prophetx", "prophetxchange"),
    ],
)
@pytest.mark.parametrize("propline_first", [False, True])
@pytest.mark.parametrize("backend", ["sql", "redis"])
@pytest.mark.parametrize("kind", ["moneyline", "props"])
@pytest.mark.parametrize("refresh", ["complete", "partial", "empty"])
def test_unabated_refresh_preserves_propline_and_other_books(
    repo,
    board,
    clock,
    backend,
    kind,
    refresh,
    propline_first,
    unabated_title,
    propline_title,
    propline_key,
    public_key,
):
    repository = (
        repo
        if backend == "sql"
        else RedisRepository(
            "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(decode_responses=True)
        )
    )
    original = future_board(lambda: board(kind), clock)
    primary_book = Sportsbook("91", unabated_title)
    fanduel = Sportsbook("92", "FanDuel")
    propline_book = Sportsbook(propline_key, propline_title, "propline")
    unabated = replace(
        original,
        books=(primary_book, fanduel),
        quotes=tuple(replace(q, book_id=b.id) for b in (primary_book, fanduel) for q in original.quotes),
    )
    propline = replace(
        original,
        provider="propline",
        books=(propline_book,),
        covered_markets=tuple({q.market for q in original.quotes}),
        quotes=tuple(replace(q, book_id=propline_book.id, price=175) for q in original.quotes),
    )
    for source in (propline, unabated) if propline_first else (unabated, propline):
        repository.save(source)
    expected = {q.selection_id: q for q in (*unabated.quotes, *propline.quotes)}
    # Exercise multiple stored-document round trips while omitting other books.
    for tick in (10, 20, 30):
        clock.value = tick
        quote = replace(
            unabated.quotes[0], price=150, collected_at=clock.now(), source_updated_at=clock.now()
        )
        incoming = () if refresh == "empty" else (quote,)
        repository.save(
            replace(
                unabated,
                books=(primary_book,),
                quotes=incoming,
                complete=refresh != "partial",
                collected_at=clock.now(),
            )
        )
        if incoming:
            expected[quote.selection_id] = quote
        saved = {r["quote"].selection_id: r["quote"] for r in repository.quotes(original.league.key)}
        assert saved == expected
    settings = Settings(
        _env_file=None, api_keys="test-key", bet365_enabled=False, collected_ttl=90, props_cache_ttl=0
    )
    with TestClient(create_app(settings, repository, clock)) as client:
        headers = {"X-API-Key": "test-key"}
        path = f"/v1/events/{original.events[0].id}/{'props' if kind == 'props' else 'odds'}"
        response = client.get(path + "?oddsFormat=american", headers=headers)
        assert response.status_code == 200
        books = response.json()["bookmakers"]
        assert {b["key"] for b in books} == {public_key, "fanduel"}
        assert len(books) == 2
        primary = next(b for b in books if b["key"] == public_key)
        if public_key == "prophetxchange":
            assert primary["title"] == "ProphetXchange"
        prices = {o["price"] for m in primary["markets"] for o in m["outcomes"]}
        assert 175 in prices
        assert (150 if refresh != "empty" else 175) in prices
        filtered = client.get(path + f"?bookmakers={public_key}", headers=headers)
        assert filtered.status_code == 200
        assert [b["key"] for b in filtered.json()["bookmakers"]] == [public_key]

        # Aging changes freshness, never sportsbook membership or the chosen price.
        clock.value = 150
        aged = client.get(path + "?oddsFormat=american", headers=headers)
        assert aged.status_code == 200
        assert [b["key"] for b in aged.json()["bookmakers"]] == sorted([public_key, "fanduel"])
        aged_primary = next(b for b in aged.json()["bookmakers"] if b["key"] == public_key)
        assert {o["price"] for m in aged_primary["markets"] for o in m["outcomes"]} == prices
        assert {
            r["quote"].selection_id: r["quote"] for r in repository.quotes(original.league.key)
        } == expected
