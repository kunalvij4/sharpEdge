from dataclasses import replace
from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from odds_api.application.services import OddsQueryService, QueryError
from odds_api.domain.models import Availability, Event, identity
from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings


def service(repo, clock):
    return OddsQueryService(repo, clock, 90, 3600, {"h2h", "player_points", "player_points_alternate"})


@pytest.mark.parametrize("delta", [-1, 0, 0.001])
def test_pregame_ingestion_uses_current_time_not_snapshot_time(repo, board, clock, delta):
    snapshot = board()
    event = replace(snapshot.events[0], start=clock.now() + timedelta(seconds=delta))
    repo.save(replace(snapshot, events=(event,), collected_at=clock.now() - timedelta(hours=1)))
    assert len(repo.events("nba_basketball")) == (1 if delta > 0 else 0)
    assert len(repo.quotes("nba_basketball")) == (2 if delta > 0 else 0)


def test_reads_expire_at_exact_kickoff_before_database_cleanup(repo, board, clock):
    snapshot = board("props")
    event = replace(snapshot.events[0], start=clock.now() + timedelta(seconds=1))
    repo.save(replace(snapshot, events=(event,)))
    query = service(repo, clock)
    assert query.event_props(event.id)["bookmakers"]
    clock.value = 1
    # Simulate both providers being down: no collection has run since kickoff.
    assert repo.event(event.id) is not None
    assert query.events("nba_basketball") == []
    assert query.odds("nba_basketball", markets="all_props") == []
    for method in (query.event_props, query.event_odds):
        with pytest.raises(QueryError) as error:
            method(event.id)
        assert error.value.status == 404


def test_cleanup_deletes_all_children_preserves_future_and_prevents_reinsertion(repo, board, clock):
    snapshot = board("props")
    expired = replace(snapshot.events[0], start=clock.now() + timedelta(seconds=1))
    future = replace(expired, source_id="future", start=clock.now() + timedelta(days=1))
    future_quotes = tuple(replace(q, event_id=future.id) for q in snapshot.quotes)
    incoming = replace(snapshot, events=(expired, future), quotes=(*snapshot.quotes, *future_quotes))
    repo.save(incoming)
    clock.value = 1
    assert repo.prune_started() == 1
    assert repo.prune_started() == 0
    assert repo.event(expired.id) is None
    assert repo.event(future.id) is not None
    repo.save(incoming)  # Late fetch/browser response cannot resurrect the event.
    for table, expected in (("events", 1), ("markets", 2), ("selections", 3), ("odds", 3)):
        with repo.engine.connect() as conn:
            assert conn.scalar(select(func.count()).select_from(repo.t[table])) == expected
    assert {r["quote"].event_id for r in repo.quotes("nba_basketball")} == {future.id}


def test_changed_kickoff_deletes_previously_future_event(repo, board, clock):
    snapshot = board()
    repo.save(snapshot)
    past = replace(snapshot.events[0], start=clock.now())
    repo.save(replace(snapshot, events=(past,), complete=False))
    assert repo.event(past.id) is None
    assert repo.quotes("nba_basketball") == []


def test_migration_round_trip_preserves_ids_quotes_and_scope_history(repo, board, clock):
    snapshot = board("props")
    repo.save(snapshot)
    before = repo.quotes("nba_basketball")
    config = Config("alembic.ini")
    config.attributes["database_url"] = repo.engine.url.render_as_string(hide_password=False)
    command.downgrade(config, "0001")
    with repo.engine.connect() as conn:
        assert conn.scalar(select(repo.t["events"].c.league_key)) == "basketball_nba"
        assert conn.scalar(select(repo.t["events"].c.id)) == snapshot.events[0].id
    command.upgrade(config, "head")
    assert repo.ready()
    assert repo.quotes("nba_basketball") == before
    assert {league.key for league in repo.leagues()} == set(DEFAULT_LEAGUES)
    scope = next(
        s
        for s in repo.status(clock.now(), 90, 3600)["scopes"]
        if s["league"] == "nba_basketball" and s["kind"] == "props"
    )
    assert scope["last_success"] == clock.now()
    assert scope["selection_count"] == 3


@pytest.mark.parametrize(
    "old,new",
    [
        ("basketball_nba", "nba_basketball"),
        ("americanfootball_nfl", "nfl_football"),
        ("baseball_mlb", "mlb_baseball"),
    ],
)
def test_league_keys_preserve_opaque_event_identity(clock, old, new):
    event = Event("555", new, clock.now(), "Home", "Away", "pregame")
    assert event.id == identity("event", old, "555")
    settings = Settings(_env_file=None, leagues_json='{"' + old + '":{"title":"League","route":"league"}}')
    assert set(settings.leagues) == {new}


def test_conflicting_response_preserves_previous_valid_selection(repo, board, raw, clock):
    from copy import deepcopy

    repo.save(board("props"))
    previous = next(
        r["quote"]
        for r in repo.quotes("nba_basketball")
        if r["quote"].name == "Over" and not r["quote"].alternate
    )
    group = raw["props"]["data"]["odds"]["arbitrary"]["periodTypes"]["arbitrary"]["pregame"]["ignored"]
    lines = group["sides"]["over"]["marketSourceLines"]
    duplicate = deepcopy(lines["whatever"])
    duplicate.update(price=-150, modifiedOn=None)
    duplicate.pop("alternateLines", None)
    lines["duplicate"] = duplicate
    updated = board("props")
    assert not updated.complete
    repo.save(updated)
    quotes = [r["quote"] for r in repo.quotes("nba_basketball")]
    over = next(q for q in quotes if q.name == "Over" and not q.alternate)
    assert over == previous
    assert next(q for q in quotes if q.name == "Under").state == Availability.AVAILABLE
    response = service(repo, clock).event_props(updated.events[0].id)
    main = next(m for b in response["bookmakers"] for m in b["markets"] if m["key"] == "player_points")
    assert {o["name"] for o in main["outcomes"]} == {"Over", "Under"}
