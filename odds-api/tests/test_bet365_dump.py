from scripts.capture_bet365_markets import records
from scripts.organize_bet365_dump import organize, prices


def row(kind, **fields):
    return {"type": kind, "fields": fields}


def message(rows):
    return {
        "received_at": "2026-10-21T20:00:00+00:00",
        "stage": "home",
        "source_url": "https://www.va.bet365.com/pullpodapi/gethomepagepods",
        "records": rows,
    }


def fixture_rows():
    return [
        row("PA", L3="NBA", FD="Away @ Home", OI="event1", BC="20261022001000"),
        row("MG", SY="cpmg"),
        row("MA", SY="cpce", NA="Money", MA="960"),
        row("PA", L3="NBA", OI="event1", ID="away-line", FI="money1", OD="37/25", SU="0"),
        row("PA", L3="NBA", OI="event1", ID="home-line", FI="money1", OD="25/44", SU="0"),
    ]


def test_wire_parser_keeps_equals_in_values_and_omits_credential_fields():
    result = records("\x14topic\x01F|PA;ID=1;NA=A=B;OD=10/11;sessionToken=secret;|")
    assert result == [row("PA", ID="1", NA="A=B", OD="10/11")]
    assert prices("25/44") == {"fractional": "25/44", "decimal": 1.56818182, "american": -176}


def test_moneylines_deduplicate_and_match_visible_pair_without_inventing_start_timezone():
    data = organize(
        [message(fixture_rows()), message(fixture_rows())],
        pages=[{"text": "Away\nPitcher A\nHome\nPitcher B\n+148\n-176\nStats"}],
    )
    event = data["leagues"][0]["events"][0]
    assert len(event["moneyline"]["outcomes"]) == 2
    assert event["moneyline"]["page_text_price_pair_matches"]
    assert event["start_time_utc"] is None
    assert not event["start_timezone_verified"]
    assert data["summary"]["moneyline_outcomes"] == 2


def test_quick_pick_threshold_preserves_settlement_and_excludes_parlay():
    rows = fixture_rows() + [
        row("EV", IT="#QP#P1#N1#"),
        row("MG", NA="Points"),
        row("MA", NA="Player A", PD="#AC#P55#", N2="Away @ Home", L3="NBA"),
        row("PA", ID="prop1", FI="prop-instance", MA="181446", ED="25", OD="5/4"),
        row("CL", IT="#PB#"),
        row("MG", SY="pbc", NA="Parlay"),
        row("MA", NA="Player A", PD="#AC#P55#", N2="Away @ Home", L3="NBA"),
        row("PA", ID="not-prop", OD="20/1"),
    ]
    data = organize([message(rows)])
    prop = data["leagues"][0]["events"][0]["player_props"][0]
    assert prop["player"] == "Player A"
    assert prop["selections"][0]["threshold"] == 25
    assert prop["selections"][0]["comparison"] is None
    assert prop["mapped_api_market"] is None
    assert data["summary"]["player_prop_selections"] == 1


def test_columnar_scorer_prices_keep_player_and_column_associations():
    rows = [
        row("MG", SY="ppg", L3="NFL", PD="#PPP#F123#", NA="Away @ Home"),
        row("PA", NA="TD Scorer", TL="#PPP#F123#I1#"),
        row("EV", IT="#PPP#F123#"),
        row("MG", SY="pps", L3="NFL", ID="M120592", IT="#PPP#F123#I1#G120592#"),
        row("MA", NA="Player / Last 5", SY="phs"),
        row("PA", NA="Player A", PD="#AC#P5#"),
        row("PA", NA="Player B", PD="#AC#P6#"),
        row("MA", SY="pho"),
        row("CO", NA="Anytime"),
        row("PA", ID="p1", OD="1/2"),
        row("PA", ID="p2", OD="2/1"),
        row("CO", NA="2+"),
        row("PA", ID="p3", OD="8/1"),
        row("PA", ID="p4", OD="12/1"),
    ]
    data = organize([message(rows)])
    props = data["leagues"][1]["events"][0]["player_props"]
    assert len(props) == 2
    assert props[0]["source_label"] == "TD Scorer"
    assert props[0]["player"] == "Player A"
    assert [s["price"]["american"] for s in props[0]["selections"]] == [-200, 800]
    assert [s["source_selection_label"] for s in props[0]["selections"]] == ["Anytime", "2+"]


def test_ambiguous_fixture_names_stay_unresolved_for_player_props():
    rows = fixture_rows() + [
        row("PA", L3="NBA", FD="Away @ Home", OI="event2"),
        row("EV", IT="#QP#P1#N1#"),
        row("MG", NA="Points"),
        row("MA", NA="Player A", PD="#AC#P55#", N2="Away @ Home", L3="NBA"),
        row("PA", ID="prop1", FI="prop-instance", ED="25", OD="5/4"),
    ]
    data = organize([message(rows)])
    prop_event = next(e for e in data["leagues"][0]["events"] if e["player_props"])
    assert prop_event["source_event_id"] is None
