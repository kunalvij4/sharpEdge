import copy
import json
from datetime import timedelta

import httpx
import pytest

from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.propline import (
    SPORT_KEYS,
    ProplineClient,
    ProplineError,
    request_budget,
    summarize,
)
from scripts.probe_propline import probe


@pytest.fixture
def propline_raw(clock):
    return [
        {
            "id": "event-123",
            "sport_key": "basketball_nba",
            "home_team": "Home Team",
            "away_team": "Away Team",
            "commence_time": (clock.now() + timedelta(days=1)).isoformat(),
            "live": False,
            "completed": False,
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "book_event_id": "native-123",
                    "markets": [
                        {
                            "key": "h2h",
                            "last_update": clock.now().isoformat(),
                            "outcomes": [
                                {"name": "Home Team", "side": "home", "price": -110, "outcome_id": "1"},
                                {"name": "Away Team", "side": "away", "price": 100, "outcome_id": "2"},
                            ],
                        },
                        {
                            "key": "spreads",
                            "last_update": clock.now().isoformat(),
                            "outcomes": [
                                {"name": "Home Team", "side": "home", "point": -1.5, "price": -105},
                                {"name": "Away Team", "side": "away", "point": 1.5, "price": -115},
                            ],
                        },
                        {
                            "key": "player_points",
                            "last_update": clock.now().isoformat(),
                            "outcomes": [
                                {
                                    "name": "Over",
                                    "description": "Example Player",
                                    "point": 25.5,
                                    "price": -110,
                                    "player_id": "nba:42",
                                    "last_seen_at": clock.now().isoformat(),
                                },
                                {
                                    "name": "Under",
                                    "description": "Example Player",
                                    "point": 25.5,
                                    "price": -110,
                                    "player_id": "nba:42",
                                    "last_seen_at": clock.now().isoformat(),
                                },
                            ],
                        },
                    ],
                }
            ],
        }
    ]


def settings():
    return Settings(_env_file=None, propline_api_key="offline-propline-key")


async def test_bulk_probe_filters_requested_books_with_one_call_per_league(tmp_path, clock, propline_raw):
    requested = []

    def handler(request):
        assert request.method == "GET" and request.url.host == "api.prop-line.com"
        assert request.headers["X-API-Key"] == "offline-propline-key"
        assert "apiKey" not in request.url.params
        assert set(request.url.params["bookmakers"].split(",")) == {
            "onexbet",
            "bet25",
            "bet99",
            "betfair_ex",
            "betmgm",
            "betrivers",
            "betus",
            "bookmaker_eu",
            "bovada",
            "courtside",
            "draftkings",
            "fanatics",
            "fanduel",
            "fliff",
            "hardrock",
            "kalshi",
            "novig",
            "pinnacle",
            "polymarket",
            "polymarket_us",
            "prophetx",
            "rebet",
            "thescorebet",
            "thrillzz",
        }
        assert "max_age" not in request.url.params
        assert request.url.params["period"] == "all"
        assert request.url.params["includeBookIds"] == "true"
        markets = set(request.url.params["markets"].split(","))
        assert {"h2h", "spreads"} < markets
        sport = request.url.path.split("/")[3]
        requested.append(sport)
        body = copy.deepcopy(propline_raw)
        body[0]["sport_key"] = sport
        if sport == "football_nfl":
            assert "player_pass_yds" in markets and "player_2plus_td" in markets
        if sport == "baseball_mlb":
            assert "pitcher_strikeouts" in markets and "batter_hits_runs_rbis" in markets
        return httpx.Response(200, json=body, headers={"X-Daily-Remaining": "997"})

    http = httpx.AsyncClient(
        base_url="https://api.prop-line.com",
        transport=httpx.MockTransport(handler),
        headers={"X-API-Key": "offline-propline-key"},
    )
    report = await probe(settings(), tmp_path, list(SPORT_KEYS), http=http, clock=clock)
    assert requested == list(SPORT_KEYS.values())
    assert report["retrieval_verified"] and report["requests_made"] == 5
    assert request_budget()["requests_per_utc_day"] == 900
    assert json.loads((tmp_path / "nba_basketball.json").read_text()) == propline_raw
    assert "offline-propline-key" not in (tmp_path / "summary.json").read_text()


@pytest.mark.parametrize("status", [401, 403, 429, 503])
async def test_key_wide_error_stops_probe_without_retries(tmp_path, clock, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            json={"error": "offline-propline-key"},
            headers={"Retry-After": "120", "X-Daily-Remaining": "0"},
        )

    http = httpx.AsyncClient(base_url="https://api.prop-line.com", transport=httpx.MockTransport(handler))
    report = await probe(settings(), tmp_path, list(SPORT_KEYS), http=http, clock=clock)
    assert len(calls) == report["requests_made"] == 1
    assert not report["retrieval_verified"]
    assert report["errors"][0]["http_status"] == status
    assert report["errors"][0]["retry_seconds"] == 120
    assert "offline-propline-key" not in (tmp_path / "summary.json").read_text()


async def test_retry_after_blocks_next_call_without_sleeping_or_retrying(clock):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "18000"})

    http = httpx.AsyncClient(base_url="https://api.prop-line.com", transport=httpx.MockTransport(handler))
    client = ProplineClient(settings(), clock, http)
    try:
        with pytest.raises(ProplineError, match="rate_limited"):
            await client.fetch_bulk("nba_basketball")
        with pytest.raises(ProplineError, match="provider_cooldown") as error:
            await client.fetch_bulk("nfl_football")
        assert error.value.retry_seconds == 18000
        assert len(calls) == 1 and clock.sleeps == []
    finally:
        await client.close()


async def test_daily_quota_resumes_at_the_advertised_utc_reset(clock):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json=[],
            headers={
                "X-Daily-Remaining": "0",
                "X-Daily-Reset": str(int(clock.origin.timestamp()) + 100),
            },
        )

    http = httpx.AsyncClient(base_url="https://api.prop-line.com", transport=httpx.MockTransport(handler))
    client = ProplineClient(settings(), clock, http)
    try:
        await client.fetch_bulk("nba_basketball")
        with pytest.raises(ProplineError, match="daily_quota_exhausted"):
            await client.fetch_bulk("nba_basketball")
        assert len(calls) == 1
        clock.value = 100
        await client.fetch_bulk("nba_basketball")
        assert len(calls) == 2
    finally:
        await client.close()


@pytest.mark.parametrize("fault", ["envelope", "price", "point", "sport", "timezone", "duplicate"])
async def test_invalid_payloads_never_verify(clock, propline_raw, fault):
    body = copy.deepcopy(propline_raw)
    if fault == "envelope":
        body = {"data": body}
    elif fault == "price":
        body[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] = -99
    elif fault == "point":
        del body[0]["bookmakers"][0]["markets"][1]["outcomes"][0]["point"]
    elif fault == "sport":
        body[0]["sport_key"] = "hockey_nhl"
    elif fault == "timezone":
        body[0]["commence_time"] = "2026-10-20T12:00:00"
    else:
        body.append(copy.deepcopy(body[0]))
    http = httpx.AsyncClient(
        base_url="https://api.prop-line.com",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    client = ProplineClient(settings(), clock, http)
    try:
        with pytest.raises(ProplineError, match="invalid_bulk_response"):
            await client.fetch_bulk("nba_basketball")
    finally:
        await client.close()


async def test_report_preserves_shapes_periods_and_flags_unavailable_rows(clock, propline_raw):
    book = propline_raw[0]["bookmakers"][0]
    book["markets"].append(
        {
            "key": "player_points",
            "period": "q1",
            "last_update": clock.now().isoformat(),
            "outcomes": [{"name": "10+ Points", "description": "Example Player", "price": 200}],
        }
    )
    # Withdrawn selection: recently updated market, but the selection wasn't in that delivery.
    book["markets"][2]["outcomes"][0]["last_seen_at"] = (clock.now() - timedelta(seconds=1)).isoformat()
    book["markets"][1]["last_update"] = (clock.now() - timedelta(seconds=301)).isoformat()
    book["markets"][0]["suspended_at"] = clock.now().isoformat()
    dfs = copy.deepcopy(book)
    dfs.update(key="prizepicks", title="PrizePicks")
    propline_raw[0]["bookmakers"].append(dfs)
    http = httpx.AsyncClient(
        base_url="https://api.prop-line.com",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=propline_raw)),
    )
    client = ProplineClient(settings(), clock, http)
    try:
        result = await client.fetch_bulk("nba_basketball")
        summary = summarize(result)
        assert result.events[0].bookmakers[0].markets[-1].period == "q1"
        assert result.raw == propline_raw
        assert summary["counts"]["withdrawn_outcomes"] == 2
        assert summary["counts"]["stale_outcomes"] == 4
        assert summary["counts"]["dfs_outcomes"] == 7
        assert summary["counts"]["prop_shape:milestone_or_yes_only"] == 2
        assert not summary["retrieval_verified"]
    finally:
        await client.close()
