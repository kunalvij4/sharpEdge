import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest


START = datetime(2026, 10, 26, 18, tzinfo=timezone.utc)


def event(event_id="event-1", price=2.2):
    return {
        "event_id": event_id, "home_team": "Home", "away_team": "Away",
        "commence_time": START.isoformat(),
        "markets": {"moneyline": {"odds_data": {
            "DraftKings": {"home_odds": price, "away_odds": 1.9},
        }}},
    }


@pytest.mark.parametrize("seconds_before, eligible", [
    (601, False), (600, True), (599, True), (1, True), (0, False), (-1, False), (-600, False),
])
def test_only_last_ten_minutes_before_start_are_persisted(closing_store, seconds_before, eligible):
    observed = START - timedelta(seconds=seconds_before)
    count = closing_store.store_event("NBA", event(), observed)

    assert count == (2 if eligible else 0)
    rows = closing_store.get_event("event-1", now=START)
    assert len(rows) == (2 if eligible else 0)


def test_last_price_replaces_same_bet_without_accumulating_history(closing_store):
    first = START - timedelta(minutes=10)
    second = START - timedelta(minutes=5)
    closing_store.store_event("NBA", event(price=2.2), first)
    closing_store.store_event("NBA", event(price=2.4), second)
    rows = closing_store.get_event("event-1", now=START)

    assert len(rows) == 2
    home = next(row for row in rows if row["side"] == "home")
    assert home["odds"] == 2.4
    assert home["observed_at"] == second.isoformat(timespec="microseconds")
    assert home["expires_at"] == int(second.timestamp()) + 7 * 24 * 3600


def test_older_or_duplicate_observation_cannot_overwrite_newer_price(closing_store):
    latest = START - timedelta(minutes=1)
    closing_store.store_event("NBA", event(price=2.4), latest)
    assert closing_store.store_event("NBA", event(price=2.1), START - timedelta(minutes=5)) == 0
    assert closing_store.store_event("NBA", event(price=2.1), latest) == 0
    home = next(row for row in closing_store.get_event("event-1", now=START) if row["side"] == "home")
    assert home["odds"] == 2.4


def test_started_event_cannot_change_the_final_pre_start_price(closing_store):
    closing_store.store_event("NFL", event(price=2.4), START - timedelta(seconds=1))
    assert closing_store.store_event("NFL", event(price=3), START + timedelta(seconds=1)) == 0
    assert next(row for row in closing_store.get_event("event-1", now=START) if row["side"] == "home")["odds"] == 2.4


def test_event_query_isolated_and_expired_rows_are_hidden_before_ttl_deletion(closing_store):
    observed = START - timedelta(minutes=5)
    closing_store.store_event("NBA", event("event-1"), observed)
    closing_store.store_event("NBA", event("event-2"), observed)
    assert {row["event_id"] for row in closing_store.get_event("event-1", now=START)} == {"event-1"}
    assert closing_store.get_event("event-1", now=observed + timedelta(days=7)) == []
    # The emulator leaves physical TTL rows present, exercising our read filter.
    assert closing_store.client.scan(TableName=closing_store.table_name)["Count"] == 4


def test_last_known_prices_for_missing_quotes_remain_available(closing_store):
    first = event()
    closing_store.store_event("NBA", first, START - timedelta(minutes=10))
    updated = event(price=2.5)
    del updated["markets"]["moneyline"]["odds_data"]["DraftKings"]["away_odds"]
    closing_store.store_event("NBA", updated, START - timedelta(minutes=5))
    rows = closing_store.get_event("event-1", now=START)
    assert len(rows) == 2
    assert next(row for row in rows if row["side"] == "away")["odds"] == 1.9


def test_players_lines_books_and_sides_have_distinct_stable_bet_keys(closing_store):
    game = event()
    game["markets"] = {"props": {"player_points": {
        player: {line: {book: {"over_odds": 2.2, "under_odds": 1.9} for book in ("FanDuel", "DraftKings")}
                 for line in ("20", "21.5")}
        for player in ("Player A", "Player B")
    }}}
    assert closing_store.store_event("NBA", game, START - timedelta(minutes=5)) == 16
    rows = closing_store.get_event("event-1", now=START)
    assert len({row["bet_key"] for row in rows}) == 16
    same = copy.deepcopy(game)
    for player in same["markets"]["props"]["player_points"].values():
        player["20.0"] = player.pop("20")
    closing_store.store_event("NBA", same, START - timedelta(minutes=1))
    assert len(closing_store.get_event("event-1", now=START)) == 16


def test_event_lookup_reads_every_page(closing_store, monkeypatch):
    closing_store.store_event("NBA", event(), START - timedelta(minutes=5))
    original = closing_store.client.query
    query = Mock(side_effect=lambda **kwargs: original(**{**kwargs, "Limit": 1}))
    monkeypatch.setattr(closing_store.client, "query", query)

    assert len(closing_store.get_event("event-1", now=START)) == 2
    assert query.call_count >= 2
    assert "ExclusiveStartKey" in query.call_args_list[1].kwargs


def test_naive_timestamps_are_rejected(closing_store):
    with pytest.raises(ValueError, match="timezone"):
        closing_store.store_event("NBA", event(), START.replace(tzinfo=None))


def test_offset_commence_time_is_compared_in_utc(closing_store):
    game = event()
    game["commence_time"] = "2026-10-26T14:00:00-04:00"
    assert closing_store.store_event("NBA", game, START - timedelta(minutes=5)) == 2
