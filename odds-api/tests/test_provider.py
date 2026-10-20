import httpx
import pytest

from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.provider import ProviderError, UnabatedClient, retry_after
from odds_api.infrastructure.rate_limit import RateLimiter


def client_for(clock, handler, **kwargs):
    settings = Settings(
        _env_file=None,
        unabated_api_key="fixture-secret",
        rate_min_interval=0.1,
        odds_min_interval=5,
        **kwargs,
    )
    http = httpx.AsyncClient(base_url="https://example.test", transport=httpx.MockTransport(handler))
    return UnabatedClient(settings, clock, RateLimiter(clock, 0.1, 5), http=http)


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authentication_failed"),
        (403, "coverage_denied"),
        (404, "unsupported_request"),
        (400, "unsupported_request"),
    ],
)
async def test_nonretryable_http_errors(clock, status, code):
    client = client_for(clock, lambda _: httpx.Response(status))
    with pytest.raises(ProviderError, match=code):
        await client.request("/league")
    assert client.metrics["requests"] == 1
    await client.close()


async def test_provider_errors_in_successful_http(clock):
    client = client_for(
        clock, lambda _: httpx.Response(200, json={"success": False, "messages": ["fixture-secret"]})
    )
    with pytest.raises(ProviderError, match="provider_operation_failed") as error:
        await client.request("/league")
    assert "fixture-secret" not in str(error.value)
    assert error.value.provider_path == "/league"
    assert error.value.provider_http_status == 200
    assert error.value.failure_reason == "upstream_unsuccessful_response"
    assert client.metrics["operation_failures"] == 1
    assert client.metrics["requests"] == 1
    await client.close()


async def test_retry_after_shared_with_discovery_and_retries(clock):
    starts = []

    def handler(request):
        starts.append(clock.monotonic())
        return (
            httpx.Response(429, headers={"Retry-After": "12"})
            if len(starts) == 1
            else httpx.Response(200, json={"success": True, "data": []})
        )

    client = client_for(clock, handler)
    await client.request("/market/nba/straight/odds")
    await client.request("/league")
    assert starts[1] >= 12
    assert starts[2] >= starts[1] + 0.1
    assert client.metrics["rate_limits"] == 1
    await client.close()


async def test_bounded_retries(clock):
    client = client_for(clock, lambda _: httpx.Response(503), max_attempts=3)
    with pytest.raises(ProviderError, match="provider_unavailable"):
        await client.request("/market/nba/props/odds")
    assert client.metrics["requests"] == 3
    await client.close()


async def test_timeout_and_invalid_json_are_bounded(clock):
    def handler(request):
        raise httpx.ReadTimeout("sensitive upstream context", request=request)

    client = client_for(clock, handler, max_attempts=2)
    with pytest.raises(ProviderError, match="transport"):
        await client.request("/league")
    assert client.metrics["requests"] == 2
    await client.close()


@pytest.mark.parametrize("league_name", ["nba", "NBA"])
async def test_discovered_ids_are_used_for_moneylines(raw, clock, league_name):
    raw["leagues"][0]["name"] = league_name
    requests = []
    routes = {
        "/league": raw["leagues"],
        "/bettype": raw["bets"],
        "/period-type/nba": raw["periods"],
        "/market-type": [{"id": 400, "name": "straight"}, {"id": 500, "name": "props"}],
        "/market/nba/straight/sources": raw["sources"],
        "/team/nba": raw["teams"],
    }

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/odds"):
            assert request.url.params["betTypeId"] == "77"
            return httpx.Response(200, json=raw["moneyline"])
        return httpx.Response(200, json={"success": True, "data": routes[request.url.path]})

    client = client_for(clock, handler)
    board = await client.fetch("basketball_nba", "moneyline")
    assert board.league.source_id == "42"
    assert board.league.route == "nba"
    assert len(board.quotes) == 2
    assert len(requests) == 7
    await client.close()


async def test_messages_preserve_partial_scope(clock):
    client = client_for(
        clock,
        lambda _: httpx.Response(
            200, json={"success": True, "data": {"odds": {}}, "messages": ["partial board"]}
        ),
    )
    _, complete = await client.request("/market/nba/props/odds")
    assert not complete
    await client.close()


async def test_pagination_cannot_be_misread_as_complete(clock):
    client = client_for(
        clock,
        lambda _: httpx.Response(200, json={"success": True, "data": [], "pagination": {"totalPages": 2}}),
    )
    with pytest.raises(ProviderError, match="incomplete_pagination"):
        await client.request("/league")
    await client.close()


def test_http_date_retry_after(clock):
    assert retry_after("Mon, 19 Oct 2026 00:00:10 GMT", clock.now()) == 10
    assert retry_after("unparseable", clock.now()) == 0


async def test_provider_cursor_cannot_be_misread_as_complete(clock):
    client = client_for(
        clock,
        lambda _: httpx.Response(
            200, json={"success": True, "data": [], "pagination": {"nextCursor": "next-page"}}
        ),
    )
    with pytest.raises(ProviderError, match="incomplete_pagination"):
        await client.request("/league")
    await client.close()


@pytest.mark.parametrize("kind,market_type", [("moneyline", "straight"), ("props", "props")])
@pytest.mark.parametrize("disabled", [False, True])
async def test_discovered_display_names_map_to_routes(raw, clock, kind, market_type, disabled):
    import json
    from pathlib import Path

    definitions = json.loads((Path(__file__).parent / "fixtures/unabated_market_types.json").read_text())
    # Change the IDs to prove they are discovered, never inferred from names.
    for definition in definitions:
        definition["id"] += 400
    if disabled:
        raw["sources"][0]["disabledMarketTypeIds"] = [401 if kind == "moneyline" else 403]
    prefix = "/market/nba/" + market_type
    routes = {
        "/league": raw["leagues"],
        "/bettype": raw["bets"],
        "/period-type/nba": raw["periods"],
        "/market-type": definitions,
        prefix + "/sources": raw["sources"],
        "/team/nba": raw["teams"],
        "/player/nba": raw["people"],
    }

    def handler(request):
        if request.url.path == prefix + "/odds":
            return httpx.Response(200, json=raw[kind])
        return httpx.Response(200, json={"success": True, "data": routes[request.url.path]})

    client = client_for(clock, handler)
    try:
        board = await client.fetch("basketball_nba", kind)
        assert board.complete and board.quotes
        assert {quote.state.value for quote in board.quotes} == ({"suspended"} if disabled else {"available"})
    finally:
        await client.close()


def discovery_routes(raw):
    return {
        "/league": raw["leagues"],
        "/bettype": raw["bets"],
        "/period-type/nba": raw["periods"],
        "/market-type": [{"id": 1, "name": "Straight"}, {"id": 3, "name": "Player Props"}],
        "/market/nba/props/sources": raw["sources"],
        "/team/nba": raw["teams"],
        "/player/nba": raw["people"],
    }


@pytest.mark.parametrize(
    "path", ["/event/nba/upcoming", "/market/nba/futures/odds", "/season/nba", "/market/nba/straight/people"]
)
async def test_unnecessary_provider_endpoints_are_blocked_before_http(clock, path):
    def handler(_):
        pytest.fail("An unnecessary endpoint reached the network")

    client = client_for(clock, handler)
    try:
        with pytest.raises(ProviderError, match="unsupported_provider_endpoint"):
            await client.request(path)
        assert client.metrics["requests"] == 0
    finally:
        await client.close()


async def test_only_required_catalogs_and_odds_are_called_and_metadata_is_cached(raw, clock):
    requested = []
    routes = discovery_routes(raw)

    def handler(request):
        path = request.url.path
        requested.append(path)
        if path == "/market/nba/props/odds":
            return httpx.Response(200, json=raw["props"])
        assert path in routes, "Unexpected endpoint: " + path
        return httpx.Response(200, json={"success": True, "data": routes[path]})

    client = client_for(clock, handler)
    try:
        for _ in range(2):
            board = await client.fetch("basketball_nba", "props")
            assert board.complete and board.quotes
        assert requested.count("/market/nba/props/odds") == 2
        assert all(requested.count(path) == 1 for path in routes)
        assert len(requested) == len(routes) + 2
    finally:
        await client.close()


@pytest.mark.parametrize("status", [401, 403, 400])
@pytest.mark.parametrize("forbidden_path", ["/market/nba/props/odds", "/market/nba/props/sources"])
async def test_denials_do_not_trigger_cross_market_or_event_requests(raw, clock, status, forbidden_path):
    requested = []
    routes = discovery_routes(raw)

    def handler(request):
        path = request.url.path
        requested.append(path)
        if path == forbidden_path:
            return httpx.Response(status)
        if path == "/market/nba/props/odds":
            return httpx.Response(200, json=raw["props"])
        assert path in routes
        return httpx.Response(200, json={"success": True, "data": routes[path]})

    client = client_for(clock, handler)
    try:
        with pytest.raises(ProviderError) as error:
            await client.fetch("basketball_nba", "props")
        assert error.value.provider_path == forbidden_path
        assert error.value.provider_http_status == status
        assert "/market/nba/straight/sources" not in requested
        assert not any(path.startswith("/event/") for path in requested)
        assert "/player/nba" not in requested
    finally:
        await client.close()


async def test_unsuccessful_odds_never_trigger_identity_lookup_or_unrelated_fallback(raw, clock):
    requested = []
    routes = discovery_routes(raw)

    def handler(request):
        path = request.url.path
        requested.append(path)
        if path == "/market/nba/props/odds":
            return httpx.Response(200, json={"success": False, "messages": ["fixture-secret"]})
        return httpx.Response(200, json={"success": True, "data": routes[path]})

    client = client_for(clock, handler)
    try:
        with pytest.raises(ProviderError, match="provider_operation_failed"):
            await client.fetch("basketball_nba", "props")
        assert set(requested) == {
            "/league",
            "/bettype",
            "/period-type/nba",
            "/market-type",
            "/market/nba/props/odds",
        }
    finally:
        await client.close()
