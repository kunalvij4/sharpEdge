import copy
from dataclasses import replace
from datetime import datetime, timedelta

import fakeredis
import pytest
from fastapi.testclient import TestClient
from test_redis_storage import future_board

from odds_api.application.prepared_odds import prepare_document, stored_event, stored_rows, wire_time
from odds_api.domain.models import Availability, Sportsbook
from odds_api.http.app import create_app
from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings
from odds_api.infrastructure.redis_repository import (
    REWRITE_DOCUMENT,
    RedisRepository,
    decode_document,
    encode,
)


@pytest.fixture
def prepared(repo, board, clock):
    moneyline, props = board(), board("props")
    moneyline = future_board(lambda: moneyline, clock)
    props = replace(
        props,
        events=moneyline.events,
        collected_at=clock.now(),
        quotes=tuple(
            replace(q, collected_at=clock.now(), source_updated_at=clock.now() if not q.alternate else None)
            for q in props.quotes
        ),
    )
    first = props.quotes[0]
    props = replace(
        props,
        quotes=(
            *props.quotes,
            replace(
                first, market="player_points_q1", period="q1", expires_at=clock.now() + timedelta(seconds=60)
            ),
            replace(first, point=first.point + 1, state=Availability.SUSPENDED),
        ),
    )
    book = Sportsbook("draftkings", "DraftKings", "propline")
    propline = replace(
        props,
        books=(book,),
        provider="propline",
        covered_markets=tuple({q.market for q in props.quotes}),
        quotes=tuple(replace(q, book_id=book.id) for q in props.quotes),
    )
    redis = RedisRepository(
        "", DEFAULT_LEAGUES, clock=clock, client=fakeredis.FakeRedis(decode_responses=True)
    )
    for repository in (repo, redis):
        for source in (moneyline, props, propline):
            repository.save(source)
    settings = Settings(
        _env_file=None,
        api_keys="fixture-key",
        propline_enabled=False,
        collected_ttl=90,
        propline_collected_ttl=600,
    )
    return redis, repo, settings, moneyline.events[0].id


@pytest.mark.parametrize("age", [0, 61, 90, 91, 601, 3601, 86400])
@pytest.mark.parametrize("odds_format", ["american", "decimal"])
@pytest.mark.parametrize(
    "query",
    [
        "/props",
        "/props?freshOnly=true",
        "/props?markets=player_points_alternate,player_points_q1&bookmakers=draftkings",
        "/odds?markets=h2h,player_points&bookmakers=fixturebook",
    ],
)
def test_prepared_responses_match_existing_contract(prepared, clock, age, odds_format, query):
    redis, sql, settings, event_id = prepared
    clock.value = age
    separator = "&" if "?" in query else "?"
    url = f"/v1/events/{event_id}{query}{separator}oddsFormat={odds_format}"
    headers = {"X-API-Key": "fixture-key"}
    with (
        TestClient(create_app(settings, sql, clock)) as old,
        TestClient(create_app(settings, redis, clock)) as new,
    ):
        expected = old.get(url, headers=headers)
        response = new.get(url, headers=headers)
        assert response.status_code == expected.status_code
        assert response.json() == expected.json()
        assert response.headers.get("X-Odds-Data-Status") == expected.headers.get("X-Odds-Data-Status")
        assert "_storage" not in response.text


@pytest.mark.parametrize("backend", ["sql", "redis"])
@pytest.mark.parametrize("odds_format", ["american", "decimal"])
@pytest.mark.parametrize("age", [0, 91, 601])
def test_every_provider_uses_same_outcome_fields_when_fresh_or_stale(
    prepared, clock, backend, odds_format, age
):
    redis, sql, settings, event_id = prepared
    repository = sql if backend == "sql" else redis
    clock.value = age
    headers = {"X-API-Key": "fixture-key"}
    path = f"/v1/events/{event_id}/odds?markets=h2h,player_points&oddsFormat={odds_format}"
    with TestClient(create_app(settings, repository, clock)) as api:
        response = api.get(path, headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert {b["key"] for b in payload["bookmakers"]} == {"fixturebook", "draftkings"}
        for book in payload["bookmakers"]:
            assert set(book) == {"key", "title", "last_update", "markets"}
            for market in book["markets"]:
                assert set(market) == {"key", "last_update", "outcomes"}
                for outcome in market["outcomes"]:
                    assert set(outcome) == (
                        {"name", "price"}
                        if market["key"] == "h2h"
                        else {"name", "price", "point", "description"}
                    )
        expected_fresh = {0: 6, 91: 2, 601: 0}[age]
        assert payload["freshness"]["fresh_outcomes"] == expected_fresh
        assert payload["freshness"]["stale_outcomes"] == 6 - expected_fresh
        filtered = api.get(path + "&freshOnly=true", headers=headers).json()
        assert filtered["freshness"]["fresh_outcomes"] == expected_fresh
        assert filtered["freshness"]["stale_outcomes"] == 0


@pytest.mark.parametrize("upgrade", ["rewrite", "collection"])
def test_old_prepared_freshness_is_hidden_and_removed_losslessly(prepared, board, clock, upgrade):
    redis, sql, settings, event_id = prepared
    key = redis.key("event:" + event_id)
    document = decode_document(redis.client.get(key))
    original_quotes = redis.quotes("nba_basketball")
    expiry = redis.client.pexpiretime(key)
    # Earlier v2 documents kept prop timestamps in public freshness blocks.
    for book in document["bookmakers"]:
        for market in book["markets"]:
            for outcome in market["outcomes"]:
                if outcome["_storage"]["player_id"] is not None:
                    outcome["freshness"] = {
                        "status": "fresh",
                        "actionable": True,
                        "age_seconds": 0,
                        **{
                            field: outcome["_storage"].pop(field)
                            for field in ("collected_at", "source_updated_at", "expires_at")
                        },
                    }
    old_value = encode(document)
    redis.client.set(key, old_value, keepttl=True)
    clock.value = 91
    path = f"/v1/events/{event_id}/odds?markets=h2h,player_points&oddsFormat=american"
    headers = {"X-API-Key": "fixture-key"}
    with (
        TestClient(create_app(settings, sql, clock)) as expected_api,
        TestClient(create_app(settings, redis, clock)) as api,
    ):
        expected = expected_api.get(path, headers=headers).json()
        assert api.get(path, headers=headers).json() == expected
        assert redis.client.get(key) == old_value
        if upgrade == "rewrite":
            assert redis.rewrite_event_documents("response")["candidate_events"] == 1
            assert redis.client.get(key) == old_value
            assert redis.rewrite_event_documents("response", dry_run=False)["rewritten_events"] == 1
            assert redis.rewrite_event_documents("response")["candidate_events"] == 0
        else:
            source = board("props")
            event = replace(source.events[0], start=datetime.fromisoformat(stored_event(document)["start"]))
            redis.save(replace(source, events=(event,), quotes=(), complete=False))
        assert api.get(path, headers=headers).json() == expected
    upgraded = decode_document(redis.client.get(key))
    assert all(
        "freshness" not in outcome
        for book in upgraded["bookmakers"]
        for market in book["markets"]
        for outcome in market["outcomes"]
    )
    assert redis.quotes("nba_basketball") == original_quotes
    assert redis.client.pexpiretime(key) == expiry


@pytest.mark.parametrize(
    "path",
    [
        "/v1/events/{event_id}/props?markets=h2h",
        "/v1/events/{event_id}/props?markets=unknown",
        "/v1/events/{event_id}/props?markets=all_props,player_points",
        "/v1/events/{event_id}/props?bookmakers=unknown",
        "/v1/events/{event_id}/props?oddsFormat=unknown",
        "/v1/events/{event_id}/props?commenceTimeFrom=2027-01-01T00:00:00",
        "/v1/events/{event_id}/props?commenceTimeFrom=2027-01-02T00:00:00Z&commenceTimeTo=2027-01-01T00:00:00Z",
        "/v1/events/missing/props",
        "/v1/sports/unknown/odds",
        "/v1/sports/nba_basketball/odds?markets=player_points",
        "/v1/sports/nba_basketball/odds?markets=h2h&oddsFormat=american",
    ],
)
def test_prepared_validation_and_sport_odds_match_existing_contract(prepared, clock, path):
    redis, sql, settings, event_id = prepared
    headers = {"X-API-Key": "fixture-key"}
    with (
        TestClient(create_app(settings, sql, clock)) as old,
        TestClient(create_app(settings, redis, clock)) as new,
    ):
        url = path.format(event_id=event_id)
        expected, response = old.get(url, headers=headers), new.get(url, headers=headers)
        assert response.status_code == expected.status_code
        assert response.json() == expected.json()


def test_latest_source_timestamp_handles_whole_and_fractional_seconds(prepared, clock):
    redis, _, settings, event_id = prepared
    key = redis.key("event:" + event_id)
    document = decode_document(redis.client.get(key))
    rows = dict(stored_rows(document))
    whole = clock.now().replace(microsecond=0)
    newest = whole + timedelta(microseconds=100000)
    for index, row in enumerate(rows.values()):
        row["quote"]["source_updated_at"] = newest if index == 1 else whole
    document = prepare_document(stored_event(document), rows)
    redis.client.set(key, encode(document), keepttl=True)
    with TestClient(create_app(settings, redis, clock)) as api:
        response = api.get(f"/v1/events/{event_id}/props", headers={"X-API-Key": "fixture-key"})
    # Rows are ordered by book, market, then player: row 1 shares a market with row 0.
    book = next(b for b in response.json()["bookmakers"] if b["key"] == "draftkings")
    assert book["last_update"] == wire_time(newest)
    assert book["markets"][0]["last_update"] == wire_time(newest)


def test_prepared_events_sort_by_actual_commence_time(prepared, clock, monkeypatch):
    redis, _, settings, event_id = prepared
    document = decode_document(redis.client.get(redis.key("event:" + event_id)))
    whole = (clock.now() + timedelta(hours=1)).replace(microsecond=0)
    documents = []
    for name, start in (("fractional", whole + timedelta(microseconds=100000)), ("whole", whole)):
        other = copy.deepcopy(document)
        other["id"] = name
        other["commence_time"] = wire_time(start)
        other["_storage"]["event"].update(id=name, start=wire_time(start))
        documents.append(other)
    monkeypatch.setattr(redis, "response_documents", lambda *args, **kwargs: documents)
    with TestClient(create_app(settings, redis, clock)) as api:
        response = api.get("/v1/sports/nba_basketball/odds", headers={"X-API-Key": "fixture-key"})
    assert [event["id"] for event in response.json()] == ["whole", "fractional"]


@pytest.mark.parametrize("event_request", [False, True])
def test_kickoff_during_response_processing_never_returns_commenced_odds(
    prepared, clock, monkeypatch, event_request
):
    from odds_api.application import services

    redis, _, settings, event_id = prepared
    project = services.project_response

    def commence_during_projection(*args, **kwargs):
        payload = project(*args, **kwargs)
        clock.value = 86400
        return payload

    monkeypatch.setattr(services, "project_response", commence_during_projection)
    path = f"/v1/events/{event_id}/props" if event_request else "/v1/sports/nba_basketball/odds"
    with TestClient(create_app(settings, redis, clock)) as api:
        response = api.get(path, headers={"X-API-Key": "fixture-key"})
    if event_request:
        assert response.status_code == 404
    else:
        assert response.status_code == 200 and response.json() == []


def test_collector_stores_compressed_public_hierarchy_and_single_event_read_skips_quote_reconstruction(
    prepared, clock, monkeypatch
):
    redis, _, settings, event_id = prepared
    key = redis.key("event:" + event_id)
    packed = redis.client.get(key)
    assert packed.startswith("zlib:1:")
    document = decode_document(packed)
    assert document["_storage"]["version"] == 2
    assert "quotes" not in document
    assert document["id"] == event_id
    assert {book["key"] for book in document["bookmakers"]} == {"unabated_901", "propline_draftkings"}
    outcome = document["bookmakers"][0]["markets"][0]["outcomes"][0]
    assert set(outcome) == {"name", "price", "point", "description", "_storage"}
    for book in document["bookmakers"]:
        for market in book["markets"]:
            for stored in market["outcomes"]:
                assert "freshness" not in stored
                assert {"collected_at", "source_updated_at", "expires_at"} <= stored["_storage"].keys()
    calls = []
    original_get = redis.client.get

    def get(key):
        calls.append(key)
        return original_get(key)

    def forbidden(*args, **kwargs):
        raise AssertionError("Prepared reads must not reconstruct domain quotes or refetch the event")

    monkeypatch.setattr(redis.client, "get", get)
    monkeypatch.setattr(redis, "event", forbidden)
    monkeypatch.setattr(redis, "quotes", forbidden)
    monkeypatch.setattr("odds_api.infrastructure.redis_repository.decode_quote", forbidden)
    with TestClient(create_app(settings, redis, clock)) as api:
        response = api.get(f"/v1/events/{event_id}/props", headers={"X-API-Key": "fixture-key"})
    assert response.status_code == 200
    assert response.json()["bookmakers"]
    assert calls == [key]


@pytest.mark.parametrize("compressed", [False, True])
def test_legacy_records_are_readable_and_upgrade_losslessly_on_partial_collection(
    prepared, clock, compressed
):
    from odds_api.infrastructure.redis_repository import compress_document, decode_quote

    redis, _, settings, event_id = prepared
    key = redis.key("event:" + event_id)
    document = decode_document(redis.client.get(key))
    original = {selection: row for selection, row in stored_rows(document)}
    legacy = encode({"event": stored_event(document), "quotes": original})
    redis.client.set(key, compress_document(legacy) if compressed else legacy, keepttl=True)
    expiry = redis.client.pexpiretime(key)
    before = redis.quotes("nba_basketball")
    with TestClient(create_app(settings, redis, clock)) as api:
        response = api.get(f"/v1/events/{event_id}/props", headers={"X-API-Key": "fixture-key"})
        assert response.status_code == 200 and response.json()["bookmakers"]
    # Read-only requests leave the old format and TTL intact.
    assert "quotes" in decode_document(redis.client.get(key))
    assert redis.client.pexpiretime(key) == expiry
    clock.value = 10
    # Update just one of Unabated's props. Other providers and lines retain their exact metadata.
    from odds_api.domain.models import Board, Event, League

    event_data = stored_event(document)
    event = Event(
        **{k: event_data[k] for k in ("source_id", "league_key", "home", "away", "status")},
        start=clock.now() + timedelta(seconds=86400 - clock.value),
    )
    selection, row = next((s, r) for s, r in original.items() if r["book_key"] == "unabated_901")
    quote = replace(
        decode_quote(row["quote"]), price=150, collected_at=clock.now(), source_updated_at=clock.now()
    )
    board = Board(
        League("nba_basketball", "NBA", "nba", "42"),
        "props",
        (event,),
        (Sportsbook("901", row["book_title"]),),
        (quote,),
        clock.now(),
        False,
    )
    redis.save(board)
    upgraded = decode_document(redis.client.get(key))
    assert upgraded["_storage"]["version"] == 2 and "quotes" not in upgraded
    assert redis.client.pexpiretime(key) == expiry
    saved = {r["quote"].selection_id: r["quote"] for r in redis.quotes("nba_basketball")}
    expected = {r["quote"].selection_id: r["quote"] for r in before}
    expected[selection] = quote
    assert saved == expected


@pytest.mark.parametrize("age,expected", [(0, True), (601, True)])
def test_expired_selections_remain_visible_without_legacy_prop_cache(prepared, clock, age, expected):
    redis, _, settings, event_id = prepared
    settings.props_cache_ttl = 0
    clock.value = age
    with TestClient(create_app(settings, redis, clock)) as api:
        response = api.get(f"/v1/events/{event_id}/props", headers={"X-API-Key": "fixture-key"})
    assert bool(response.json()["bookmakers"]) is expected


def test_explicit_format_migration_and_rollback_preserve_quotes_and_expiry(prepared):
    redis, _, _, event_id = prepared
    key = redis.key("event:" + event_id)
    before = redis.quotes("nba_basketball")
    expiry = redis.client.pexpiretime(key)
    packed = redis.client.get(key)
    preview = redis.rewrite_event_documents("legacy")
    assert preview["candidate_events"] == 1 and preview["rewritten_events"] == 0
    assert redis.client.get(key) == packed
    for target in ("legacy", "response"):
        counts = redis.rewrite_event_documents(target, dry_run=False)
        assert counts["rewritten_events"] == 1
        assert ("quotes" in decode_document(redis.client.get(key))) == (target == "legacy")
        assert redis.quotes("nba_basketball") == before
        assert redis.client.pexpiretime(key) == expiry
        assert redis.rewrite_event_documents(target, dry_run=False)["candidate_events"] == 0


@pytest.mark.parametrize("race", ["updated", "expired"])
def test_format_migration_cannot_overwrite_updates_or_resurrect_expired_events(prepared, monkeypatch, race):
    redis, _, _, event_id = prepared
    key = redis.key("event:" + event_id)
    newer = copy.deepcopy(decode_document(redis.client.get(key)))
    newer["home_team"] = "Updated home team"
    value = encode(newer)
    original_eval = redis.client.eval

    def concurrently_change(script, *args):
        assert script == REWRITE_DOCUMENT
        if race == "updated":
            redis.client.set(key, value, keepttl=True)
        else:
            redis.client.delete(key)
        return original_eval(script, *args)

    monkeypatch.setattr(redis.client, "eval", concurrently_change)
    counts = redis.rewrite_event_documents("legacy", dry_run=False)
    assert counts["rewritten_events"] == 0 and counts["raced_events"] == 1
    assert redis.client.get(key) == (value if race == "updated" else None)
