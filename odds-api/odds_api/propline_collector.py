"""Bulk collection, with no per-event calls or retries."""

import asyncio
import json
import logging
import signal
from pathlib import Path

from odds_api.application.async_work import blocking_work
from odds_api.infrastructure.clock import SystemClock
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.logging import configure_logging
from odds_api.infrastructure.propline import SPORT_KEYS, ProplineClient, ProplineError, request_budget
from odds_api.infrastructure.propline_normalization import boards
from odds_api.infrastructure.storage import collector_lease, create_repository

log = logging.getLogger(__name__)


async def collect_cycle(client, repository, settings, state, *, lease=None, snapshots=None):
    for league in SPORT_KEYS:
        if league not in settings.leagues:
            continue
        if lease:
            lease.ping()
        previous = state.get(league, {})
        attempt = client.clock.now().isoformat()
        try:
            result = await client.fetch_bulk(league)
            if snapshots is not None:
                snapshots[league] = result
            output, counts = await blocking_work(
                boards,
                result,
                repository,
                max_age=settings.propline_max_age,
                collected_ttl=settings.propline_collected_ttl,
                discover_events=not settings.unabated_enabled,
            )
            if lease:
                lease.ping()
            for board in output:
                await blocking_work(repository.save, board)
            state[league] = {
                "last_attempt": attempt,
                "last_success": client.clock.now().isoformat(),
                "outcome": "partial" if any(not b.complete for b in output) else "success",
                "counts": counts,
                "quota": result.headers,
                "source_events": len(result.events),
            }
            log.info("propline_collection", extra={"league": league, "counts": counts})
        except Exception as error:
            state[league] = {
                **previous,
                "last_attempt": attempt,
                "outcome": getattr(error, "code", "collection_error"),
                "error_type": type(error).__name__,
            }
            if isinstance(error, ProplineError):
                state[league].update(quota=error.headers, retry_seconds=error.retry_seconds)
            log.warning(
                "propline_collection_failed", extra={"league": league, "outcome": state[league]["outcome"]}
            )
            if isinstance(error, ProplineError) and (
                error.status in {401, 403, 429, 503}
                or error.code in {"transport_error", "daily_quota_exhausted", "provider_cooldown"}
            ):
                break


async def run():
    configure_logging()
    settings, clock, stop = Settings(), SystemClock(), asyncio.Event()
    if not settings.propline_enabled:
        return
    key = settings.propline_api_key.get_secret_value()
    if not key:
        raise RuntimeError("Set PROPLINE_API_KEY")
    repository = create_repository(settings, clock)
    client = ProplineClient(settings, clock)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            signal.signal(signum, lambda *_: loop.call_soon_threadsafe(stop.set))
    directory = Path(settings.propline_output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    state = {}
    try:
        with collector_lease(repository, key=911712352) as lease:
            while not stop.is_set():
                started = clock.monotonic()
                await collect_cycle(client, repository, settings, state, lease=lease)
                status = {
                    "updated_at": clock.now().isoformat(),
                    "leagues": state,
                    "requests_made": client.requests,
                    "budget": request_budget(
                        settings.propline_poll_interval, len(set(settings.leagues) & SPORT_KEYS.keys())
                    ),
                }
                temporary = directory / "status.tmp"
                temporary.write_text(
                    json.dumps(status, indent=2).replace(key, "[REDACTED]"), encoding="utf-8"
                )
                temporary.replace(directory / "status.json")
                # Never catch up with extra calls if a slow cycle misses its deadline.
                remaining = max(0, settings.propline_poll_interval - (clock.monotonic() - started))
                while remaining > 0 and not stop.is_set():
                    try:
                        await asyncio.wait_for(stop.wait(), min(2, remaining))
                    except TimeoutError:
                        lease.ping()
                    remaining = max(0, settings.propline_poll_interval - (clock.monotonic() - started))
    finally:
        await client.close()
        repository.close()


if __name__ == "__main__":
    asyncio.run(run())
