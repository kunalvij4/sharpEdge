"""Verify outgoing requests against the reviewed Unabated reference contract."""

import json
from pathlib import Path

import httpx
import pytest

from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings
from odds_api.infrastructure.provider import UnabatedClient
from odds_api.infrastructure.rate_limit import RateLimiter


@pytest.mark.parametrize("sport", DEFAULT_LEAGUES)
@pytest.mark.parametrize("kind", ["moneyline", "props"])
async def test_real_client_builds_documented_requests(raw, clock, monkeypatch, sport, kind):
    # College Football is CFB in the live discovery contract. Keep this
    # expectation independent of application defaults to catch route regressions.
    route = "cfb" if sport == "ncaaf_football" else DEFAULT_LEAGUES[sport]["route"]
    market_type = "straight" if kind == "moneyline" else "props"
    prefix = f"/market/{route}/{market_type}"
    raw["leagues"][0]["name"] = route.upper()
    raw["bets"].append({"id": 1234, "name": "Moneyline"})
    raw["bets"].append({"id": 5678, "name": "Spread"})
    definitions = json.loads((Path(__file__).parent / "fixtures/unabated_market_types.json").read_text())
    discovery = {
        "/league": raw["leagues"],
        "/bettype": raw["bets"],
        f"/period-type/{route}": raw["periods"],
        "/market-type": definitions,
        prefix + "/sources": raw["sources"],
        f"/team/{route}": raw["teams"],
    }
    if kind == "props":
        discovery[f"/player/{route}"] = raw["people"]
        if route == "cfb":
            discovery["/event/cfb/upcoming"] = raw["events"]
    requested = []

    def handler(request):
        assert request.method == "GET"
        assert request.url.scheme == "https"
        assert request.url.host == "data.unabated.com"
        assert request.headers["X-Api-Key"] == "offline-provider-fixture"
        assert request.headers["Accept"] == "application/json"
        requested.append(request.url.path)
        if request.url.path == prefix + "/odds":
            expected = (
                [("betTypeId", "77"), ("betTypeId", "1234"), ("betTypeId", "5678")]
                if kind == "moneyline"
                else []
            )
            assert request.url.params.multi_items() == expected
            return httpx.Response(200, json=raw[kind])
        assert not request.url.params
        return httpx.Response(200, json={"success": True, "data": discovery[request.url.path]})

    # Exercise our real HTTP-client constructor, including its base URL and headers.
    # Only replace the network transport; no production configuration is loaded.
    real_async_client = httpx.AsyncClient

    def offline_client(**kwargs):
        return real_async_client(**kwargs, transport=httpx.MockTransport(handler), trust_env=False)

    monkeypatch.setattr("odds_api.infrastructure.provider.httpx.AsyncClient", offline_client)
    settings = Settings(
        _env_file=None,
        unabated_api_base_url="https://data.unabated.com",
        unabated_api_key="offline-provider-fixture",
        leagues_json=json.dumps(DEFAULT_LEAGUES),
    )
    client = UnabatedClient(settings, clock, RateLimiter(clock, 0.1, 5))
    try:
        board = await client.fetch(sport, kind)
        assert board.league.key == sport
        assert board.complete and board.quotes
        assert set(requested) == {*discovery, prefix + "/odds"}
        assert len(requested) == len(discovery) + 1
    finally:
        await client.close()


@pytest.mark.parametrize("catalog_mode", ["available", "unavailable", "malformed_row"])
async def test_cfb_catalog_resolves_missing_context_without_becoming_mandatory(raw, clock, catalog_mode):
    import copy

    raw["leagues"][0]["name"] = "CFB"
    group = raw["props"]["data"]["odds"]["arbitrary"]["periodTypes"]["arbitrary"]["pregame"]["ignored"]
    if catalog_mode != "unavailable":
        group.pop("eventTeams", None)
        group.pop("eventStart", None)
        group.pop("statusId", None)
    catalog = copy.deepcopy(raw["events"])
    for team in catalog[0]["eventTeams"]:
        team["name"] = "AWY" if team["sideIndex"] == 0 else "HME"
    if catalog_mode == "malformed_row":
        catalog.extend([{"eventId": 123, "leagueId": 42}, {"eventId": 999, "leagueId": 100}])
    definitions = json.loads((Path(__file__).parent / "fixtures/unabated_market_types.json").read_text())
    payloads = {
        "/league": raw["leagues"],
        "/bettype": raw["bets"],
        "/market-type": definitions,
        "/period-type/cfb": raw["periods"],
        "/team/cfb": raw["teams"],
        "/player/cfb": raw["people"],
        "/market/cfb/props/sources": raw["sources"],
        "/event/cfb/upcoming": catalog,
    }
    paths = []

    def handler(request):
        path = request.url.path
        paths.append(path)
        if path == "/market/cfb/props/odds":
            return httpx.Response(200, json=raw["props"])
        if path == "/event/cfb/upcoming" and catalog_mode == "unavailable":
            return httpx.Response(200, json={"success": False})
        return httpx.Response(200, json={"success": True, "data": payloads[path]})

    settings = Settings(_env_file=None)
    http = httpx.AsyncClient(base_url="https://data.unabated.com", transport=httpx.MockTransport(handler))
    client = UnabatedClient(settings, clock, RateLimiter(clock, 0, 0), http)
    try:
        board = await client.fetch("ncaaf_football", "props")
        assert len(board.quotes) == 3
        assert all(q.state.value == "available" for q in board.quotes)
        assert board.events[0].home == "Home Team" and board.events[0].away == "Away Team"
        if catalog_mode == "available":
            assert board.complete
            await client.fetch("ncaaf_football", "props")
            assert paths.count("/event/cfb/upcoming") == 1
        elif catalog_mode == "unavailable":
            assert board.complete and client.metrics["event_catalog_failures"] == 1
        else:
            assert not board.complete
            assert "unresolved_catalog_event:123" in board.warnings
            assert "foreign_catalog_event:999" in board.warnings
    finally:
        await client.close()
