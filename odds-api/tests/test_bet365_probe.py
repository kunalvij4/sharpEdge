from scripts.probe_bet365 import classify, payload_signals, safe_text, safe_url


def test_challenge_and_location_pages_never_count_as_market_access():
    assert classify(403, "markets: access denied", [object()]) == "access_blocked"
    assert classify(200, "Verify you are human", [object()]) == "access_blocked"
    assert classify(200, "Unable to verify your location", [object()]) == "location_restricted"
    assert classify(503, "", []) == "http_error"
    assert classify(None, "", [], "net::ERR_CONNECTION_RESET") == "navigation_error"


def test_wire_signals_require_records_and_do_not_imply_validation():
    signals = payload_signals(b"\x14OVInPlay_1\x01F|EV;ID=1;|MA;ID=2;|PA;ID=3;OD=10/11;|")
    assert signals["records"] == {"EV": 1, "MA": 1, "PA": 1}
    assert signals["priced_participant_records"] == 1
    assert classify(200, "NBA", [signals]) == "market_payload_candidates_unvalidated"
    assert payload_signals("NBA: compare odds and player points")["records"] == {}
    assert classify(200, "NBA player points", []) == "page_loaded_no_market_payload"


def test_sanitization_omits_url_credentials_and_tokens():
    assert safe_url("https://user:secret@va.bet365.com/sports?token=secret#session") == (
        "https://va.bet365.com/sports"
    )
    assert "opaque" in safe_url("https://va.bet365.com/" + "a" * 100)
    assert safe_text("Contact someone@example.com or https://host/path?secret=value") == (
        "Contact [email] or [URL]"
    )
