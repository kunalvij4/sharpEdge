import copy
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from odds_api.domain.models import Availability
from odds_api.http.app import create_app
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.propline import BulkOdds, Event
from odds_api.infrastructure.propline_normalization import boards
from odds_api.propline_collector import collect_cycle


def snapshot(board, clock):
    canonical = board()
    event = canonical.events[0]
    player = board("props").quotes[0]
    now = clock.now().isoformat()
    raw = [
        {
            "id": "propline-event",
            "sport_key": "basketball_nba",
            "home_team": event.home,
            "away_team": event.away,
            "commence_time": event.start.isoformat(),
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "markets": [
                        {
                            "key": "h2h",
                            "last_update": now,
                            "outcomes": [
                                {"name": event.home, "side": "home", "price": -110},
                                {"name": event.away, "side": "away", "price": 100},
                            ],
                        },
                        {
                            "key": "spreads",
                            "last_update": now,
                            "outcomes": [
                                {"name": event.home, "side": "home", "price": -110, "point": -1.5},
                                {"name": event.away, "side": "away", "price": -110, "point": 1.5},
                            ],
                        },
                        {
                            "key": "player_points",
                            "last_update": now,
                            "outcomes": [
                                {
                                    "name": "Over",
                                    "description": player.description,
                                    "price": -110,
                                    "point": 25.5,
                                    "player_id": "nba:42",
                                    "last_seen_at": now,
                                },
                                {
                                    "name": "Under",
                                    "description": player.description,
                                    "price": -110,
                                    "point": 25.5,
                                    "player_id": "nba:42",
                                    "last_seen_at": now,
                                },
                                {
                                    "name": "30+ Points",
                                    "description": player.description,
                                    "price": 200,
                                    "player_id": "nba:42",
                                    "point": None,
                                    "last_seen_at": now,
                                },
                            ],
                        },
                    ],
                }
            ],
        }
    ]
    return raw


def ingest(raw, repo, clock):
    result = BulkOdds(
        "nba_basketball", tuple(Event.model_validate(e) for e in raw), raw, {}, clock.now(), 0, 0
    )
    output, counts = boards(result, repo)
    for board in output:
        repo.save(board)
    return output, counts


def test_complete_refreshes_cannot_remove_another_provider(repo, board, clock):
    repo.save(board())
    repo.save(board("props"))
    raw = snapshot(board, clock)
    output, counts = ingest(raw, repo, clock)
    assert counts["matched_events"] == 1 and counts["stored_outcomes"] == 7
    expected = {q.selection_id for b in output for q in b.quotes}
    assert expected
    repo.save(board())
    repo.save(board("props"))
    assert {
        row["quote"].selection_id
        for row in repo.quotes("nba_basketball")
        if row["book_key"].startswith("propline_") and row["quote"].state == Availability.AVAILABLE
    } == expected
    # Even an empty successful response retains prior data at its original age.
    before = repo.quotes("nba_basketball")
    ingest([], repo, clock)
    rows = repo.quotes("nba_basketball")
    assert rows == before
    assert all(
        row["quote"].state == Availability.AVAILABLE
        for row in rows
        if row["book_key"].startswith("unabated_")
    )


def test_spreads_props_and_milestones_round_trip_through_public_api(repo, board, clock):
    repo.save(board())
    repo.save(board("props"))
    ingest(snapshot(board, clock), repo, clock)
    settings = Settings(_env_file=None, api_keys="test-product")
    headers = {"X-API-Key": "test-product"}
    eid = board().events[0].id
    with TestClient(create_app(settings, repo, clock)) as client:
        response = client.get(
            "/v1/sports/nba_basketball/odds?markets=spreads&oddsFormat=american", headers=headers
        )
        assert response.status_code == 200
        assert response.json()[0]["id"] == eid
        book = response.json()[0]["bookmakers"][0]
        assert book["key"] == "draftkings"
        assert {o["point"] for o in book["markets"][0]["outcomes"]} == {-1.5, 1.5}
        props = client.get(f"/v1/events/{eid}/props?bookmakers=draftkings", headers=headers)
        assert props.status_code == 200
        outcomes = props.json()["bookmakers"][0]["markets"][0]["outcomes"]
        assert {o["name"] for o in outcomes} == {"Over", "Under", "30+ Points"}
        assert "point" not in next(o for o in outcomes if o["name"] == "30+ Points")
        assert client.get(f"/v1/events/{eid}/props?markets=spreads", headers=headers).status_code == 422
        # Quotes remain fresh through the eight-minute polling boundary and expire after ten minutes.
        clock.value = 481
        fresh = client.get(f"/v1/events/{eid}/props?bookmakers=draftkings&freshOnly=true", headers=headers)
        assert fresh.json()["freshness"]["status"] == "fresh"
        assert client.get("/v1/sports/nba_basketball/odds?markets=spreads", headers=headers).json()
        clock.value = 601
        expired = client.get(f"/v1/events/{eid}/props?bookmakers=draftkings", headers=headers)
        assert expired.json()["bookmakers"] == []
        assert client.get("/v1/sports/nba_basketball/odds?markets=spreads", headers=headers).json() == []


def test_rejects_unmatched_and_ambiguous_fixtures(repo, board, clock):
    canonical = board()
    repo.save(canonical)
    raw = snapshot(board, clock)
    other = replace(canonical.events[0], source_id="other-game-same-teams-and-time")
    repo.save(replace(canonical, events=(other,), quotes=()))
    output, counts = ingest(raw, repo, clock)
    assert counts["unmatched_or_ambiguous_events"] == 1
    assert all(not b.quotes for b in output)
    raw[0]["away_team"] = "Another Team"
    output, counts = ingest(raw, repo, clock)
    assert counts["unmatched_or_ambiguous_events"] == 1
    assert all(not b.quotes for b in output)
    assert len(repo.events("nba_basketball")) == 2


def test_nba_tipoff_offset_matches_one_fixture_without_moving_its_start(repo, board, clock):
    repo.save(board())
    raw = snapshot(board, clock)
    canonical = board().events[0]
    raw[0]["commence_time"] = (canonical.start + timedelta(minutes=10)).isoformat()
    output, counts = ingest(raw, repo, clock)
    assert counts["matched_events"] == 1
    assert output[0].events[0].start == canonical.start
    assert repo.event(canonical.id)["start"] == canonical.start


def test_abbreviated_city_in_either_feed_and_reversed_orientation():
    from odds_api.infrastructure.propline_normalization import match_event, teams_match

    assert teams_match("Los Angeles Clippers", "LA Clippers")
    assert teams_match("LA Clippers", "Los Angeles Clippers")
    assert not teams_match("Los Angeles Clippers", "LA Lakers")
    event = Event.model_validate(
        {
            "id": "source",
            "sport_key": "basketball_nba",
            "home_team": "Los Angeles Clippers",
            "away_team": "Oklahoma City Thunder",
            "commence_time": "2026-10-25T23:00:00Z",
            "bookmakers": [],
        }
    )
    canonical = {
        "status": "pregame",
        "start": event.commence_time,
        "home": "OKC Thunder",
        "away": "LA Clippers",
    }
    assert match_event(event, [canonical]) is canonical


def test_excludes_dfs_withdrawn_suspended_and_stale_prices(repo, board, clock):
    repo.save(board())
    raw = snapshot(board, clock)
    book = raw[0]["bookmakers"][0]
    dfs = copy.deepcopy(book)
    dfs.update(key="pick6", title="DraftKings Pick6")
    raw[0]["bookmakers"].append(dfs)
    book["markets"][0]["suspended_at"] = clock.now().isoformat()
    book["markets"][1]["last_update"] = (clock.now() - timedelta(seconds=901)).isoformat()
    book["markets"][2]["outcomes"][0]["last_seen_at"] = (clock.now() - timedelta(seconds=1)).isoformat()
    broken = copy.deepcopy(book["markets"][2]["outcomes"][0])
    broken["last_seen_at"] = clock.now().isoformat()
    broken["point"] = None
    book["markets"][2]["outcomes"].append(broken)
    output, counts = ingest(raw, repo, clock)
    quotes = [q for b in output for q in b.quotes]
    assert {q.name for q in quotes} == {"Under", "30+ Points"}
    assert counts["excluded_dfs_or_frozen_book_blocks"] == 1
    assert counts["withdrawn_outcomes"] == 1
    assert counts["suspended_stale_or_undated_markets"] == 2
    assert counts["props_without_required_line"] == 1


def test_duplicate_conflicts_are_suspended_and_periods_stay_separate(repo, board, clock):
    repo.save(board())
    raw = snapshot(board, clock)
    book = raw[0]["bookmakers"][0]
    quarter = copy.deepcopy(book["markets"][2])
    quarter["period"] = "q1"
    conflict = copy.deepcopy(book["markets"][2])
    conflict["outcomes"] = [copy.deepcopy(conflict["outcomes"][0])]
    conflict["outcomes"][0]["price"] = 150
    book["markets"].extend([quarter, conflict])
    output, counts = ingest(raw, repo, clock)
    assert counts["conflicting_selections"] == 1
    props = next(b for b in output if b.kind == "props")
    assert not props.complete
    assert len([q for q in props.quotes if q.market == "player_points_q1"]) == 3
    assert any(
        q.name == "Over" and q.market == "player_points" and q.state == Availability.SUSPENDED
        for q in props.quotes
    )


async def test_collection_cycle_uses_one_bulk_call_per_configured_league(repo, board, clock):
    from odds_api.infrastructure.propline import SPORT_KEYS, ProplineClient

    repo.save(board())
    raw = snapshot(board, clock)
    requested = []

    def handler(request):
        requested.append(request.url.path)
        body = copy.deepcopy(raw)
        body[0]["sport_key"] = request.url.path.split("/")[3]
        return httpx.Response(200, json=body)

    http = httpx.AsyncClient(base_url="https://api.prop-line.com", transport=httpx.MockTransport(handler))
    settings = Settings(_env_file=None, propline_api_key="offline-key", propline_enabled=True)
    client = ProplineClient(settings, clock, http)
    state = {}
    try:
        await collect_cycle(client, repo, settings, state)
        assert len(requested) == 5
        assert set(state) == set(SPORT_KEYS)
        assert all(row["outcome"] == "success" for row in state.values())
    finally:
        await client.close()


def test_polling_faster_than_five_minutes_is_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, propline_poll_interval=299)


def test_explicit_period_moneyline_draw_is_preserved(repo, board, clock):
    repo.save(board())
    raw = snapshot(board, clock)
    market = raw[0]["bookmakers"][0]["markets"][0]
    market["period"] = "p1"
    market["outcomes"].append({"name": "Draw", "side": "draw", "price": 250})
    output, _ = ingest(raw, repo, clock)
    assert {q.name for b in output for q in b.quotes if q.market == "h2h_p1"} == {
        "Home Team",
        "Away Team",
        "Draw",
    }
