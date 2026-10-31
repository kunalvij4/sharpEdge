from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from odds_api.domain.models import Availability
from odds_api.http.app import create_app
from odds_api.infrastructure.bet365 import BOOK, boards, match_event
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.lease import CollectorLease


@pytest.fixture
def report(repo, board, clock):
    money, props = board(), board("props")
    future = replace(money.events[0], start=clock.now() + timedelta(days=1))
    money, props = replace(money, events=(future,)), replace(props, events=(future,))
    repo.save(money)
    repo.save(props)
    event = money.events[0]
    prop = next(q for q in props.quotes if q.market == "player_points")

    def selection(name, price=-110):
        return dict(
            side=name,
            comparison=name,
            source_selection_id="365-" + name,
            source_market_instance_id="365-market",
            price={"american": price},
            source={"received_at": clock.now().isoformat()},
        )

    return {
        "normalization_issues": [],
        "leagues": [
            dict(
                key=event.league_key,
                title="NBA",
                events=[
                    dict(
                        source_event_id="365-fixture",
                        home_team=event.home,
                        away_team=event.away,
                        start_time_source=event.start.strftime("%Y%m%d%H%M%S"),
                        moneyline=dict(
                            type="two_way_moneyline", outcomes=[selection("home"), selection("away", 120)]
                        ),
                        player_props=[
                            dict(
                                source_label="Points O/U",
                                player=prop.description,
                                point=float(prop.point),
                                offering_context="league_player_props",
                                both_sides_present=True,
                                selections=[selection("over"), selection("under")],
                            )
                        ],
                    )
                ],
            )
        ],
    }


def save_report(report, repo, clock):
    output, counts = boards(report, repo, clock.now())
    for board in output:
        repo.save(board)
    return output, counts


def bet_quotes(repo):
    return [r["quote"] for r in repo.quotes("nba_basketball") if r["book_key"] == "bet365"]


def test_disabled_bet365_is_hidden_even_when_old_rows_exist(repo, clock, report):
    save_report(report, repo, clock)
    assert bet_quotes(repo)
    settings = Settings(_env_file=None, api_keys="test-key", bet365_enabled=False)
    with TestClient(create_app(settings, repo, clock)) as client:
        headers = {"X-API-Key": "test-key"}
        games = client.get("/v1/sports/nba_basketball/odds", headers=headers).json()
        assert {b["key"] for e in games for b in e["bookmakers"]} == {"fixturebook"}
        event_id = games[0]["id"]
        props = client.get(f"/v1/events/{event_id}/props?bookmakers=bet365", headers=headers).json()
        assert props["bookmakers"] == []
        assert client.get("/v1/status", headers=headers).json()["bet365"]["enabled"] is False


def test_provider_leases_are_independent_but_each_is_exclusive(repo):
    with CollectorLease(repo.engine), CollectorLease(repo.engine, key=911712350):
        with pytest.raises(RuntimeError, match="Another collector"):
            with CollectorLease(repo.engine, key=911712350):
                pass


def test_merge_uses_existing_ids_and_exact_api_schema(repo, board, clock, report):
    original = [r["quote"] for r in repo.quotes("nba_basketball")]
    output, counts = save_report(report, repo, clock)
    assert counts["moneyline_selections"] == 2 and counts["props_selections"] == 2
    assert {q.event_id for q in bet_quotes(repo)} == {board().events[0].id}
    canonical = next(q for q in original if q.market == "player_points")
    assert all(
        q.player_id == canonical.player_id and q.description == canonical.description
        for q in bet_quotes(repo)
        if q.player_id
    )
    assert all(q.source_updated_at is None for q in bet_quotes(repo))
    assert len(repo.events("nba_basketball")) == 1
    settings = Settings(_env_file=None, api_keys="test-key", bet365_enabled=True)
    with TestClient(create_app(settings, repo, clock)) as client:
        headers = {"X-API-Key": "test-key"}
        money = client.get("/v1/sports/nba_basketball/odds", headers=headers)
        assert money.status_code == 200
        books = money.json()[0]["bookmakers"]
        assert {b["key"] for b in books} == {"fixturebook", "bet365"}
        assert next(b for b in books if b["key"] == "bet365")["title"] == "Bet365"
        props = client.get(f"/v1/events/{canonical.event_id}/props?bookmakers=bet365", headers=headers)
        assert props.status_code == 200
        assert props.json()["bookmakers"][0]["markets"][0]["key"] == "player_points"
    assert [r["quote"] for r in repo.quotes("nba_basketball") if r["book_key"] != "bet365"] == original


@pytest.mark.parametrize("mutation", ["line", "player", "market", "milestone", "ambiguous_player"])
def test_unshared_and_uncomparable_props_are_discarded(repo, board, clock, report, mutation):
    prop = report["leagues"][0]["events"][0]["player_props"][0]
    if mutation == "line":
        prop["point"] += 1
    elif mutation == "player":
        prop["player"] = "Another Player"
    elif mutation == "market":
        prop["source_label"] = "Unmapped O/U"
    elif mutation == "milestone":
        prop["offering_context"] = "homepage_same_game_parlay_plus"
    else:
        snapshot = board("props")
        repo.save(
            replace(
                snapshot,
                quotes=tuple(replace(q, player_id="ambiguous") for q in snapshot.quotes),
                complete=False,
            )
        )
    save_report(report, repo, clock)
    assert not any(q.player_id for q in bet_quotes(repo))


def test_provider_refreshes_cannot_remove_each_other_or_corrupt_event_lifecycle(repo, board, clock, report):
    output, _ = save_report(report, repo, clock)
    assert len(bet_quotes(repo)) == 4
    refreshed = board()
    repo.save(replace(refreshed, events=output[0].events))
    assert all(q.state == Availability.AVAILABLE for q in bet_quotes(repo))
    repo.save(replace(output[0], quotes=()))
    assert all(
        r["quote"].state == Availability.AVAILABLE
        for r in repo.quotes("nba_basketball")
        if r["book_key"] != "bet365"
    )
    # A late browser write cannot revert the canonical provider's final event.
    snapshot = board()
    repo.save(replace(snapshot, events=(replace(snapshot.events[0], status="final"),)))
    repo.save(output[0])
    assert repo.events("nba_basketball")[0]["status"] == "final"


def test_empty_api_refresh_preserves_legacy_bet365_support(repo, board, clock, report):
    save_report(report, repo, clock)
    assert len(bet_quotes(repo)) == 4
    repo.save(replace(board("props"), quotes=()))
    assert all(q.state == Availability.AVAILABLE for q in bet_quotes(repo) if q.player_id)
    assert all(q.state == Availability.AVAILABLE for q in bet_quotes(repo) if not q.player_id)


def test_late_legacy_capture_retains_support_after_empty_api_response(repo, board, clock, report):
    output, _ = boards(report, repo, clock.now())
    repo.save(replace(board("props"), quotes=()))
    for snapshot in output:
        repo.save(snapshot)
    assert any(q.player_id for q in bet_quotes(repo))


def test_capture_timestamp_and_expiry_are_never_refreshed_by_reimport(repo, clock, report):
    clock.value = 30
    save_report(report, repo, clock)
    assert all(q.collected_at == clock.origin for q in bet_quotes(repo))
    assert all(q.expires_at == clock.origin + timedelta(seconds=150) for q in bet_quotes(repo))
    clock.value = 151
    output, _ = boards(report, repo, clock.now())
    assert not any(b.quotes for b in output)


def test_ambiguous_fixtures_are_never_guessed(repo, board, clock, report):
    event = repo.events("nba_basketball")[0]
    source = report["leagues"][0]["events"][0]
    assert match_event(source, [event, {**event, "id": "doubleheader"}], clock.now()) is None
    source = deepcopy(source)
    source["home_team"], source["away_team"] = source["away_team"], source["home_team"]
    assert match_event(source, [event], clock.now()) is None


def test_bet365_failure_expiry_and_support_filter_do_not_hide_other_books(repo, board, clock, report):
    save_report(report, repo, clock)
    settings = Settings(_env_file=None, api_keys="test-key", bet365_enabled=True)
    with TestClient(create_app(settings, repo, clock)) as client:
        clock.value = 151
        # The browser has failed; ordinary collection keeps refreshing independently.
        money = board()
        repo.save(money)
        response = client.get("/v1/sports/nba_basketball/odds", headers={"X-API-Key": "test-key"})
        assert {b["key"] for b in response.json()[0]["bookmakers"]} == {"fixturebook"}
        assert BOOK.key == "bet365"
