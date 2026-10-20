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
    route = DEFAULT_LEAGUES[sport]["route"]
    market_type = "straight" if kind == "moneyline" else "props"
    prefix = f"/market/{route}/{market_type}"
    raw["leagues"][0]["name"] = route.upper()
    raw["bets"].append({"id": 1234, "name": "Moneyline"})
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
    requested = []

    def handler(request):
        assert request.method == "GET"
        assert request.url.scheme == "https"
        assert request.url.host == "data.unabated.com"
        assert request.headers["X-Api-Key"] == "offline-provider-fixture"
        assert request.headers["Accept"] == "application/json"
        requested.append(request.url.path)
        if request.url.path == prefix + "/odds":
            expected = [("betTypeId", "77"), ("betTypeId", "1234")] if kind == "moneyline" else []
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
