from copy import deepcopy

import pytest

from scripts.organize_bet365_league_dump import organize_leagues
from scripts.verify_bet365_dump import verify


def row(kind, **fields):
    return {"type": kind, "fields": fields}


def capture():
    return {
        "stage": "nba_points_o_u",
        "received_at": "2026-10-21T23:00:00+00:00",
        "source_url": "https://www.nj.bet365.com/contentdata/matchmarketscontentapi/markets",
        "records": [
            row("CL", L3="NBA"),
            row("MG", SY="cms"),
            row("MA", NA="Points O/U", PD="#AC#B18#D43#E181378#"),
            row("MG", SY="fe", FI="fixture", NA="Away @ Home", MA="181378", BC="20261022001000"),
            row("MA", SY="dp", FI="prop-instance"),
            row("PA", ID="Pover-a", NA="Player A", PD="#AC#P123#"),
            row("PA", ID="Pover-b", NA="Player B", PD="#AC#P456#"),
            row("MA", SY="dc", NA="Over", FI="prop-instance"),
            row("PA", ID="over-a", HA="19.5", OD="1/1", OI="fixture"),
            row("PA", ID="placeholder", OD="", SU="1"),
            row("MA", SY="dc", NA="Under", FI="prop-instance"),
            row("PA", ID="under-a", HA="19.5", OD="4/5", OI="fixture"),
            row("PA", ID="under-b", HA="7.5", OD="10/11", OI="fixture"),
        ],
    }


def props(report):
    return report["leagues"][0]["events"][0]["player_props"]


def test_explicit_ou_keeps_both_sides_and_empty_cells_do_not_shift_players():
    report = organize_leagues([capture()])
    first, second = props(report)
    assert first["player"] == "Player A"
    assert first["point"] == 19.5
    assert first["both_sides_present"]
    assert [s["comparison"] for s in first["selections"]] == ["over", "under"]
    assert [s["price"]["american"] for s in first["selections"]] == [100, -125]
    assert second["player"] == "Player B"
    assert not second["both_sides_present"]
    assert second["selections"][0]["source_selection_id"] == "under-b"
    assert second["selections"][0]["player_source"]["record_index"] == 6
    assert not report["normalization_issues"]
    assert not report["websocket_deltas_applied"]


def test_truncated_price_column_is_rejected_instead_of_shifting_players():
    message = capture()
    del message["records"][9]
    report = organize_leagues([message])
    assert report["leagues"][0]["events"] == []
    assert report["normalization_issues"][0]["type"] == "column_length_mismatch"


def test_reordered_over_cells_fail_descriptor_id_crosscheck():
    message = capture()
    message["records"][8]["fields"]["ID"] = "some-other-player"
    report = organize_leagues([message])
    assert report["leagues"][0]["events"] == []
    assert report["normalization_issues"][0]["type"] == "player_order_mismatch"


def test_duplicate_snapshot_updates_prices_without_duplicate_player_lines():
    old = capture()
    new = deepcopy(old)
    new["records"][8]["fields"]["OD"] = "6/5"
    report = organize_leagues([old, new])
    assert len(props(report)) == 2
    selection = props(report)[0]["selections"][0]
    assert selection["price"]["american"] == 120
    assert selection["source"]["message_index"] == 1


@pytest.mark.parametrize("style", ["mgi", "mgh"])
def test_event_partial_resolves_fixture_from_pf_not_prop_market_instance(style):
    message = capture()
    group = message["records"][3]["fields"]
    group.update(SY=style, NA="Points O/U", ID="181378")
    del group["FI"]
    message["records"].insert(1, row("EV", CC="NBA", N2="Away", N3="Home", OI="fixture"))
    message["records"][5]["fields"]["PF"] = "fixture"
    report = organize_leagues([message])
    assert props(report)[0]["offering_context"] == "event_player_props"
    assert report["leagues"][0]["events"][0]["source_event_id"] == "fixture"
    assert props(report)[0]["selections"][0]["source_market_instance_id"] == "prop-instance"


def test_mixed_regions_and_websocket_deltas_are_rejected():
    message = capture()
    message["source_url"] = message["source_url"].replace("www.nj.", "www.va.")
    with pytest.raises(ValueError, match="region/host mismatch"):
        organize_leagues([message])
    message = capture()
    message["transport"] = "websocket"
    with pytest.raises(ValueError, match="HTTP snapshots only"):
        organize_leagues([message])


def test_verifier_detects_corrupted_prices_and_player_associations():
    message = capture()
    report = organize_leagues([message])
    assert verify(report, [message])["source_checks_passed"]
    props(report)[0]["selections"][0]["price"]["american"] = 999
    props(report)[0]["selections"][1]["column_row_index"] = 1
    result = verify(report, [message])
    assert not result["source_checks_passed"]
    assert result["errors"][0]["errors"] == ["price_mismatch"]
    assert result["errors"][1]["errors"] == ["column_row_mismatch"]


def test_league_moneyline_columns_keep_fixture_id_and_away_home_sides():
    message = capture()
    message["records"] = [
        row("CL", L3="NBA"),
        row("MG", SY="cmx", ID="1453"),
        row("MA", SY="ef"),
        row("PA", OI="fixture", NA="Away", N2="Home"),
        row("PA"),
        row("MA", SY="eo", NA="Money", MA="960"),
        row("PA", OI="fixture", FI="fixture", ID="away", OD="7/5"),
        row("PA", OI="fixture", FI="fixture", ID="home", OD="4/7"),
    ]
    report = organize_leagues([message], [{"text": "Away\nHome\n+140\n-175"}])
    event = report["leagues"][0]["events"][0]
    assert event["source_event_id"] == "fixture"
    assert [o["name"] for o in event["moneyline"]["outcomes"]] == ["Away", "Home"]
    assert event["moneyline"]["page_text_price_pair_matches"]
    assert report["summary"]["moneyline_events"] == 1


def test_named_player_without_stable_id_keeps_null_identity_and_source_descriptor():
    message = capture()
    del message["records"][5]["fields"]["PD"]
    report = organize_leagues([message])
    group = props(report)[0]
    assert group["player"] == "Player A"
    assert group["source_player_id"] is None
    assert group["source_player_descriptor_id"] == "Pover-a"
    assert group["both_sides_present"]
    assert verify(report, [message])["source_checks_passed"]


def test_unoffered_suspended_moneyline_is_reported_without_exporting_an_empty_fixture():
    message = capture()
    message["records"] = [
        row("CL", L3="NBA"),
        row("MG", SY="cmx"),
        row("MA", SY="ef"),
        row("PA", OI="fixture", NA="Away", N2="Home"),
        row("MA", SY="eo", NA="Money"),
        row("PA", OI="fixture", ID="away", OD="", SU="1"),
        row("PA", OI="fixture", ID="home", OD="", SU="1"),
    ]
    report = organize_leagues([message])
    assert report["summary"]["events"] == 0
    assert report["leagues"][0]["events"] == []
    assert report["normalization_issues"] == []
    assert report["source_unavailable_moneylines"][0]["event_id"] == "fixture"
    assert report["source_unavailable_moneylines"][0]["reason"] == "both_prices_unavailable"
