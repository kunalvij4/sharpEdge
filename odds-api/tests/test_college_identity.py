from dataclasses import replace
from datetime import UTC, datetime, timedelta

import fakeredis
import pytest
from fastapi.testclient import TestClient

from odds_api.domain.college import SCHOOL_CANDIDATES, CollegePlayers, school_key
from odds_api.domain.models import League
from odds_api.http.app import create_app
from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings
from odds_api.infrastructure.normalization import Normalizer
from odds_api.infrastructure.propline import BulkOdds, Event
from odds_api.infrastructure.propline_normalization import boards
from odds_api.infrastructure.redis_repository import RedisRepository


@pytest.mark.parametrize(
    "aliases",
    [
        ("University test", "University test"),
        ("Connecticut", "UConn", "UConn Huskies", "CONN"),
        ("Akron", "AKR", "Akron Zips"),
        ("Iowa State", "ISU", "Iowa State Cyclones"),
        ("Mississippi", "Ole Miss", "Ole Miss Rebels"),
        ("Fairleigh Dickinson", "FDU", "FDU Knights"),
        ("UTSA", "Texas San Antonio", "UTSA Roadrunners"),
    ],
)
def test_common_school_names_have_one_identity(aliases):
    assert len({school_key(name) for name in aliases}) == 1


def test_school_context_matches_punctuation_but_preserves_opposing_namesakes():
    players = CollegePlayers("Michigan State", "Duke Blue Devils")
    players.add("D.J. Smith", "unabated-duke", "Duke")
    assert players.resolve("DJ Smith (DUKE)") == ("D.J. Smith (Duke)", school_key("Duke"), {"unabated-duke"})
    players.add("D.J. Smith", "unabated-msu", "Michigan State")
    assert players.resolve("DJ Smith") is None
    assert players.resolve("DJ Smith (Duke)")[2] == {"unabated-duke"}
    assert players.resolve("DJ Smith (Michigan State)")[2] == {"unabated-msu"}
    assert players.resolve("DJ Smith (Akron)") is None
    # Initials are not expanded into guessed given names.
    assert players.resolve("David Smith")[1] is None


def test_conflicting_ids_on_the_same_school_are_rejected():
    players = CollegePlayers("Duke", "Army")
    players.add("John Smith", "one", "Duke")
    players.add("John Smith", "two", "Duke")
    assert players.resolve("John Smith (DUKE)") is None


def test_ambiguous_school_alias_cannot_accidentally_equal_a_canonical_name():
    for alias, schools in SCHOOL_CANDIDATES.items():
        if len(schools) > 1:
            assert school_key(alias) not in schools


@pytest.mark.parametrize("backend", ["sql", "redis"])
@pytest.mark.parametrize(
    "stat,market_key",
    [
        ("Player Points", "player_points"),
        ("Points and Rebounds", "player_points_rebounds"),
        ("Points Rebounds Assists", "player_points_rebounds_assists"),
        ("Points Assists", "player_points_assists"),
        ("Rebounds Assists", "player_rebounds_assists"),
        ("Player Turnovers", "player_turnovers"),
        ("Steals Blocks", "player_blocks_steals"),
    ],
)
def test_school_and_name_unify_source_ids_and_retained_quotes_in_public_api(
    repo, raw, clock, backend, stat, market_key
):
    repository = (
        repo
        if backend == "sql"
        else RedisRepository(
            "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(decode_responses=True)
        )
    )
    raw["teams"]["20"]["name"] = "Duke"
    raw["teams"]["10"]["name"] = "Army"
    raw["people"]["300"].update(firstName="D.J.", lastName="Smith", teamId=20)
    raw["bets"][1]["name"] = stat
    league = League("ncaab_basketball", "NCAAB", "cbb", "42")
    canonical = Normalizer().parse(
        league,
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
    assert {q.description for q in canonical.quotes} == {"D.J. Smith (Duke)"}
    assert {q.market for q in canonical.quotes} == {market_key, market_key + "_alternate"}
    clock.origin = datetime.now(UTC)
    canonical = replace(
        canonical,
        events=tuple(replace(event, start=clock.now() + timedelta(days=1)) for event in canonical.events),
        quotes=tuple(
            replace(
                q,
                collected_at=clock.now(),
                source_updated_at=clock.now(),
                expires_at=clock.now() + timedelta(minutes=10),
            )
            for q in canonical.quotes
        ),
        collected_at=clock.now(),
    )
    repository.save(canonical)
    event = canonical.events[0]
    data = [
        {
            "id": "college-source",
            "sport_key": "basketball_ncaab",
            "home_team": "Duke Blue Devils",
            "away_team": "Army Black Knights",
            "commence_time": event.start.isoformat(),
            "bookmakers": [],
        }
    ]
    # Book identities differ, as do their player IDs and school-name spellings.
    for key, title, description, pid in (
        ("draftkings", "DraftKings", "DJ Smith (DUKE)", "espn:999"),
        ("fanduel", "FanDuel", "D.J. Smith", None),
    ):
        data[0]["bookmakers"].append(
            {
                "key": key,
                "title": title,
                "markets": [
                    {
                        "key": market_key,
                        "last_update": clock.now().isoformat(),
                        "outcomes": [
                            {
                                "name": side,
                                "description": description,
                                "point": 25.5,
                                "price": -110,
                                "player_id": pid,
                            }
                            for side in ("Over", "Under")
                        ],
                    }
                ],
            }
        )
    result = BulkOdds(league.key, tuple(Event.model_validate(e) for e in data), data, {}, clock.now(), 0, 0)
    output, counts = boards(result, repository)
    props = next(b for b in output if b.kind == "props")
    assert counts["school_matched_player_outcomes"] == 4
    assert {q.description for q in props.quotes} == {"D.J. Smith (Duke)"}
    assert {q.player_id for q in props.quotes} == {"300"}
    for board in output:
        repository.save(board)
    # Retained observations with a bare name must collapse into the same public
    # player without changing their saved timestamps or adding public fields.
    older = replace(
        props,
        quotes=tuple(replace(q, player_id="legacy-other-id", description="DJ Smith") for q in props.quotes),
    )
    repository.save(older)
    stored = repository.quotes(league.key)
    with TestClient(create_app(Settings(_env_file=None, api_keys="test"), repository, clock)) as api:
        response = api.get(f"/v1/events/{event.id}/props?freshOnly=true", headers={"X-API-Key": "test"})
        assert response.status_code == 200
        payload = response.json()
        for book in payload["bookmakers"]:
            for market in book["markets"]:
                outcomes = market["outcomes"]
                assert {q["description"] for q in outcomes} == {"D.J. Smith (Duke)"}
                if market["key"] == market_key:
                    assert len(outcomes) == 2
                assert all(set(q) == {"name", "price", "point", "description"} for q in outcomes)
    assert repository.quotes(league.key) == stored
