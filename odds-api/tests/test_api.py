import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from odds_api.http.app import create_app
from odds_api.infrastructure.config import Settings


@pytest.fixture
def client(repo, board, clock):
    repo.save(board())
    repo.save(board("props"))
    settings = Settings(
        _env_file=None, api_keys="consumer-fixture-key", unabated_api_key="provider-secret", collected_ttl=90
    )
    with TestClient(create_app(settings, repo, clock)) as client:
        yield client


def test_health_and_authentication(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").status_code == 200
    assert client.get("/v1/sports").status_code == 401
    assert client.get("/v1/status").status_code == 401
    assert client.get("/v1/sports", headers={"X-API-Key": "consumer-fixture-key"}).status_code == 200
    assert len(client.get("/v1/sports?apiKey=consumer-fixture-key").json()) == 5


def test_moneyline_compatibility_fixture(client, board):
    expected = json.loads((Path(__file__).parent / "fixtures/consumer_moneyline.json").read_text())
    expected[0]["id"] = board().events[0].id
    response = client.get(
        "/v1/sports/nba_basketball/odds?oddsFormat=american", headers={"X-API-Key": "consumer-fixture-key"}
    )
    assert response.status_code == 200
    assert response.json() == expected
    assert "X-Odds-Observed-At" in response.headers
    assert response.headers["cache-control"] == "no-store"


def test_event_props_and_null_last_update(client, board):
    eid = board().events[0].id
    response = client.get(
        f"/v1/events/{eid}/odds?markets=player_points_alternate",
        headers={"X-API-Key": "consumer-fixture-key"},
    )
    assert response.status_code == 200
    market = response.json()["bookmakers"][0]["markets"][0]
    assert market["last_update"] is None
    assert market["outcomes"][0]["point"] == 30.5


def test_player_points_expire_during_failed_refresh_without_erasing_stored_quotes(client, repo, board, clock):
    eid = board().events[0].id
    url = f"/v1/events/{eid}/odds?markets=player_points&oddsFormat=american"
    headers = {"X-API-Key": "consumer-fixture-key"}
    fresh = client.get(url, headers=headers)
    assert fresh.status_code == 200
    assert fresh.json()["bookmakers"][0]["markets"][0]["key"] == "player_points"
    assert len(fresh.json()["bookmakers"][0]["markets"][0]["outcomes"]) == 2
    clock.value = 90
    assert client.get(url, headers=headers).json()["bookmakers"]
    clock.value = 91
    repo.failure("nba_basketball", "props", "provider_operation_failed")
    cached = client.get(url, headers=headers)
    assert cached.status_code == 200 and cached.json()["bookmakers"]
    assert cached.json()["freshness"]["status"] == "stale"
    assert cached.json()["freshness"]["stale_outcomes"] == 2
    for outcome in cached.json()["bookmakers"][0]["markets"][0]["outcomes"]:
        assert outcome["freshness"]["actionable"] is False
        assert outcome["freshness"]["age_seconds"] == 91
    expired = client.get(url + "&freshOnly=true", headers=headers)
    assert expired.status_code == 200 and expired.json()["bookmakers"] == []
    assert expired.headers["X-Odds-Collected-TTL"] == "90.0"
    assert any(row["quote"].market == "player_points" for row in repo.quotes("nba_basketball"))
    repo.save(board("props"))
    assert client.get(url, headers=headers).json()["bookmakers"]


def test_all_props_route_includes_alternates_and_rejects_moneylines(client, board):
    eid = board().events[0].id
    headers = {"X-API-Key": "consumer-fixture-key"}
    path = f"/v1/events/{eid}/props"
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    assert {m["key"] for b in response.json()["bookmakers"] for m in b["markets"]} == {
        "player_points",
        "player_points_alternate",
    }
    alias = client.get(path.replace("/props", "/odds?markets=all_props"), headers=headers)
    assert alias.json() == response.json()
    assert response.json()["freshness"]["status"] == "fresh"
    assert response.headers["X-Odds-Data-Status"] == "fresh"
    assert client.get(path).status_code == 401
    assert client.get(path + "?markets=h2h", headers=headers).status_code == 422
    assert client.get(path + "?freshOnly=bogus", headers=headers).status_code == 422


@pytest.mark.parametrize(
    "sport,base", [("nba_basketball", "player_points"), ("nfl_football", "player_pass_yds")]
)
def test_all_props_for_nba_and_nfl_include_distinct_periods_and_cached_flags(
    client, repo, board, clock, sport, base
):
    snapshot = board("props")
    event = replace(snapshot.events[0], league_key=sport)
    league = replace(snapshot.league, key=sport)
    if sport == "nfl_football":
        league = replace(league, title="NFL", route="nfl", source_id="43")
    quotes = tuple(
        replace(q, event_id=event.id, market=q.market.replace("player_points", base)) for q in snapshot.quotes
    )
    quarter = replace(quotes[0], market=base + "_q1", period="q1")
    repo.save(replace(snapshot, league=league, events=(event,), quotes=(*quotes, quarter)))
    clock.value = 91
    headers = {"X-API-Key": "consumer-fixture-key"}
    path = f"/v1/events/{event.id}/props"
    response = client.get(path + "?oddsFormat=american", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert {m["key"] for b in payload["bookmakers"] for m in b["markets"]} == {
        base,
        base + "_alternate",
        base + "_q1",
    }
    assert payload["freshness"]["stale_outcomes"] == 4
    assert response.headers["X-Odds-Data-Status"] == "stale"
    assert all(
        o["freshness"]["actionable"] is False
        for b in payload["bookmakers"]
        for m in b["markets"]
        for o in m["outcomes"]
    )
    assert client.get(path + "?freshOnly=true", headers=headers).json()["bookmakers"] == []


@pytest.mark.parametrize(
    "url,status",
    [
        ("/v1/sports/unknown/events", 404),
        ("/v1/events/unknown/odds", 404),
        ("/v1/sports/nba_basketball/odds?markets=bogus", 422),
        ("/v1/sports/nba_basketball/odds?bookmakers=bogus", 422),
        ("/v1/sports/nba_basketball/odds?oddsFormat=fractional", 422),
        ("/v1/sports/nba_basketball/odds?regions=us", 422),
        ("/v1/sports/nba_basketball/events?commenceTimeFrom=2026-10-20T00:00:00", 422),
    ],
)
def test_documented_errors(client, url, status):
    assert client.get(url, headers={"X-API-Key": "consumer-fixture-key"}).status_code == status


def test_docs_and_openapi_do_not_contain_provider_credentials(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert "OddsResponse" in spec["components"]["schemas"]
    assert spec["paths"]["/v1/sports/{sport}/odds"]["get"]["security"]
    assert "provider-secret" not in response.text
    assert client.get("/docs").status_code == 200
    assert "/v1/events/{event_id}/props" in spec["paths"]
    assert all(not path.startswith("/v4") for path in spec["paths"])
    assert "sport" not in {
        p["name"] for p in spec["paths"]["/v1/events/{event_id}/props"]["get"]["parameters"]
    }


def test_v1_league_keys_and_removed_routes(client):
    headers = {"X-API-Key": "consumer-fixture-key"}
    leagues = client.get("/v1/sports", headers=headers).json()
    assert {league["key"] for league in leagues} == {
        "nba_basketball",
        "nfl_football",
        "mlb_baseball",
        "nhl_hockey",
        "ncaaf_football",
    }
    assert {league["group"] for league in leagues} == {"Basketball", "Football", "Baseball", "Hockey"}
    for old in ("/v4/sports", "/v1/sports/basketball_nba/events", "/status"):
        assert client.get(old, headers=headers).status_code == 404


def test_internal_database_error_is_safe_service_unavailable(client, repo, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def fail():
        raise OperationalError("sensitive-query", {}, Exception("database-secret"))

    monkeypatch.setattr(repo, "leagues", fail)
    response = client.get("/v1/sports", headers={"X-API-Key": "consumer-fixture-key"})
    assert response.status_code == 503
    assert "database-secret" not in response.text
