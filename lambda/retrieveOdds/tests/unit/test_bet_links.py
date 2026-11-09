import importlib
from urllib.parse import parse_qs, urlsplit

import pytest


def enricher(**kwargs):
    return importlib.import_module("odds_pipeline.bet_links").BetLinkEnricher(**kwargs)


def test_supplied_code_preserves_selection_path_and_replaces_attribution_once():
    row = {"bet_link": {"provider": "unabated", "url": (
        "https://www.gambly.com/deeplink/odds/7/1/-3.5?utm_campaign=old&x=y&utm_campaign=duplicate"
    )}}
    service = enricher()
    assert service.enrich({"spreads": [row]}) == {"provided": 1, "event": 0, "unavailable": 0}
    first = row["bet_link"]["url"]
    assert urlsplit(first).path == "/deeplink/odds/7/1/-3.5"
    assert parse_qs(urlsplit(first).query) == {"utm_campaign": ["sharpedge"], "x": ["y"]}
    service.enrich({"spreads": [row]})
    assert row["bet_link"]["url"] == first


def test_propline_event_links_and_direct_book_links_are_passed_through():
    rows = [
        {"bet_link": {"provider": "propline", "url": "https://sportsbook.draftkings.com/event/1?x=y"}},
        {"bet_link": {"provider": "unabated", "url": "https://sportsbook.fanduel.com/addToBetslip?selectionId=7"}},
    ]
    original = [row["bet_link"]["url"] for row in rows]
    assert enricher().enrich({"props": rows}) == {"provided": 1, "event": 1, "unavailable": 0}
    assert [row["bet_link"]["url"] for row in rows] == original
    assert rows[0]["bet_link"]["status"] == "event_support"


@pytest.mark.parametrize("value", [None, "", "javascript:alert(1)", "http://book.example/", "https://[",
                                  "https://user:password@book.example/", {"url": "https://book.example/"}])
def test_invalid_links_leave_no_clickable_url(value):
    link = {"provider": "unabated", "url": value}
    assert enricher().prepare(link) == "unavailable"
    assert "url" not in link


def test_missing_links_and_provider_ids_never_trigger_lookup_or_cache_calls(monkeypatch):
    def forbid(*args, **kwargs):
        pytest.fail("Returned links must not make generation or cache calls")

    monkeypatch.setattr("requests.sessions.Session.request", forbid)
    monkeypatch.setattr("odds_pipeline.cache._get_client", forbid)
    monkeypatch.setenv("REDIS_URL", "rediss://unused.invalid:6379")
    rows = [{}, {"line": 20.5, "bet_link": {"provider": "unabated", "market_line_id": "1", "market_source_id": "7"}}]
    service = importlib.import_module("odds_pipeline.bet_links").BetLinkEnricher.from_env()
    assert service.enrich({"props": rows}) == {"provided": 0, "event": 0, "unavailable": 2}


def test_comparisons_and_arb_legs_keep_their_own_returned_urls():
    comparison = {"provider": "propline", "url": "https://sportsbook.draftkings.com/event/2"}
    alternate = {"provider": "unabated"}
    over = {"provider": "unabated", "url": "https://www.gambly.com/deeplink/odds/7/1/20.5"}
    under = {"provider": "propline", "url": "https://sports.betmgm.com/event/3"}
    ev = {"props": [{"other_books": [{"bet_link": comparison}], "over_other_books": [{"bet_link": alternate}]}]}
    arb = {"props": [{"bet_link1": over, "bet_link2": under}]}
    enricher().attach_related(ev, arb)
    assert comparison["url"] == "https://sportsbook.draftkings.com/event/2"
    assert comparison["status"] == "event_support"
    assert over["url"].endswith("/20.5?utm_campaign=sharpedge")
    assert under["url"] == "https://sports.betmgm.com/event/3"
    assert "url" not in alternate


def test_partner_environment_defaults_and_override(monkeypatch):
    cls = importlib.import_module("odds_pipeline.bet_links").BetLinkEnricher
    monkeypatch.delenv("UNABATED_PARTNER_CODE", raising=False)
    assert cls.from_env().partner_code == "sharpedge"
    monkeypatch.setenv("UNABATED_PARTNER_CODE", "replacement")
    assert cls.from_env().partner_code == "replacement"


def test_app_only_courtside_link_is_carried_without_web_url():
    link = {"provider": "propline", "app_url": "courtside://fixture/abc"}
    assert enricher().enrich({"props": [{"bet_link": link}]}) == {"provided": 0, "event": 1, "unavailable": 0}
    assert link == {"provider": "propline", "app_url": "courtside://fixture/abc", "status": "event_support"}


def test_web_and_https_app_links_are_both_retained():
    link = {"provider": "propline", "url": "https://www.prophetx.co/event/1",
            "app_url": "https://app.prophetx.co/fixture/1"}
    enricher().prepare(link)
    assert link["url"] == "https://www.prophetx.co/event/1"
    assert link["app_url"] == "https://app.prophetx.co/fixture/1"


@pytest.mark.parametrize("app", ["javascript:alert(1)", "file:///etc/passwd", "https://user:secret@book.example/"])
def test_invalid_app_urls_are_discarded(app):
    link = {"provider": "propline", "app_url": app}
    assert enricher().prepare(link) == "unavailable"
    assert "app_url" not in link
