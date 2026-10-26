from datetime import datetime, timedelta, timezone
import importlib
import json
from unittest.mock import Mock

import boto3
import pytest
import requests


NOW = datetime(2026, 10, 26, 17, 55, tzinfo=timezone.utc)
LEAGUES = ("NBA", "NFL", "NHL", "MLB", "NCAAF")


def raw_event(league, label="near", minutes=5):
    return {
        "id": f"{league}-{label}", "sport_title": league,
        "home_team": "Home", "away_team": "Away",
        "commence_time": (NOW + timedelta(minutes=minutes)).isoformat(),
        "bookmakers": [
            {"title": book, "markets": [
                {"key": "h2h", "outcomes": [{"name": "Home", "price": 2.2}, {"name": "Away", "price": 2.2}]},
                {"key": "spreads", "outcomes": [
                    {"name": "Home", "price": 2.2, "point": -3.5},
                    {"name": "Away", "price": 2.2, "point": 3.5},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": 2.2, "point": 220.5},
                    {"name": "Under", "price": 2.2, "point": 220.5},
                ]},
            ]}
            for book in ("FanDuel", "DraftKings")
        ],
    }


@pytest.fixture
def runtime(monkeypatch, closing_store):
    app = importlib.import_module("odds_pipeline.handler")
    cache = importlib.import_module("odds_pipeline.cache")
    results = importlib.import_module("odds_pipeline.results")
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setenv("ODDS_API_BASE_URL", "https://odds.example.com")
    monkeypatch.setenv("REDIS_URL", "rediss://default:test-password@cache.invalid:6379")
    monkeypatch.setattr(app, "utc_now", lambda: NOW)
    monkeypatch.setattr(app, "ClosingOddsStore", lambda: closing_store)
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-pipeline-results")
    monkeypatch.setattr(app, "ResultsPublisher", lambda: results.ResultsPublisher(bucket="test-pipeline-results", s3=s3))
    snapshots = {}
    client = Mock()
    client.hset.side_effect = lambda table, field, body: snapshots.update({(table, field): json.loads(body)})
    monkeypatch.setattr(cache, "_get_client", lambda url: client)
    api = app.OddsAPI("test-key", "https://odds.example.com")

    def get_odds(sport, **kwargs):
        league = next(league for league, key in app.LEAGUE_SPORT_KEYS.items() if key == sport)
        return [raw_event(league), raw_event(league, "far", 60), raw_event(league, "started", -5)]

    def get_event_odds(sport, event_id, markets):
        assert markets == "all_props"
        prop_markets = importlib.import_module("odds_pipeline.leagues").PROP_MARKETS_BY_SPORT[sport]
        return {"id": event_id, "bookmakers": [
            {"title": book, "markets": [
                {"key": market, "outcomes": [
                    {"name": side, "description": "Player", "point": 20.5, "price": 2.2}
                    for side in ("Over", "Under")
                ]} for market in prop_markets
            ]} for book in ("FanDuel", "DraftKings")
        ]}

    api.get_odds = Mock(side_effect=get_odds)
    api.get_events = Mock(return_value=[])
    api.get_event_odds = Mock(side_effect=get_event_odds)
    monkeypatch.setattr(app, "OddsAPI", lambda key, base_url: api)
    return app, api, s3, snapshots, cache, closing_store


def s3_results(s3):
    return {
        item["Key"]: json.loads(s3.get_object(Bucket="test-pipeline-results", Key=item["Key"])["Body"].read())
        for item in s3.list_objects_v2(Bucket="test-pipeline-results").get("Contents", [])
    }


def test_one_run_fetches_all_leagues_archives_only_near_start_and_publishes_results(runtime):
    app, api, s3, snapshots, _, store = runtime

    summary = app.lambda_handler({}, None)

    assert summary["status"] == "complete"
    assert summary["events_fetched"] == 15
    assert api.get_odds.call_count == 5
    assert api.get_events.call_count == 5
    assert api.get_event_odds.call_count == 15
    assert summary["closing_prices_written"] > 0
    objects = s3_results(s3)
    assert len(objects) == len(snapshots) == 40
    assert all(key.startswith(("ev/", "arbitrage/")) for key in objects)
    for league in LEAGUES:
        archived = store.get_event(f"{league}-near", now=NOW)
        assert {row["category"] for row in archived} == {"moneyline", "spreads", "totals", "props"}
        assert store.get_event(f"{league}-far", now=NOW) == []
        assert store.get_event(f"{league}-started", now=NOW) == []
        for category in ("moneyline", "spreads", "totals", "props"):
            for table, prefix, suffix in (("EV", "ev", "ev"), ("arbitrage", "arbitrage", "arb")):
                rows = objects[f"{prefix}/{league}/{category}_{suffix}.json"]
                assert rows
                assert {row["event_id"] for row in rows} == {
                    f"{league}-near", f"{league}-far", f"{league}-started",
                }
                snapshot = snapshots[table, f"{league}/{category}"]
                assert snapshot["league"] == league
                assert snapshot["opportunities"] == rows
                assert snapshot["count"] == len(rows)
            archive_keys = {row["bet_key"] for row in archived}
            for bet in objects[f"ev/{league}/{category}_ev.json"]:
                if bet["event_id"] == f"{league}-near":
                    assert bet["id"] in archive_keys


def test_props_only_events_are_processed_and_archived_for_all_leagues(runtime):
    app, api, s3, snapshots, _, store = runtime
    api.get_odds.side_effect = lambda *args, **kwargs: []

    def events(sport):
        league = next(league for league, key in app.LEAGUE_SPORT_KEYS.items() if key == sport)
        event = raw_event(league)
        event.pop("bookmakers")
        return [event]

    api.get_events.side_effect = events
    summary = app.lambda_handler({}, None)

    assert summary["status"] == "complete"
    assert summary["events_fetched"] == 5
    assert api.get_event_odds.call_count == 5
    objects = s3_results(s3)
    for league in LEAGUES:
        archived = store.get_event(f"{league}-near", now=NOW)
        assert {row["category"] for row in archived} == {"props"}
        assert objects[f"ev/{league}/props_ev.json"]
        assert snapshots["EV", f"{league}/props"]["count"] > 0
        assert objects[f"ev/{league}/moneyline_ev.json"] == []


def test_event_ids_prevent_same_team_rematches_from_colliding(runtime):
    app, api, *_ = runtime
    first, second = raw_event("NBA", "first"), raw_event("NBA", "second")
    games = api.parse_all_markets_odds([first, second])
    assert set(games) == {"NBA-first", "NBA-second"}
    ev, arb = importlib.import_module("odds_pipeline.engine").calculate("NBA", games)
    assert {bet["event_id"] for bet in ev["moneyline"]} == {"NBA-first", "NBA-second"}
    assert {bet["event_id"] for bet in arb["moneyline"]} == {"NBA-first", "NBA-second"}


def test_different_spread_and_total_lines_cannot_create_false_arbitrage(runtime):
    _, api, *_ = runtime
    raw = raw_event("NBA")
    raw["bookmakers"][0]["markets"][1]["outcomes"][1]["point"] = 4.5
    raw["bookmakers"][0]["markets"][2]["outcomes"] = [{"name": "Over", "price": 3, "point": 220.5}]
    raw["bookmakers"][1]["markets"][1]["outcomes"] = [{"name": "Away", "price": 3, "point": 5.5}]
    raw["bookmakers"][1]["markets"][2]["outcomes"] = [{"name": "Under", "price": 3, "point": 221.5}]
    games = api.parse_all_markets_odds([raw])
    _, arb = importlib.import_module("odds_pipeline.engine").calculate("NBA", games)
    assert arb["spreads"] == []
    assert arb["totals"] == []


def test_props_arbitrage_is_independent_of_ev_eligibility(runtime):
    _, api, *_ = runtime
    game = next(iter(api.parse_all_markets_odds([raw_event("NFL")]).values()))
    game["markets"] = {"props": {"player_pass_yds": {"Player": {"250.5": {
        "Bovada": {"over_odds": 2.2, "under_odds": 2.2},
    }}}}}
    ev, arb = importlib.import_module("odds_pipeline.engine").calculate("NFL", {game["event_id"]: game})
    assert ev["props"] == []
    assert len(arb["props"]) == 1
    assert arb["props"][0]["event_id"] == "NFL-near"


def test_different_players_and_prop_lines_cannot_create_false_arbitrage(runtime):
    _, api, *_ = runtime
    game = next(iter(api.parse_all_markets_odds([raw_event("NBA")]).values()))
    game["markets"] = {"props": {"player_points": {
        "Player A": {"20.5": {"FanDuel": {"over_odds": 2.2, "under_odds": 1.01}}},
        "Player B": {"20.5": {"DraftKings": {"over_odds": 1.01, "under_odds": 2.2}}},
        "Player C": {
            "20.5": {"FanDuel": {"over_odds": 2.2}},
            "21.5": {"DraftKings": {"under_odds": 2.2}},
        },
    }}}
    _, arb = importlib.import_module("odds_pipeline.engine").calculate("NBA", {game["event_id"]: game})
    assert arb["props"] == []


def test_three_way_draw_market_is_not_mistaken_for_two_way_arbitrage(runtime):
    _, api, *_ = runtime
    raw = raw_event("NHL")
    for book in raw["bookmakers"]:
        book["markets"] = [{"key": "h2h", "outcomes": [
            {"name": "Home", "price": 3}, {"name": "Away", "price": 3}, {"name": "Draw", "price": 3},
        ]}]
    ev, arb = importlib.import_module("odds_pipeline.engine").calculate("NHL", api.parse_all_markets_odds([raw]))
    assert ev["moneyline"] == arb["moneyline"] == []


def test_results_missing_event_id_are_rejected_before_storage(runtime):
    _, _, s3, snapshots, *_ = runtime
    results = importlib.import_module("odds_pipeline.results")
    categories = ("moneyline", "spreads", "totals", "props")
    ev = {category: [] for category in categories}
    arb = {category: [] for category in categories}
    ev["moneyline"] = [{"sport": "NBA", "odds": 2.2}]
    failures = results.ResultsPublisher(bucket="test-pipeline-results", s3=s3).publish("NBA", ev, arb, NOW.isoformat())
    assert "ev/NBA/moneyline_ev.json" in failures
    assert "ev/NBA/moneyline_ev.json" not in s3_results(s3)
    assert ("EV", "NBA/moneyline") not in snapshots


def test_empty_current_results_replace_old_cache_entries(runtime):
    app, api, s3, snapshots, *_ = runtime
    snapshots["EV", "NBA/moneyline"] = {"opportunities": [{"old": True}]}
    api.get_odds.side_effect = lambda *args, **kwargs: []

    summary = app.lambda_handler({}, None)

    assert summary["status"] == "complete"
    assert summary["closing_prices_written"] == 0
    assert all(rows == [] for rows in s3_results(s3).values())
    assert snapshots["EV", "NBA/moneyline"]["opportunities"] == []


def test_redis_failure_does_not_block_s3_or_closing_prices(runtime, monkeypatch, caplog):
    app, _, s3, _, cache, store = runtime
    monkeypatch.setattr(cache, "_get_client", Mock(side_effect=ConnectionError("test-password")))

    summary = app.lambda_handler({}, None)

    assert summary["status"] == "partial"
    assert len(s3_results(s3)) == 40
    assert store.get_event("NBA-near", now=NOW)
    assert "test-password" not in caplog.text


def test_s3_failure_does_not_block_redis_or_closing_prices(runtime, monkeypatch):
    app, _, s3, snapshots, _, store = runtime
    monkeypatch.setattr(s3, "put_object", Mock(side_effect=RuntimeError("S3 unavailable")))

    summary = app.lambda_handler({}, None)

    assert summary["status"] == "partial"
    assert len(snapshots) == 40
    assert store.get_event("NBA-near", now=NOW)


def test_one_failed_league_does_not_clear_its_previous_results_or_block_others(runtime):
    app, api, s3, snapshots, *_ = runtime
    original = api.get_odds.side_effect
    api.get_odds.side_effect = lambda sport, **kwargs: (_ for _ in ()).throw(requests.Timeout()) if sport == "americanfootball_nfl" else original(sport, **kwargs)
    previous = {"opportunities": [{"old": True}]}
    snapshots["EV", "NFL/moneyline"] = previous

    summary = app.lambda_handler({}, None)

    assert summary["failed_leagues"] == ["NFL"]
    assert len(s3_results(s3)) == 32
    assert snapshots["EV", "NFL/moneyline"] is previous


def test_partial_props_failure_preserves_complete_props_results(runtime):
    app, api, s3, snapshots, *_ = runtime
    original = api.get_event_odds.side_effect

    def get_props(sport, event_id, markets):
        if sport == "americanfootball_nfl":
            raise requests.HTTPError(response=Mock(status_code=403, headers={}))
        return original(sport, event_id, markets)

    api.get_event_odds.side_effect = get_props
    previous = {"opportunities": [{"old": True}]}
    snapshots["EV", "NFL/props"] = previous
    summary = app.lambda_handler({}, None)

    assert summary["props_failed_events"]["NFL"]
    assert summary["failed_leagues"] == []
    assert snapshots["EV", "NFL/props"] is previous
    assert "ev/NFL/moneyline_ev.json" in s3_results(s3)
    assert "ev/NFL/props_ev.json" not in s3_results(s3)


def test_props_response_after_start_cannot_retimestamp_or_archive_game_lines(runtime, monkeypatch):
    app, api, _, _, _, store = runtime
    monkeypatch.setattr(app, "LEAGUE_SPORT_KEYS", {"NBA": "basketball_nba"})
    start = NOW + timedelta(minutes=5)
    times = iter([start - timedelta(seconds=1), start + timedelta(seconds=1)])
    monkeypatch.setattr(app, "utc_now", lambda: next(times))
    api.get_odds.side_effect = lambda *args, **kwargs: [raw_event("NBA")]

    summary = app.lambda_handler({}, None)

    assert summary["status"] == "complete"
    archived = store.get_event("NBA-near", now=start)
    assert archived
    assert {row["category"] for row in archived} == {"moneyline", "spreads", "totals"}
    assert {row["observed_at"] for row in archived} == {(start - timedelta(seconds=1)).isoformat(timespec="microseconds")}


@pytest.mark.parametrize("status, retry", [(429, True), (503, True), (400, False)])
def test_player_props_have_bounded_retries_and_keep_failure_visible(monkeypatch, status, retry):
    collect = importlib.import_module("odds_pipeline.collect")
    api = Mock()
    api.get_event_odds.side_effect = [requests.HTTPError(response=Mock(status_code=status, headers={"Retry-After": "3"})), {"bookmakers": []}]
    sleep = Mock()
    monkeypatch.setattr(collect.time, "sleep", sleep)
    failures = []
    collect.fetch_and_attach_player_props(api, "americanfootball_ncaaf", {"event": {"event_id": "event"}}, failures)
    assert api.get_event_odds.call_count == (2 if retry else 1)
    assert failures == ([] if retry else ["event"])
    assert sleep.call_count == (1 if retry else 0)


def test_real_redis_client_uses_tls_verification_and_bounded_timeouts():
    import ssl
    cache = importlib.import_module("odds_pipeline.cache")
    cache._get_client.cache_clear()
    client = cache._get_client("rediss://default:encoded%40password@cache.invalid:6379")
    try:
        connection = client.connection_pool.make_connection()
        assert connection.check_hostname is True
        assert connection.cert_reqs == ssl.CERT_REQUIRED
        assert connection.password == "encoded@password"
        assert connection.socket_connect_timeout == 1
        assert connection.socket_timeout == 2
    finally:
        client.close()
        cache._get_client.cache_clear()
