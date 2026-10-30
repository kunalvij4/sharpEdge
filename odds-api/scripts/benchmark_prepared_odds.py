"""Offline comparison of legacy quote assembly and prepared Redis event responses.

Run with the project's development dependencies; all data and Redis are synthetic.
"""

import argparse
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from time import perf_counter
from types import SimpleNamespace

import fakeredis

from odds_api.application.prepared_odds import stored_event, stored_rows
from odds_api.application.services import OddsQueryService
from odds_api.domain.models import League
from odds_api.http.schemas import OddsResponse
from odds_api.infrastructure.config import DEFAULT_LEAGUES
from odds_api.infrastructure.normalization import Normalizer
from odds_api.infrastructure.redis_repository import (
    RedisRepository,
    compress_document,
    decode_document,
    encode,
)


class LegacyReads:
    """Expose the old query interface without enabling prepared responses."""

    def __init__(self, repository):
        for name in ("leagues", "event", "events", "quotes", "bookmakers"):
            setattr(self, name, getattr(repository, name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selections", type=int, default=3000)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.selections < 1 or arguments.iterations < 1:
        parser.error("selections and iterations must be positive")
    root = Path(__file__).resolve().parents[1]
    raw = json.loads((root / "tests/fixtures/provider.json").read_text())
    fixture = Normalizer().parse(
        League("nba_basketball", "NBA", "nba", "42"),
        "props",
        raw["props"]["data"],
        raw["sources"],
        raw["bets"],
        raw["periods"],
        raw["events"],
        raw["people"],
        raw["teams"],
        datetime(2026, 10, 19, tzinfo=UTC),
    )
    now = datetime.now(UTC)
    clock = SimpleNamespace(now=lambda: now)
    board = replace(
        fixture,
        events=(replace(fixture.events[0], start=now + timedelta(days=1)),),
        collected_at=now,
        quotes=tuple(
            replace(
                fixture.quotes[index % len(fixture.quotes)],
                player_id=str(100000 + index // len(fixture.quotes)),
                description=f"Synthetic Player {index // len(fixture.quotes):05d}",
                source_selection_id=str(index + 1),
                collected_at=now,
                source_updated_at=now,
                expires_at=None,
            )
            for index in range(arguments.selections)
        ),
    )
    client = fakeredis.FakeRedis(decode_responses=True)
    repository = RedisRepository("", DEFAULT_LEAGUES, clock=clock, client=client)
    started = perf_counter()
    repository.save(board)
    save_seconds = perf_counter() - started
    event_id = board.events[0].id
    key = repository.key("event:" + event_id)
    prepared = client.get(key)
    document = decode_document(prepared)
    legacy = compress_document(
        encode({"event": stored_event(document), "quotes": dict(stored_rows(document))})
    )
    markets = {q.market for q in board.quotes}
    results = {}
    payloads = {}
    for name, value, source in (
        ("legacy", legacy, LegacyReads(repository)),
        ("prepared", prepared, repository),
    ):
        client.set(key, value)
        service = OddsQueryService(source, clock, 600, 3600, markets)
        timings = []
        for _ in range(arguments.iterations):
            started = perf_counter()
            payload = service.event_props(event_id)
            timings.append(perf_counter() - started)
        # Compare actual wire contracts, including UTC timestamps and numeric types.
        payloads[name] = OddsResponse.model_validate(payload).model_dump(mode="json", exclude_unset=True)
        results[name] = {"median_query_seconds": median(timings), "compressed_bytes": len(value.encode())}
    assert payloads["legacy"] == payloads["prepared"]
    results.update(
        selections=arguments.selections,
        iterations=arguments.iterations,
        save_seconds=save_seconds,
        query_speedup=results["legacy"]["median_query_seconds"] / results["prepared"]["median_query_seconds"],
        identical_public_payload=True,
        synthetic=True,
    )
    output = json.dumps(results, indent=2) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
