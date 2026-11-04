import copy
from dataclasses import replace
from datetime import timedelta

import fakeredis
import pytest
from fastapi.testclient import TestClient
from test_propline_integration import snapshot
from test_redis_storage import future_board

from odds_api.domain.models import League
from odds_api.http.app import create_app
from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings
from odds_api.infrastructure.normalization import Normalizer, values
from odds_api.infrastructure.propline import SPORT_KEYS, BulkOdds, Event
from odds_api.infrastructure.propline_normalization import boards, match_event, teams_match
from odds_api.infrastructure.redis_repository import RedisRepository


@pytest.mark.parametrize(
    "left,right",
    [
        ("Miami (OH)", "Miami Ohio"),
        ("Miami FL", "Miami Florida"),
        ("UMass", "Massachusetts"),
        ("Ball St.", "Ball State"),
        ("Mississippi St.", "Mississippi State"),
        ("Ole Miss", "Mississippi"),
        ("(2) Duke Blue Devils", "Duke"),
        ("Army Black Knights", "Army"),
        ("Illinois Fighting Illini", "Illinois"),
        ("Fairleigh Dickinson Knights", "Fairleigh Dickinson"),
        ("FDU Knights", "Fairleigh Dickinson"),
    ],
)
def test_college_school_aliases_match_in_both_directions(left, right):
    for sport in ("basketball_ncaab", "football_ncaaf"):
        assert teams_match(left, right, sport)
        assert teams_match(right, left, sport)
    assert not teams_match(left, right, "basketball_nba")


@pytest.mark.parametrize(
    "left,right",
    [
        ("Michigan", "Michigan State"),
        ("Miami Ohio", "Miami Florida"),
        ("Miami", "Miami Florida"),
        ("Mississippi", "Mississippi State"),
        ("Illinois", "Eastern Illinois"),
        ("FDU Knights", "UCF Knights"),
    ],
)
def test_college_names_never_match_by_shared_prefix_or_mascot(left, right):
    assert not teams_match(left, right, "basketball_ncaab")


def test_college_alias_match_still_requires_unique_fixture_and_kickoff():
    source = Event.model_validate(
        {
            "id": "duke-army",
            "sport_key": "basketball_ncaab",
            "home_team": "(2) Duke Blue Devils",
            "away_team": "Army Black Knights",
            "commence_time": "2026-11-02T23:30:00Z",
            "bookmakers": [],
        }
    )
    canonical = {"status": "pregame", "start": source.commence_time, "home": "Army", "away": "Duke"}
    assert match_event(source, [canonical]) is canonical
    assert match_event(source, [canonical, dict(canonical)]) is None
    assert match_event(source, [{**canonical, "start": canonical["start"] + timedelta(minutes=6)}]) is None


@pytest.mark.parametrize("offset", [-60, 60])
def test_ncaab_hour_offset_requires_two_recognized_schools_and_unique_fixture(offset):
    source = Event.model_validate(
        {
            "id": "byu-ohio-state",
            "sport_key": "basketball_ncaab",
            "home_team": "BYU Cougars",
            "away_team": "Ohio St.",
            "commence_time": "2026-11-03T01:00:00Z",
            "bookmakers": [],
        }
    )
    canonical = {
        "status": "pregame",
        "start": source.commence_time + timedelta(minutes=offset),
        "home": "Ohio State",
        "away": "BYU",
    }
    assert match_event(source, [canonical]) is canonical
    other = {**canonical, "start": source.commence_time - timedelta(minutes=offset)}
    assert match_event(source, [canonical, other]) is None
    closer = {**canonical, "start": source.commence_time}
    assert match_event(source, [canonical, closer]) is closer
    assert match_event(source, [{**canonical, "status": "live"}]) is None
    assert match_event(source, [{**canonical, "away": "Utah"}]) is None
    for minutes in (6, 45, 90):
        assert (
            match_event(source, [{**canonical, "start": source.commence_time + timedelta(minutes=minutes)}])
            is None
        )
    for sport in ("football_ncaaf", "basketball_nba"):
        assert match_event(source.model_copy(update={"sport_key": sport}), [canonical]) is None
    for school in ("Unknown University", "MSU"):
        unconfirmed = source.model_copy(update={"home_team": school})
        assert match_event(unconfirmed, [{**canonical, "away": school}]) is None


@pytest.mark.parametrize("offset", [-60, 60])
def test_ncaab_hour_offset_quotes_expire_at_the_earlier_reported_tipoff(repo, board, clock, offset):
    raw = snapshot(board, clock)
    original = board()
    config = DEFAULT_LEAGUES["ncaab_basketball"]
    canonical_start = clock.now() + timedelta(minutes=5 if offset == 60 else 65)
    event = replace(
        original.events[0],
        league_key="ncaab_basketball",
        start=canonical_start,
        home="BYU",
        away="Ohio State",
    )
    repo.save(
        replace(
            original,
            league=League("ncaab_basketball", config["title"], config["route"], "4"),
            events=(event,),
            quotes=(),
        )
    )
    source_start = canonical_start + timedelta(minutes=offset)
    raw[0].update(
        sport_key="basketball_ncaab",
        commence_time=source_start.isoformat(),
        home_team="BYU Cougars",
        away_team="Ohio St.",
    )
    raw[0]["bookmakers"][0]["markets"] = raw[0]["bookmakers"][0]["markets"][2:]
    result = BulkOdds(
        "ncaab_basketball", tuple(Event.model_validate(e) for e in raw), raw, {}, clock.now(), 0, 0
    )
    output, counts = boards(result, repo)
    assert counts["one_hour_start_offset_events"] == 1
    props = next(b for b in output if b.kind == "props")
    assert len(props.quotes) == 3
    assert props.events[0].id == event.id
    assert props.events[0].start == canonical_start
    assert all(q.expires_at == clock.now() + timedelta(minutes=5) for q in props.quotes)
    for collected in output:
        repo.save(collected)
    with TestClient(create_app(Settings(_env_file=None, api_keys="test"), repo, clock)) as api:
        path = f"/v1/events/{event.id}/props?freshOnly=true"
        headers = {"X-API-Key": "test"}
        assert api.get(path, headers=headers).json()["freshness"]["fresh_outcomes"] == 3
        clock.value = 301
        expired = api.get(path, headers=headers)
        if offset == 60:
            assert expired.status_code == 404  # Canonical event has started.
        else:
            assert expired.json()["freshness"]["fresh_outcomes"] == 0
    # Both feeds must still describe an unstarted fixture.
    output, counts = boards(replace(result, collected_at=clock.now()), repo)
    assert not any(b.quotes for b in output)


@pytest.mark.parametrize("backend", ["sql", "redis"])
@pytest.mark.parametrize("sport", ["ncaaf_football", "ncaab_basketball"])
def test_college_sportsbooks_with_named_players_but_no_ids_reach_fresh_api(
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
    config = DEFAULT_LEAGUES[sport]
    event = replace(source.events[0], league_key=sport, home="Duke", away="Army")
    source = replace(
        source,
        league=League(sport, config["title"], config["route"], "42"),
        events=(event,),
        quotes=(),
    )
    repository.save(source)
    raw[0].update(
        sport_key=SPORT_KEYS[sport],
        commence_time=event.start.isoformat(),
        home_team="(2) Duke Blue Devils",
        away_team="Army Black Knights",
    )
    template = raw[0]["bookmakers"][0]
    template["markets"] = template["markets"][2:]
    market = template["markets"][0]
    market["last_update"] = clock.now().isoformat()
    market["key"] = "player_pass_yds" if sport == "ncaaf_football" else "player_points"
    market["outcomes"] = market["outcomes"][:2]
    for outcome in market["outcomes"]:
        outcome.update(player_id=None, last_seen_at=clock.now().isoformat())
    raw[0]["bookmakers"] = []
    for key, title in (("draftkings", "DraftKings"), ("fanduel", "FanDuel"), ("courtside", "Courtside")):
        book = copy.deepcopy(template)
        book.update(key=key, title=title)
        raw[0]["bookmakers"].append(book)
    # A second fixture must get its own private player identity for this name.
    later = replace(event, source_id="later-fixture", start=event.start + timedelta(days=2))
    repository.save(replace(source, events=(later,)))
    second = copy.deepcopy(raw[0])
    second.update(id="later-propline", commence_time=later.start.isoformat())
    raw.append(second)
    result = BulkOdds(sport, tuple(Event.model_validate(e) for e in raw), raw, {}, clock.now(), 0, 0)
    output, counts = boards(result, repository)
    assert counts["stored_outcomes"] == 12
    props = next(b for b in output if b.kind == "props")
    assert len({q.player_id for q in props.quotes if q.event_id == event.id}) == 1
    assert len({q.player_id for q in props.quotes}) == 2
    for collected in output:
        repository.save(collected)
    with TestClient(create_app(Settings(_env_file=None, api_keys="test"), repository, clock)) as api:
        response = api.get(f"/v1/events/{event.id}/props?freshOnly=true", headers={"X-API-Key": "test"})
        assert response.status_code == 200
        payload = response.json()
        assert {b["key"] for b in payload["bookmakers"]} == {"draftkings", "fanduel", "courtside"}
        assert payload["freshness"]["fresh_outcomes"] == 6
        assert payload["home_team"] == "Duke"


@pytest.mark.parametrize("route", ["cfb", "cbb"])
def test_college_event_names_use_confirmed_team_catalog(raw, league, clock, route):
    # Event lists and market groups may contain different abbreviations for the
    # same IDs. Both must resolve to the provider's school names.
    for team in raw["events"][0]["eventTeams"]:
        team["name"] = "HOME" if team["sideIndex"] == 1 else "AWAY"
    groups = raw["props"]["data"]["odds"]["arbitrary"]["periodTypes"]["arbitrary"]["pregame"]
    for group in groups.values():
        for team in values(group["eventTeams"]):
            team["name"] = "HOM" if team["sideIndex"] == 1 else "AWA"
    result = Normalizer().parse(
        replace(league, route=route),
        "props",
        raw["props"]["data"],
        raw["sources"],
        raw["bets"],
        raw["periods"],
        raw["events"],
        raw["people"],
        raw["teams"],
        clock.now(),
    )
    assert result.events[0].home == "Home Team"
    assert result.events[0].away == "Away Team"
    assert result.quotes


@pytest.mark.parametrize("sport", ["nba_basketball", "ncaab_basketball"])
def test_missing_player_id_keeps_professional_guard_and_rejects_ambiguous_college_players(
    repo, board, clock, sport
):
    source = board("props")
    config = DEFAULT_LEAGUES[sport]
    event = replace(source.events[0], league_key=sport)
    source = replace(
        source,
        league=League(sport, config["title"], config["route"], "42"),
        events=(event,),
        quotes=tuple(replace(q, event_id=event.id) for q in source.quotes),
    )
    raw = snapshot(board, clock)
    raw[0]["sport_key"] = SPORT_KEYS[sport]
    book = raw[0]["bookmakers"][0]
    book["markets"] = book["markets"][2:]
    for outcome in book["markets"][0]["outcomes"]:
        outcome["player_id"] = None
    if sport == "ncaab_basketball":
        ambiguous = replace(source.quotes[0], player_id="another-player")
        repo.save(replace(source, quotes=(*source.quotes, ambiguous)))
    else:
        repo.save(replace(source, quotes=()))
    result = BulkOdds(sport, tuple(Event.model_validate(e) for e in raw), raw, {}, clock.now(), 0, 0)
    output, counts = boards(result, repo)
    assert not any(b.quotes for b in output)
    reason = "ambiguous_players" if sport == "ncaab_basketball" else "props_without_confirmed_player_id"
    assert counts[reason] == 3
