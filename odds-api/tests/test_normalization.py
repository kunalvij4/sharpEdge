from copy import deepcopy

import pytest

from odds_api.domain.models import Availability
from odds_api.infrastructure.normalization import Normalizer, link_with_partner, timestamp


def prop_line(raw):
    return raw["props"]["data"]["odds"]["arbitrary"]["periodTypes"]["arbitrary"]["pregame"]["ignored"][
        "sides"
    ]["over"]["marketSourceLines"]["whatever"]


def test_moneylines_and_all_discovered_books(raw, board):
    source = {**raw["sources"][0], "id": 902, "name": "New Book"}
    raw["sources"].append(source)
    group = raw["moneyline"]["data"]["odds"]["notAnIdentity"]["periodTypes"]["arbitrary"]["pregame"][
        "ignored"
    ]
    lines = group["sides"]["arbitraryAway"]["marketSourceLines"]
    lines["another"] = {**next(iter(lines.values())), "marketSourceId": 902, "marketLineId": 9999}
    result = board()
    assert result.complete
    assert len(result.books) == 2
    assert {q.name for q in result.quotes} == {"Home Team", "Away Team"}
    assert len(result.quotes) == 3


def test_props_alternates_and_missing_timestamps(board):
    result = board("props")
    assert result.complete
    assert len(result.quotes) == 3
    alt = next(q for q in result.quotes if q.alternate)
    assert alt.market == "player_points_alternate"
    assert alt.source_updated_at is None
    assert alt.description == "Sample Player"
    assert alt.deep_link is None


def test_missing_prop_points_skip_only_that_quote_and_preserve_valid_alternates(raw, board):
    prop_line(raw)["points"] = None
    result = board("props")
    assert not result.complete
    assert len(result.quotes) == 2
    assert all(q.point is not None for q in result.quotes)
    assert any(q.alternate and q.name == "Over" for q in result.quotes)
    assert any(q.name == "Under" for q in result.quotes)
    assert "missing_prop_points:bet=88:source=901" in result.warnings


def test_missing_event_team_context_skips_only_unresolved_event(raw, board):
    groups = raw["props"]["data"]["odds"]["arbitrary"]["periodTypes"]["arbitrary"]["pregame"]
    groups["bad_event"] = {**deepcopy(groups["ignored"]), "eventId": 9999, "eventTeams": []}
    result = board("props")
    assert result.quotes and not result.complete
    assert "unresolved_event:9999" in result.warnings


def test_period_markets_remain_distinct(raw, board):
    periods = raw["props"]["data"]["odds"]["arbitrary"]["periodTypes"]
    periods["quarter"] = deepcopy(periods["arbitrary"])
    periods["quarter"]["periodTypeId"] = 13
    result = board("props")
    assert len({q.market_id for q in result.quotes}) == 4
    assert "player_points_q1" in {q.market for q in result.quotes}


@pytest.mark.parametrize(
    "name,expected",
    [
        ("RBIs", "batter_rbis"),
        ("Pitcher Outs", "pitcher_outs"),
        ("Pitcher Hits Allowed", "pitcher_hits_allowed"),
        ("Pitcher Earned Runs", "pitcher_earned_runs"),
        ("Hitter Walks", "batter_walks"),
    ],
)
def test_observed_mlb_names_resolve_discovered_ids(raw, board, name, expected):
    raw["bets"][1]["name"] = name
    result = board("props")
    assert result.complete
    assert {q.market for q in result.quotes} == {expected, expected + "_alternate"}


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Second Inning", "2nd_1_innings"),
        ("First Five Innings", "1st_5_innings"),
        ("First Three Innings", "1st_3_innings"),
        ("First Seven Innings", "1st_7_innings"),
    ],
)
def test_observed_mlb_periods_remain_distinct_from_full_game(raw, board, name, expected):
    periods = raw["moneyline"]["data"]["odds"]["notAnIdentity"]["periodTypes"]
    periods["new_period"] = deepcopy(periods["arbitrary"])
    periods["new_period"]["periodTypeId"] = 9876
    raw["periods"].append({"id": 9876, "name": name})
    result = board()
    assert result.complete
    assert {q.market for q in result.quotes} == {"h2h", "h2h_" + expected}


def test_missing_period_definition_is_not_inferred_from_other_leagues(raw, board):
    period = raw["moneyline"]["data"]["odds"]["notAnIdentity"]["periodTypes"]["arbitrary"]
    period["periodTypeId"] = 9876
    result = board()
    assert not result.complete and not result.quotes
    assert any("period=9876" in warning for warning in result.warnings)


@pytest.mark.parametrize("subtype", ["Milestone", "Milestone-Alt", "strikeouts"])
def test_observed_subtypes_do_not_become_standard_over_under_props(raw, board, subtype):
    group = raw["props"]["data"]["odds"]["arbitrary"]["periodTypes"]["arbitrary"]["pregame"]["ignored"]
    group["betSubType"] = subtype
    result = board("props")
    assert not result.complete and not result.quotes
    assert any(warning.startswith("unsupported_bet_subtype:") for warning in result.warnings)


@pytest.mark.parametrize("change", [{"disabled": True}, {"statusId": 2}, {"price": None}])
def test_suspended_lines_are_preserved(raw, board, change):
    prop_line(raw).update(change)
    main = next(q for q in board("props").quotes if not q.alternate and q.name == "Over")
    assert main.state == Availability.SUSPENDED


def test_unknown_mapping_is_reported_and_prevents_replacement(raw, board):
    group = raw["props"]["data"]["odds"]["arbitrary"]["periodTypes"]["arbitrary"]["pregame"]["ignored"]
    group["betTypeId"] = 89
    result = board("props")
    assert not result.complete
    assert result.warnings[0].startswith("unsupported_mapping")


def test_explicit_id_mapping_supports_additional_bet_types(raw, league, clock):
    raw["bets"][1]["name"] = "Account-specific points label"
    result = Normalizer({"88": "player_points"}).parse(
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
    assert result.complete and result.quotes


def test_missing_board_is_not_successfully_empty(raw, league, clock):
    with pytest.raises(ValueError):
        Normalizer().parse(
            league,
            "props",
            {},
            raw["sources"],
            raw["bets"],
            raw["periods"],
            raw["events"],
            raw["people"],
            raw["teams"],
            clock.now(),
        )


def test_unknown_book_is_reported_without_erasing_supported_prices(raw, board):
    prop_line(raw)["marketSourceId"] = 999
    result = board("props")
    assert not result.complete
    assert "undiscovered_source:999" in result.warnings
    assert result.quotes and all(q.name == "Under" for q in result.quotes)


def test_missing_player_is_reported_without_mislabeling_quotes(raw, board):
    raw["people"] = {}
    result = board("props")
    assert not result.complete and not result.quotes
    assert "unresolved_player:300" in result.warnings


def test_out_of_scope_or_offline_book_not_actionable(raw, board):
    raw["sources"][0]["propsStatusId"] = 3
    assert all(q.state == Availability.SUSPENDED for q in board("props").quotes)


def test_links_are_tagged_once_and_not_reused_for_alternates():
    result = link_with_partner("https://gambly.com/bet?utm_campaign=old&x=1", "new")
    assert result.count("utm_campaign=") == 1
    assert "utm_campaign=new" in result
    assert link_with_partner("javascript:unsafe", "new") is None


def test_unknown_source_timestamp_is_null():
    assert timestamp(None) is None
    assert timestamp(0) is None
