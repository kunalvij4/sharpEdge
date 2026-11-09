from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient
from test_bet365_league_dump import capture, row

from odds_api.bet365_collector import browser_environment, destination, jobs, transmit
from odds_api.domain.models import Availability, Board, Event, League, Quote, Sportsbook
from odds_api.http.app import create_app
from odds_api.infrastructure.bet365_ingestion import MAX_CAPTURE_BYTES
from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings
from odds_api.infrastructure.redis_repository import RedisRepository

ACTIVE = [key for key in DEFAULT_LEAGUES if key != "mlb_baseball"]


@pytest.fixture
def stream(clock):
    clock.origin = datetime.now(UTC)
    repository = RedisRepository(
        "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(decode_responses=True)
    )
    settings = Settings(
        _env_file=None,
        api_keys="product-key",
        bet365_enabled=True,
        bet365_ingest_key="collector-only",
        bet365_max_age=150,
    )

    def seed(key="nba_basketball"):
        league = League(key, DEFAULT_LEAGUES[key]["title"], DEFAULT_LEAGUES[key]["route"], "league")
        event = Event("canonical", key, clock.now() + timedelta(days=1), "Home", "Away", "pregame")
        book = Sportsbook("fixture", "Fixture Book")
        quotes = tuple(
            Quote(
                event.id,
                book.id,
                "h2h",
                "full",
                None,
                None,
                False,
                side,
                None,
                "canonical-market",
                side,
                -110,
                Availability.AVAILABLE,
                clock.now(),
            )
            for side in ("Home", "Away")
        )
        board = Board(league, "moneyline", (event,), (book,), quotes, clock.now(), True)
        repository.save(board)
        message = capture()
        message.update(stage=league.title.lower() + "_lines", received_at=clock.now().isoformat())
        message["records"] = [
            row("CL", L3=league.title),
            row("MG", SY="cmx"),
            row("MA", SY="ef"),
            row("PA", OI="source-fixture", NA="Away", N2="Home", BC=event.start.strftime("%Y%m%d%H%M%S")),
            row("MA", SY="eo", NA="Money", MA="960"),
            row("PA", OI="source-fixture", FI="source-fixture", ID="away", OD="7/5"),
            row("PA", OI="source-fixture", FI="source-fixture", ID="home", OD="4/7"),
        ]
        return board, {"version": 1, "region": "nj", "league": key, "messages": [message]}

    app = create_app(settings, repository, clock)
    with TestClient(app) as client:
        yield repository, settings, client, seed, app


def post(client, payload, key="collector-only"):
    return client.post("/v1/ingest/bet365", json=payload, headers={"X-Collector-Key": key})


@pytest.mark.parametrize("league", ACTIVE)
def test_all_five_leagues_stream_into_shared_redis_and_public_api(stream, league):
    repo, _, client, seed, _ = stream
    board, payload = seed(league)
    assert post(client, payload).json()["accepted_selections"] == 2
    response = client.get(
        f"/v1/sports/{league}/odds?markets=h2h&oddsFormat=american", headers={"X-API-Key": "product-key"}
    )
    assert response.status_code == 200
    events = response.json()
    assert len(events) == 1 and events[0]["id"] == board.events[0].id
    books = {book["key"]: book for book in events[0]["bookmakers"]}
    assert len(books) == 2 and "bet365" in books
    assert {o["price"] for o in books["bet365"]["markets"][0]["outcomes"]} == {140, -175}
    assert len(repo.events(league)) == 1
    status = client.get("/v1/status", headers={"X-API-Key": "product-key"}).json()
    assert status["bet365"]["jobs"][league]["accepted_selections"] == 2
    assert repo.client.ttl(repo.key("event:" + board.events[0].id)) > 0


@pytest.mark.parametrize("key", ["", "product-key", "wrong"])
def test_read_credentials_cannot_write_odds(stream, key):
    repo, _, client, seed, _ = stream
    board, payload = seed()
    assert post(client, payload, key).status_code == 401
    assert len(repo.quotes(board.league.key)) == 2


@pytest.mark.parametrize("mutation", ["source", "timezone", "future", "fields", "league", "malformed"])
def test_invalid_capture_is_rejected_before_writes(stream, mutation, clock):
    repo, _, client, seed, _ = stream
    board, payload = seed()
    message = payload["messages"][0]
    if mutation == "source":
        message["source_url"] = "https://attacker.example/contentdata/markets"
    elif mutation == "timezone":
        message["received_at"] = "2026-11-09T00:00:00"
    elif mutation == "future":
        message["received_at"] = (clock.now() + timedelta(seconds=6)).isoformat()
    elif mutation == "fields":
        message["records"][0]["fields"]["token"] = "x" * 16385
    elif mutation == "league":
        payload["league"] = "mlb_baseball"
    else:
        message["records"][5]["fields"]["OD"] = "invalid"
    assert post(client, payload).status_code == 422
    assert len(repo.quotes(board.league.key)) == 2


def test_request_size_is_bounded(stream):
    _, _, client, _, _ = stream
    response = client.post(
        "/v1/ingest/bet365",
        content=b" " * (MAX_CAPTURE_BYTES + 1),
        headers={"X-Collector-Key": "collector-only"},
    )
    assert response.status_code == 413


def test_retries_keep_original_capture_and_other_providers_and_never_resurrect_events(stream, clock):
    repo, _, client, seed, _ = stream
    board, payload = seed()
    original = repo.quotes(board.league.key)
    assert post(client, payload).json()["accepted_selections"] == 2
    assert post(client, payload).json()["accepted_selections"] == 2
    assert len(repo.quotes(board.league.key)) == 4
    assert [r for r in repo.quotes(board.league.key) if r["book_key"] != "bet365"] == original
    clock.value += 151
    assert post(client, payload).json()["accepted_selections"] == 0
    captured = [r["quote"] for r in repo.quotes(board.league.key) if r["book_key"] == "bet365"]
    assert all(q.collected_at == clock.origin for q in captured)
    assert all(q.expires_at == clock.origin + timedelta(seconds=150) for q in captured)
    repo.client.delete(repo.key("event:" + board.events[0].id))
    assert post(client, payload).json()["accepted_selections"] == 0
    assert repo.event(board.events[0].id) is None


def test_fresh_update_wins_but_late_older_capture_cannot_rollback_price(stream, clock):
    repo, _, client, seed, _ = stream
    board, old = seed()
    assert post(client, old).status_code == 200
    clock.value += 5
    new = deepcopy(old)
    new["messages"][0]["received_at"] = clock.now().isoformat()
    new["messages"][0]["records"][5]["fields"]["OD"] = "2/1"
    assert post(client, new).status_code == 200
    assert post(client, old).status_code == 200
    away = [
        r["quote"]
        for r in repo.quotes(board.league.key)
        if r["book_key"] == "bet365" and r["quote"].name == "Away"
    ]
    assert away[0].price == 200
    assert away[0].collected_at == clock.now()


def test_spreads_and_totals_join_the_same_canonical_fixture(stream):
    _, _, client, seed, _ = stream
    board, payload = seed()
    payload["messages"][0]["records"].extend(
        [
            row("MA", SY="eo", NA="Spread"),
            row("PA", OI="source-fixture", FI="spread", ID="away-spread", HA="-3.5", OD="10/11"),
            row("PA", OI="source-fixture", FI="spread", ID="home-spread", HA="3.5", OD="10/11"),
            row("MA", SY="eo", NA="Total"),
            row("PA", OI="source-fixture", FI="total", ID="under", HA="219.5", HD="U 219.5", OD="10/11"),
            row("PA", OI="source-fixture", FI="total", ID="over", HA="219.5", HD="O 219.5", OD="10/11"),
        ]
    )
    result = post(client, payload)
    assert result.status_code == 200 and result.json()["accepted_selections"] == 6
    data = client.get(
        f"/v1/events/{board.events[0].id}/odds?markets=h2h,spreads,totals&bookmakers=bet365",
        headers={"X-API-Key": "product-key"},
    ).json()
    markets = {m["key"]: m["outcomes"] for m in data["bookmakers"][0]["markets"]}
    assert {o["name"]: o["point"] for o in markets["spreads"]} == {"Away": -3.5, "Home": 3.5}
    assert {o["name"]: o["point"] for o in markets["totals"]} == {"Over": 219.5, "Under": 219.5}


def test_explicit_props_stream_with_canonical_player_identity_and_no_inherited_links(stream, clock):
    repo, _, client, seed, _ = stream
    board, payload = seed()
    template = board.quotes[0]
    canonical_props = tuple(
        replace(
            template,
            market="player_points",
            player_id="canonical-player",
            description="Player A",
            point=Decimal("19.5"),
            name=side,
            deep_link="https://other-book.example/bet",
            app_link="otherbook://bet",
        )
        for side in ("Over", "Under")
    )
    repo.save(replace(board, kind="props", quotes=canonical_props))
    message = capture()
    message["received_at"] = clock.now().isoformat()
    message["records"][3]["fields"].update(
        FI="source-fixture", NA="Away @ Home", BC=board.events[0].start.strftime("%Y%m%d%H%M%S")
    )
    payload["messages"].append(message)
    result = post(client, payload)
    assert result.status_code == 200 and result.json()["accepted_selections"] == 4
    quotes = [
        r["quote"]
        for r in repo.quotes(board.league.key)
        if r["book_key"] == "bet365" and r["quote"].player_id
    ]
    assert len(quotes) == 2 and {q.player_id for q in quotes} == {"canonical-player"}
    assert all(q.deep_link is None and q.app_link is None for q in quotes)
    data = client.get(
        f"/v1/events/{board.events[0].id}/props?bookmakers=bet365", headers={"X-API-Key": "product-key"}
    ).json()
    assert data["bookmakers"][0]["markets"][0]["key"] == "player_points"


@pytest.mark.parametrize("change", ["deleted", "final", "rescheduled"])
def test_capture_prepared_before_catalog_change_cannot_restore_old_lifecycle(stream, clock, change):
    from odds_api.infrastructure.bet365 import boards
    from scripts.organize_bet365_league_dump import organize_leagues

    repo, _, _, seed, _ = stream
    board, payload = seed()
    snapshots, _ = boards(organize_leagues(payload["messages"]), repo, clock.now())
    event = board.events[0]
    key = repo.key("event:" + event.id)
    if change == "deleted":
        repo.client.delete(key)
    elif change == "final":
        repo.save(replace(board, events=(replace(event, status="final"),)))
    else:
        repo.save(replace(board, events=(replace(event, start=event.start + timedelta(hours=2)),)))
    original = repo.client.get(key)
    for snapshot in snapshots:
        repo.save(snapshot)
    if change in {"deleted", "final"}:
        assert repo.client.get(key) == original
    else:
        assert repo.event(event.id)["start"] == event.start + timedelta(hours=2)
        assert (
            repo.client.zscore(repo.key("events:" + board.league.key), event.id)
            == (event.start + timedelta(hours=2)).timestamp()
        )


def test_disabled_ingestion_and_prepared_read_filter(stream):
    repo, settings, client, seed, _ = stream
    board, payload = seed()
    assert post(client, payload).status_code == 200
    with TestClient(create_app(settings.model_copy(update={"bet365_enabled": False}), repo)) as disabled:
        assert post(disabled, payload).status_code == 503
        data = disabled.get(
            f"/v1/sports/{board.league.key}/odds", headers={"X-API-Key": "product-key"}
        ).json()
        assert all(book["key"] != "bet365" for event in data for book in event["bookmakers"])


def test_direct_and_api_feed_bet365_prices_merge_by_actual_observation_time(stream, clock):
    repo, _, client, seed, _ = stream
    board, payload = seed()
    api_book = Sportsbook("365", "Bet365")
    upstream = replace(
        board,
        books=(api_book,),
        quotes=tuple(replace(q, book_id=api_book.id, source_updated_at=clock.now()) for q in board.quotes),
    )
    repo.save(upstream)
    clock.value = 10
    payload["messages"][0]["received_at"] = clock.now().isoformat()
    assert post(client, payload).status_code == 200

    def prices():
        data = client.get(
            f"/v1/events/{board.events[0].id}/odds?bookmakers=bet365&oddsFormat=american",
            headers={"X-API-Key": "product-key"},
        ).json()
        assert len(data["bookmakers"]) == 1
        return {o["price"] for o in data["bookmakers"][0]["markets"][0]["outcomes"]}

    assert prices() == {140, -175}
    clock.value = 20
    repo.save(
        replace(
            upstream,
            quotes=tuple(
                replace(
                    q,
                    price=120,
                    collected_at=clock.now(),
                    source_updated_at=clock.now() - timedelta(seconds=15),
                )
                for q in upstream.quotes
            ),
        )
    )
    assert prices() == {140, -175}
    clock.value = 30
    repo.save(
        replace(
            upstream,
            quotes=tuple(
                replace(q, price=130, collected_at=clock.now(), source_updated_at=clock.now())
                for q in upstream.quotes
            ),
        )
    )
    assert prices() == {130}


def test_collector_defaults_to_exactly_five_leagues_and_seasonal_overrides():
    settings = Settings(_env_file=None)
    assert {key for _, key in jobs(settings)} == set(ACTIVE)
    assert len(jobs(Settings(_env_file=None, collection_excluded_leagues=set()))) == 6
    assert {
        key
        for _, key in jobs(
            Settings(_env_file=None, leagues_json='{"nba_basketball":{"title":"NBA","route":"nba"}}')
        )
    } == {"nba_basketball"}


@pytest.mark.parametrize(
    "url",
    ["http://remote.example", "https://user:secret@remote.example", "https://remote.example/?key=secret"],
)
def test_sender_requires_https_without_embedded_credentials(url):
    with pytest.raises(ValueError):
        destination(Settings(_env_file=None, bet365_server_url=url, bet365_ingest_key="secret"))


def test_browser_subprocess_never_receives_ingestion_or_provider_keys(monkeypatch):
    for key in ("BET365_INGEST_KEY", "REDIS_URL", "API_KEYS", "PROPLINE_API_KEY", "UNABATED_API_KEY"):
        monkeypatch.setenv(key, "secret")
        assert key not in browser_environment()


async def test_sender_retries_outage_with_identical_payload_and_authenticates_end_to_end(stream):
    repo, _, _, seed, app = stream
    board, payload = seed()
    attempts = []

    async def handle(request):
        attempts.append(request.content)
        assert request.headers["X-Collector-Key"] == "collector-only"
        if len(attempts) == 1:
            return httpx.Response(503)
        return await httpx.ASGITransport(app=app).handle_async_request(request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), headers={"X-Collector-Key": "collector-only"}
    ) as sender:
        import json

        result = await transmit(
            sender, "https://server.example/v1/ingest/bet365", json.dumps(payload), sleep=AsyncMock()
        )
    assert result["accepted_selections"] == 2 and attempts[0] == attempts[1]
    assert len(repo.quotes(board.league.key)) == 4


async def test_sender_does_not_retry_permanent_authentication_failure():
    transport = httpx.MockTransport(lambda request: httpx.Response(401))
    sleep = AsyncMock()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await transmit(client, "https://server.example/v1/ingest/bet365", "{}", sleep=sleep)
    sleep.assert_not_called()
