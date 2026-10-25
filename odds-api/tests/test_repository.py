from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from odds_api.domain.models import Availability


def count(repo, table):
    with repo.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(repo.t[table])).scalar_one()


def test_migrations_idempotency_and_relationships(repo, board):
    snapshot = board()
    repo.save(snapshot)
    repo.save(snapshot)
    assert repo.ready()
    assert count(repo, "events") == 1
    assert count(repo, "markets") == 1
    assert count(repo, "selections") == 2
    assert count(repo, "odds") == 2
    assert repo.quotes("nba_basketball")[0]["quote"].source_selection_id in {"2001", "2002"}


def test_unique_source_event_constraint(repo, board):
    repo.save(board())
    event = repo.events("nba_basketball")[0]
    with pytest.raises(IntegrityError), repo.engine.begin() as conn:
        conn.execute(
            repo.t["events"]
            .insert()
            .values(
                id="duplicate",
                source_id=event["source_id"],
                league_key=event["league_key"],
                start=event["start"],
                home="H",
                away="A",
                status="pregame",
            )
        )


def test_partial_refresh_and_failure_preserve_absent_selections(repo, board):
    snapshot = board()
    repo.save(snapshot)
    repo.save(replace(snapshot, quotes=snapshot.quotes[:1], complete=False))
    repo.failure("nba_basketball", "moneyline", "provider_unavailable")
    assert all(r["quote"].state == Availability.AVAILABLE for r in repo.quotes("nba_basketball"))


def test_complete_empty_refresh_preserves_all_prices_and_timestamps(repo, board):
    moneyline, props = board(), board("props")
    repo.save(moneyline)
    repo.save(props)
    before = repo.quotes("nba_basketball")
    repo.save(replace(moneyline, quotes=()))
    rows = repo.quotes("nba_basketball")
    assert rows == before


def test_invalid_refresh_preserves_price_until_valid_fresher_relisting(repo, board, clock):
    snapshot = board()
    q = snapshot.quotes[0]
    repo.save(snapshot)
    repo.save(replace(snapshot, quotes=(replace(q, state=Availability.SUSPENDED),)))
    repo.save(replace(snapshot, quotes=()))
    clock.value = 1
    repo.save(
        replace(snapshot, quotes=(replace(q, source_selection_id="new-line-id", collected_at=clock.now()),))
    )
    rows = repo.quotes("nba_basketball")
    assert len(rows) == 2
    relisted = next(r["quote"] for r in rows if r["quote"].selection_id == q.selection_id)
    assert relisted.state == Availability.AVAILABLE
    assert relisted.source_selection_id == "new-line-id"


def test_failed_transaction_rolls_back_removals_and_updates(repo, board, monkeypatch):
    snapshot = board()
    repo.save(snapshot)
    original = repo.upsert_many

    def fail(conn, name, data):
        if name == "odds":
            raise RuntimeError("simulated write failure after removal")
        return original(conn, name, data)

    monkeypatch.setattr(repo, "upsert_many", fail)
    with pytest.raises(RuntimeError):
        repo.save(replace(snapshot, quotes=snapshot.quotes[:1]))
    assert all(r["quote"].state == Availability.AVAILABLE for r in repo.quotes("nba_basketball"))


def test_event_transitions_preserve_identity_and_null_source_times(repo, board):
    snapshot = board()
    for status in ("pregame", "live", "final", "cancelled"):
        repo.save(replace(snapshot, events=(replace(snapshot.events[0], status=status),)))
        assert repo.events("nba_basketball")[0]["id"] == snapshot.events[0].id
        assert repo.events("nba_basketball")[0]["status"] == status
    repo.save(board("props"))
    assert any(r["quote"].source_updated_at is None for r in repo.quotes("nba_basketball"))


def test_snapshots_have_retention(repo, board, clock):
    repo.retention = 1
    snapshot = board()
    repo.save(snapshot)
    repo.save(replace(snapshot, collected_at=clock.now() + timedelta(days=2)))
    assert count(repo, "snapshots") == 1


def test_collection_status_distinguishes_empty_failure_and_stale(repo, board, clock):
    snapshot = board()
    repo.save(snapshot)
    repo.heartbeat(clock.now(), {"rate_limits": 2})
    state = repo.status(clock.now() + timedelta(seconds=100), 90, 3600)
    assert state["stale_quotes"] == 2
    assert not state["collector_healthy"]
    assert state["provider_metrics"]["rate_limits"] == 2
    repo.save(replace(snapshot, quotes=()))
    scope = next(
        s
        for s in repo.status(clock.now(), 90, 3600)["scopes"]
        if s["league"] == "nba_basketball" and s["kind"] == "moneyline"
    )
    assert scope["outcome"] == "empty"
    assert scope["last_success"] is not None


def test_collector_ownership_is_exclusive(repo):
    from odds_api.infrastructure.lease import CollectorLease

    with CollectorLease(repo.engine):
        with pytest.raises(RuntimeError, match="Another collector"):
            with CollectorLease(repo.engine):
                pass
    with CollectorLease(repo.engine):
        pass


def test_readers_never_observe_partial_board(repo, board, monkeypatch, clock):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    original = board()
    repo.save(original)
    paused, resume = Event(), Event()
    upsert = repo.upsert_many

    def pause_before_prices(connection, name, rows):
        if name == "odds":
            paused.set()
            if not resume.wait(10):
                raise RuntimeError("Writer coordination timed out")
        return upsert(connection, name, rows)

    monkeypatch.setattr(repo, "upsert_many", pause_before_prices)
    clock.value = 1
    replacement = replace(
        original, quotes=(replace(original.quotes[0], price=150, collected_at=clock.now()),)
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        write = executor.submit(repo.save, replacement)
        try:
            assert paused.wait(5)
            during = repo.quotes("nba_basketball")
            assert len(during) == 2
            assert all(row["quote"].state == Availability.AVAILABLE for row in during)
            assert {row["quote"].price for row in during} == {120, -130}
        finally:
            resume.set()
        write.result(timeout=10)
    after = [row["quote"] for row in repo.quotes("nba_basketball")]
    assert {quote.state for quote in after} == {Availability.AVAILABLE}
    assert {quote.price for quote in after} == {150, -130}
