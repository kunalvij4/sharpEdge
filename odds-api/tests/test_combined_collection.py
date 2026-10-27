import asyncio
import copy
import json
import threading
from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from test_propline_integration import snapshot

from odds_api.application.feed_schedule import FeedSchedule
from odds_api.collector import CombinedCollection
from odds_api.domain.models import League
from odds_api.http.app import create_app
from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings
from odds_api.infrastructure.propline import SPORT_KEYS, ProplineClient


async def test_schedule_alternates_every_four_minutes_and_survives_restart(clock, tmp_path):
    path = tmp_path / "schedule.json"
    calls = []

    async def collect(feed):
        calls.append((feed, clock.monotonic()))

    for instant in (0, 100, 239, 240, 479, 480, 720, 960):
        clock.value = instant
        # Reconstruct each time to prove a restart cannot trigger an extra request.
        await FeedSchedule(clock, path).tick(collect)
    assert calls == [
        ("propline", 0),
        ("unabated", 240),
        ("propline", 480),
        ("unabated", 720),
        ("propline", 960),
    ]


async def test_slow_cycle_and_downtime_preserve_alternation_without_catch_up(clock, tmp_path):
    schedule = FeedSchedule(clock, tmp_path / "schedule.json")
    calls = []

    async def collect(feed):
        calls.append((feed, clock.value))
        clock.value += 300

    await schedule.tick(collect)
    await schedule.tick(collect)
    assert calls == [("propline", 0), ("unabated", 300)]
    clock.value = 600
    await schedule.tick(collect)
    clock.value = 2400
    await schedule.tick(collect)
    assert calls == [("propline", 0), ("unabated", 300), ("propline", 600), ("unabated", 2400)]


async def test_crash_does_not_reissue_claimed_slot(clock, tmp_path):
    path = tmp_path / "schedule.json"

    async def fail(feed):
        raise RuntimeError("failed")

    with pytest.raises(RuntimeError):
        await FeedSchedule(clock, path).tick(fail)
    calls = []

    async def collect(feed):
        calls.append(feed)

    await FeedSchedule(clock, path).tick(collect)
    assert not calls
    clock.value = 240
    await FeedSchedule(clock, path).tick(collect)
    assert calls == ["unabated"]


async def test_late_restart_keeps_four_minutes_between_provider_starts(clock, tmp_path):
    path = tmp_path / "schedule.json"
    calls = []

    async def collect(feed):
        calls.append((feed, clock.value))

    await FeedSchedule(clock, path).tick(collect)
    clock.value = 400
    await FeedSchedule(clock, path).tick(collect)
    clock.value = 480
    await FeedSchedule(clock, path).tick(collect)
    assert calls == [("propline", 0), ("unabated", 400)]
    clock.value = 640
    await FeedSchedule(clock, path).tick(collect)
    assert calls[-1] == ("propline", 640)


async def test_both_feeds_share_five_league_api_after_cold_start(repo, board, clock, tmp_path):
    settings = Settings(
        _env_file=None,
        api_keys="offline-product",
        unabated_odds_enabled=True,
        propline_api_key="offline-key",
        propline_output_dir=str(tmp_path),
        leagues_json=json.dumps(DEFAULT_LEAGUES),
    )
    calls = []
    template = snapshot(board, clock)
    prop_keys = {
        "nhl_hockey": "player_points",
        "nba_basketball": "player_points",
        "nfl_football": "player_pass_yds",
        "mlb_baseball": "batter_hits",
        "ncaaf_football": "player_pass_yds",
    }

    def handler(request):
        sport = request.url.path.split("/")[3]
        calls.append(sport)
        raw = copy.deepcopy(template)
        raw[0]["sport_key"] = sport
        key = next(k for k, v in SPORT_KEYS.items() if v == sport)
        raw[0]["bookmakers"][0]["markets"][2]["key"] = prop_keys[key]
        return httpx.Response(200, json=raw)

    class Unabated:
        async def fetch(self, sport, kind):
            source = board(kind)
            league = League(sport, DEFAULT_LEAGUES[sport]["title"], DEFAULT_LEAGUES[sport]["route"], sport)
            event = replace(source.events[0], league_key=sport)
            return replace(
                source,
                league=league,
                events=(event,),
                collected_at=clock.now(),
                quotes=tuple(
                    replace(
                        q,
                        event_id=event.id,
                        collected_at=clock.now(),
                        market=prop_keys[sport] if kind == "props" else q.market,
                    )
                    for q in source.quotes
                ),
            )

    http = httpx.AsyncClient(base_url="https://api.prop-line.com", transport=httpx.MockTransport(handler))
    propline = ProplineClient(settings, clock, http)
    collection = CombinedCollection(settings, clock, repo, Unabated(), propline, Mock())
    try:
        await collection.collect("propline")
        assert len(calls) == 5
        assert not repo.events("nba_basketball")
        clock.value = 240
        await collection.collect("unabated")
        assert len(calls) == 5  # Catalog rejoin never calls the provider again.
        with TestClient(create_app(settings, repo, clock)) as api:
            for league in DEFAULT_LEAGUES:
                response = api.get(
                    f"/v1/sports/{league}/odds?markets=h2h,spreads&oddsFormat=american",
                    headers={"X-API-Key": "offline-product"},
                )
                assert response.status_code == 200
                event = response.json()[0]
                assert {b["key"] for b in event["bookmakers"]} == {"unabated_901", "propline_draftkings"}
                props = api.get(f"/v1/events/{event['id']}/props", headers={"X-API-Key": "offline-product"})
                assert {b["key"] for b in props.json()["bookmakers"]} == {
                    "unabated_901",
                    "propline_draftkings",
                }
                rows = [r["quote"] for r in repo.quotes(league) if r["book_key"].startswith("propline_")]
                assert all(q.collected_at == clock.origin for q in rows)
            clock.value = 479
            response = api.get(
                "/v1/sports/nba_basketball/odds?markets=spreads&freshOnly=true",
                headers={"X-API-Key": "offline-product"},
            )
            assert response.json()
    finally:
        await propline.close()


def test_unabated_spread_sign_and_hockey_periods(raw, league, clock):
    from odds_api.infrastructure.normalization import Normalizer

    raw["bets"].append({"id": 99, "name": "Puck Line"})
    raw["periods"][0]["name"] = "First Period"
    group = raw["moneyline"]["data"]["odds"]["notAnIdentity"]["periodTypes"]["arbitrary"]["pregame"][
        "ignored"
    ]
    group["betTypeId"] = 99
    for side in group["sides"].values():
        for line in side["marketSourceLines"].values():
            line["points"] = -1.5 if side["sideIndex"] == 1 else 1.5
    result = Normalizer().parse(
        replace(league, route="nhl"),
        "moneyline",
        raw["moneyline"]["data"],
        raw["sources"],
        raw["bets"],
        raw["periods"],
        raw["events"],
        raw["people"],
        raw["teams"],
        clock.now(),
    )
    assert result.complete
    assert {(q.name, float(q.point), q.market) for q in result.quotes} == {
        ("Home Team", -1.5, "spreads_p1"),
        ("Away Team", 1.5, "spreads_p1"),
    }


async def test_blocking_sql_keeps_loop_responsive_and_finishes_before_cancellation():
    from odds_api.application.async_work import blocking_work

    started, finish, completed = threading.Event(), threading.Event(), threading.Event()

    def save():
        started.set()
        finish.wait(5)
        completed.set()

    task = asyncio.create_task(blocking_work(save))
    try:
        async with asyncio.timeout(2):
            while not started.is_set():
                await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert completed.is_set()
    finally:
        finish.set()
