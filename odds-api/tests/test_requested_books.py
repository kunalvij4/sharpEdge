import copy
from dataclasses import replace

import fakeredis
import pytest
from fastapi.testclient import TestClient
from test_propline_integration import snapshot
from test_redis_storage import future_board

from odds_api.domain.models import League
from odds_api.domain.sportsbooks import sportsbook_key
from odds_api.http.app import create_app
from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings
from odds_api.infrastructure.propline import SPORT_KEYS, BulkOdds, Event
from odds_api.infrastructure.propline_normalization import boards
from odds_api.infrastructure.redis_repository import RedisRepository


@pytest.mark.parametrize("title", ["Underdog", "Underdog Fantasy", "Underdog Pick'em"])
def test_underdog_has_one_public_bookmaker_key(title):
    assert sportsbook_key("propline_underdog", title) == "underdog"


@pytest.mark.parametrize("backend", ["sql", "redis"])
@pytest.mark.parametrize("sport", ["nba_basketball", "ncaab_basketball"])
def test_requested_books_reach_api_with_exact_prices_and_missing_player_ids(
    repo, board, clock, backend, sport
):
    repository = (
        repo
        if backend == "sql"
        else RedisRepository(
            "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(decode_responses=True)
        )
    )
    raw = snapshot(board, clock)
    source = future_board(board, clock)
    event = replace(source.events[0], league_key=sport)
    config = DEFAULT_LEAGUES[sport]
    source = replace(
        source,
        league=League(sport, config["title"], config["route"], "42"),
        events=(event,),
        quotes=tuple(replace(q, event_id=event.id) for q in source.quotes),
    )
    repository.save(source)
    raw[0].update(sport_key=SPORT_KEYS[sport], commence_time=event.start.isoformat())
    template = raw[0]["bookmakers"][0]
    for market in template["markets"]:
        market["last_update"] = clock.now().isoformat()
        for outcome in market["outcomes"]:
            outcome["last_seen_at"] = clock.now().isoformat()
    template["markets"][2]["outcomes"] = template["markets"][2]["outcomes"][:2]
    for outcome in template["markets"][2]["outcomes"]:
        outcome["player_id"] = None
    prizepicks = copy.deepcopy(template)
    prizepicks.update(key="prizepicks", title="Prize Picks", markets=prizepicks["markets"][2:])
    for outcome in prizepicks["markets"][0]["outcomes"]:
        outcome.update(price=100, dfs_odds_type="standard")
    for flavor, point in (("goblin", 15.5), ("demon", 35.5), (None, 45.5)):
        alternate = copy.deepcopy(prizepicks["markets"][0])
        for outcome in alternate["outcomes"]:
            outcome.update(point=point, dfs_odds_type=flavor)
        prizepicks["markets"].append(alternate)
    underdog = copy.deepcopy(template)
    underdog.update(key="underdog", title="Underdog Fantasy", markets=underdog["markets"][2:])
    for outcome, price, multiplier in zip(underdog["markets"][0]["outcomes"], (-135, 110), (0.86, 1.1)):
        outcome.update(price=price, payout_multiplier=multiplier)
    sportzino = copy.deepcopy(template)
    sportzino.update(key="sportzino", title="Sportzino")
    raw[0]["bookmakers"] = [prizepicks, underdog, sportzino]
    result = BulkOdds(sport, tuple(Event.model_validate(e) for e in raw), raw, {}, clock.now(), 0, 0)
    output, counts = boards(result, repository)
    assert counts["stored_outcomes"] == 10
    assert counts["stored_outcomes:prizepicks"] == 2
    assert counts["stored_outcomes:underdog"] == 2
    assert counts["stored_outcomes:sportzino"] == 6
    assert counts["excluded_nonstandard_prizepicks_outcomes"] == 6
    assert not counts.get("props_without_confirmed_player_id")
    for collected in output:
        repository.save(collected)
    original = repository.quotes(sport)
    headers = {"X-API-Key": "test-key"}
    with TestClient(create_app(Settings(_env_file=None, api_keys="test-key"), repository, clock)) as api:
        payload = api.get(f"/v1/events/{event.id}/props?oddsFormat=american", headers=headers)
        assert payload.status_code == 200
        books = {book["key"]: book for book in payload.json()["bookmakers"]}
        assert set(books) == {"prizepicks", "underdog", "sportzino"}
        assert books["underdog"]["title"] == "Underdog"
        assert books["prizepicks"]["title"] == "PrizePicks"
        assert {o["price"] for m in books["underdog"]["markets"] for o in m["outcomes"]} == {-135, 110}
        assert {o["price"] for m in books["prizepicks"]["markets"] for o in m["outcomes"]} == {100}
        for book in books.values():
            for market in book["markets"]:
                for outcome in market["outcomes"]:
                    assert set(outcome) == {"name", "price", "point", "description"}
                    assert outcome["point"] == 25.5
        for key in books:
            filtered = api.get(f"/v1/events/{event.id}/props?bookmakers={key}", headers=headers)
            assert [book["key"] for book in filtered.json()["bookmakers"]] == [key]
        game = api.get(f"/v1/sports/{sport}/odds?bookmakers=sportzino&markets=h2h,spreads", headers=headers)
        assert game.status_code == 200
        assert {m["key"] for m in game.json()[0]["bookmakers"][0]["markets"]} == {"h2h", "spreads"}
    assert repository.quotes(sport) == original


def test_ambiguous_players_still_block_requested_book_props(repo, board, clock):
    source = board("props")
    ambiguous = replace(source.quotes[0], player_id="another-player")
    repo.save(replace(source, quotes=(*source.quotes, ambiguous)))
    raw = snapshot(board, clock)
    book = raw[0]["bookmakers"][0]
    book.update(key="underdog", title="Underdog Fantasy", markets=book["markets"][2:])
    for outcome in book["markets"][0]["outcomes"]:
        outcome["player_id"] = None
    result = BulkOdds(
        "nba_basketball", tuple(Event.model_validate(e) for e in raw), raw, {}, clock.now(), 0, 0
    )
    output, counts = boards(result, repo)
    assert not any(b.quotes for b in output)
    assert counts["ambiguous_players"] == 3
