from dataclasses import replace

import fakeredis
import pytest
from fastapi.testclient import TestClient
from test_redis_storage import future_board

from odds_api.http.app import create_app
from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings
from odds_api.infrastructure.redis_repository import RedisRepository


@pytest.mark.parametrize("backend", ["sql", "redis"])
def test_links_are_opt_in_fresh_and_keep_exact_alternate_identity(repo, board, clock, backend):
    source = future_board(lambda: board("props"), clock)
    original = source.quotes[0]
    source = replace(
        source,
        quotes=(
            replace(original, deep_link="https://www.gambly.com/deeplink/odds/901/101/20.5"),
            replace(
                original,
                point=original.point + 1,
                alternate=True,
                market="player_points_alternate",
                deep_link=None,
            ),
        ),
    )
    repository = (
        repo
        if backend == "sql"
        else RedisRepository(
            "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(decode_responses=True)
        )
    )
    repository.save(source)
    settings = Settings(_env_file=None, api_keys="test", propline_enabled=False, collected_ttl=90)
    path = f"/v1/events/{source.events[0].id}/odds?markets=all_props"
    with TestClient(create_app(settings, repository, clock)) as api:
        plain = api.get(path, headers={"X-API-Key": "test"})
        assert plain.status_code == 200
        assert all(
            "bet_link" not in o
            for b in plain.json()["bookmakers"]
            for m in b["markets"]
            for o in m["outcomes"]
        )
        result = api.get(path + "&includeBetLinks=true", headers={"X-API-Key": "test"})
        assert result.status_code == 200
        markets = result.json()["bookmakers"][0]["markets"]
        links = {m["key"]: m["outcomes"][0]["bet_link"] for m in markets}
        assert links[original.market] == {
            "provider": "unabated",
            "market_line_id": original.source_selection_id,
            "market_source_id": source.books[0].source_id,
            "url": "https://www.gambly.com/deeplink/odds/901/101/20.5",
            "status": "provided",
        }
        assert "url" not in links["player_points_alternate"]
        assert links["player_points_alternate"]["market_line_id"] == original.source_selection_id
        assert "_storage" not in result.text
        clock.value += 91
        stale = api.get(path + "&includeBetLinks=true", headers={"X-API-Key": "test"}).json()
        assert stale["bookmakers"]
        assert all(
            "bet_link" not in o for b in stale["bookmakers"] for m in b["markets"] for o in m["outcomes"]
        )


def test_propline_bulk_event_links_are_retained_without_losing_selection_links(repo, board, clock):
    from test_propline_integration import ingest, snapshot

    repo.save(board())
    raw = snapshot(board, clock)
    book = raw[0]["bookmakers"][0]
    book["link"] = "https://sportsbook.draftkings.com/event/1"
    selected = book["markets"][0]["outcomes"][0]
    selected["bet_link"] = "https://sportsbook.draftkings.com/slip/selection-7"
    output, _ = ingest(raw, repo, clock)
    quotes = [q for source in output for q in source.quotes]
    assert quotes
    assert sum(q.deep_link == selected["bet_link"] for q in quotes) == 1
    assert all(q.deep_link in {book["link"], selected["bet_link"]} for q in quotes)
    from odds_api.application.bet_links import bet_link

    for quote in quotes:
        link = bet_link(vars(quote), "propline_draftkings", True)
        assert link["url"] == quote.deep_link
        assert link["status"] == "event_support"


@pytest.mark.parametrize("backend", ["sql", "redis"])
def test_propline_app_only_link_survives_storage_and_public_projection(repo, board, clock, backend):
    from test_propline_integration import ingest, snapshot

    raw = snapshot(board, clock)
    future = future_board(board, clock)
    repo.save(future)
    raw[0]["commence_time"] = future.events[0].start.isoformat()
    for market in raw[0]["bookmakers"][0]["markets"]:
        market["last_update"] = clock.now().isoformat()
        for outcome in market["outcomes"]:
            if "last_seen_at" in outcome:
                outcome["last_seen_at"] = clock.now().isoformat()
    book = raw[0]["bookmakers"][0]
    book.update(key="courtside", title="Courtside", app_link="courtside://fixture/abc")
    output, _ = ingest(raw, repo, clock)
    repository = (
        repo
        if backend == "sql"
        else RedisRepository(
            "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(decode_responses=True)
        )
    )
    if backend == "redis":
        for source in output:
            repository.save(source)
    quotes = [
        row["quote"] for row in repository.quotes("nba_basketball") if row["book_key"].startswith("propline_")
    ]
    assert quotes and all(q.app_link == "courtside://fixture/abc" for q in quotes)
    assert all(q.deep_link is None for q in quotes)
    settings = Settings(_env_file=None, api_keys="test", propline_enabled=False)
    with TestClient(create_app(settings, repository, clock)) as api:
        path = f"/v1/events/{output[0].events[0].id}/odds?markets=all_props&includeBetLinks=true"
        response = api.get(path, headers={"X-API-Key": "test"})
        assert response.status_code == 200
        courtside = next(b for b in response.json()["bookmakers"] if b["key"] == "courtside")
        for market in courtside["markets"]:
            for outcome in market["outcomes"]:
                assert outcome["bet_link"] == {
                    "provider": "propline",
                    "app_url": "courtside://fixture/abc",
                    "status": "event_support",
                }
