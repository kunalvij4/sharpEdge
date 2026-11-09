from dataclasses import replace
from decimal import Decimal

import pytest
from test_bet365_league_dump import capture, row
from test_bet365_streaming import post
from test_bet365_streaming import stream as stream_fixture

from scripts.capture_bet365_league import captured_market, fixture_routes
from scripts.organize_bet365_league_dump import organize_leagues
from scripts.verify_bet365_dump import verify

stream = stream_fixture


def test_only_priced_payloads_for_the_same_fixture_avoid_duplicate_prop_navigation():
    message = capture()
    message["stage"] = "nba_event_123"
    message["records"][3]["fields"].update(SY="mgh", NA="Points O/U")
    assert captured_market([message], "nba_event_123", "Points O/U")
    assert not captured_market([message], "nba_event_456", "Points O/U")
    for record in message["records"]:
        record["fields"].pop("OD", None)
    assert not captured_market([message], "nba_event_123", "Points O/U")


def native_message(now, start):
    return {
        "stage": "nhl_event_source_fixture_shots",
        "received_at": now.isoformat(),
        "source_url": "https://www.nj.bet365.com/contentdata/matchbettingcontentapi/markets",
        "records": [
            row("CL", L3="NHL"),
            row("EV", CC="NHL", OI="source-fixture", N2="Away", N3="Home", BC=start.strftime("%Y%m%d%H%M%S")),
            row("MG", ID="170600", NA="Shots on Goal", SY="mgh"),
            row("MA", SY="dv", PF="source-fixture", FI="native-market"),
            row("PA", ID="PCnative-price", NA="Player A", PD="#AC#P123#"),
            row("MA", SY="dw", PF="source-fixture", FI="native-market"),
            row("CO", SY="ipg", NA="1"),
            row("PA", ID="native-price", FI="native-market", OD="1/1"),
        ],
    }


def test_native_milestone_keeps_its_own_market_and_never_fabricates_an_under(stream, clock):
    repo, _, client, seed, _ = stream
    board, payload = seed("nhl_hockey")
    q = replace(
        board.quotes[0],
        market="player_shots_on_goal",
        player_id="canonical-player",
        description="Player A",
        point=Decimal("1.5"),
        name="Over",
    )
    repo.save(replace(board, kind="props", quotes=(q,)))
    message = native_message(clock.now(), board.events[0].start)
    report = organize_leagues([message])
    assert verify(report, [message])["source_checks_passed"]
    payload["messages"].append(message)
    result = post(client, payload)
    assert result.status_code == 200
    assert result.json()["counts"]["native_prop_selections"] == 1
    assert result.json()["counts"]["offered_prop_selections"] == 1
    response = client.get(
        f"/v1/events/{board.events[0].id}/props?freshOnly=true&oddsFormat=american",
        headers={"X-API-Key": "product-key"},
    )
    bet = next(book for book in response.json()["bookmakers"] if book["key"] == "bet365")
    assert bet["markets"][0]["key"] == "player_shots_on_goal_1plus"
    assert bet["markets"][0]["outcomes"] == [{"name": "Yes", "price": 100, "description": "Player A"}]


def test_native_player_column_mismatch_is_rejected(clock):
    from datetime import timedelta

    message = native_message(clock.now(), clock.now() + timedelta(days=1))
    message["records"][-1]["fields"]["ID"] = "another-player"
    assert organize_leagues([message])["normalization_issues"][0]["type"] == "native_player_order_mismatch"


def test_event_props_use_only_published_fixture_links_for_requested_league():
    messages = [
        {
            "stage": "nhl_lines",
            "records": [
                row("PA", L3="NHL", FD="Away @ Home", OI="fixture", PD="#AC#B17#D19#E123#F19#"),
                row("PA", L3="NFL", FD="Wrong @ Sport", OI="wrong", PD="#AC#B12#D19#E456#F19#"),
                row("PA", L3="NHL", FD="Not @ Event", OI="menu", PD="#AC#B17#D48#E972#"),
                row("PA", L3="NHL", FD="Away @ Home", OI="fixture", PD="#AC#B17#D19#E123#F19#"),
            ],
        }
    ]
    assert fixture_routes(messages, "nhl") == [("fixture", "#AC#B17#D19#E123#F19#")]
    assert fixture_routes(messages, "nba") == []


@pytest.mark.parametrize(
    "league,label,market",
    [
        ("nba_basketball", "Points O/U", "player_points"),
        ("ncaab_basketball", "Points O/U", "player_points"),
        ("nfl_football", "Pass Yds O/U", "player_pass_yds"),
        ("ncaaf_football", "Pass Yds O/U", "player_pass_yds"),
        ("nhl_hockey", "Shots on Goal O/U", "player_shots_on_goal"),
    ],
)
def test_verified_props_reach_shared_store_and_public_props_route_for_every_league(
    stream, clock, league, label, market
):
    repo, _, client, seed, _ = stream
    board, payload = seed(league)
    template = board.quotes[0]
    props = tuple(
        replace(
            template,
            market=market,
            player_id="canonical-player",
            description="Player A",
            point=Decimal("19.5"),
            name=side,
        )
        for side in ("Over", "Under")
    )
    repo.save(replace(board, kind="props", quotes=props))
    message = capture()
    message.update(
        stage=board.league.title.lower() + "_event_fixture_props", received_at=clock.now().isoformat()
    )
    message["records"][0]["fields"]["L3"] = board.league.title
    message["records"][2]["fields"]["NA"] = label
    message["records"][3]["fields"].update(
        FI="source-fixture", NA="Away @ Home", BC=board.events[0].start.strftime("%Y%m%d%H%M%S")
    )
    payload["messages"].append(message)
    result = post(client, payload)
    assert result.status_code == 200
    assert result.json()["counts"]["offered_prop_selections"] == 2
    assert result.json()["counts"]["props_selections"] == 2
    response = client.get(
        f"/v1/events/{board.events[0].id}/props?freshOnly=true&oddsFormat=american",
        headers={"X-API-Key": "product-key"},
    )
    assert response.status_code == 200
    books = {book["key"]: book for book in response.json()["bookmakers"]}
    assert "bet365" in books and len(books) == 2
    assert books["bet365"]["markets"][0]["key"] == market
    outcomes = books["bet365"]["markets"][0]["outcomes"]
    assert {outcome["name"] for outcome in outcomes} == {"Over", "Under"}
    assert all(outcome["description"] == "Player A" and outcome["point"] == 19.5 for outcome in outcomes)
