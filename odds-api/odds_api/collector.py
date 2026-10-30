"""One owner collects PropLine at minute 0 and Unabated at minute 4, repeating every 8."""

import asyncio
import logging
import signal
from pathlib import Path

from odds_api.application.async_work import blocking_work
from odds_api.application.feed_schedule import FeedSchedule
from odds_api.application.services import CollectionService
from odds_api.infrastructure.bet365_runtime import write_json
from odds_api.infrastructure.clock import SystemClock
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.logging import configure_logging
from odds_api.infrastructure.propline import ProplineClient, request_budget
from odds_api.infrastructure.propline_normalization import boards
from odds_api.infrastructure.provider import UnabatedClient
from odds_api.infrastructure.rate_limit import RateLimiter
from odds_api.infrastructure.storage import collector_lease, create_repository
from odds_api.propline_collector import collect_cycle

log = logging.getLogger(__name__)


class CombinedCollection:
    def __init__(self, settings, clock, repository, unabated, propline, lease):
        self.settings, self.clock, self.repository = settings, clock, repository
        self.unabated, self.propline, self.lease = unabated, propline, lease
        self.service = CollectionService(unabated, repository, clock)
        self.snapshots, self.state = {}, {}

    async def collect(self, feed):
        self.lease.ping()
        if feed == "propline":
            if not self.settings.propline_enabled:
                return
            await collect_cycle(
                self.propline,
                self.repository,
                self.settings,
                self.state,
                lease=self.lease,
                snapshots=self.snapshots,
            )
            directory = Path(self.settings.propline_output_dir)
            directory.mkdir(parents=True, exist_ok=True)
            write_json(
                directory / "status.json",
                {
                    "updated_at": self.clock.now().isoformat(),
                    "leagues": self.state,
                    "requests_made": self.propline.requests,
                    "budget": request_budget(),
                },
            )
        else:
            if not self.settings.unabated_enabled:
                return
            for league in self.settings.leagues:
                kinds = ("moneyline", "props") if self.settings.unabated_odds_enabled else ("moneyline",)
                for kind in kinds:
                    self.lease.ping()
                    await self.service.collect(
                        league, kind, metadata_only=not self.settings.unabated_odds_enabled
                    )
                # Rejoin the first PropLine snapshot after canonical discovery.
                # Its collection time and expiry remain unchanged.
                result = self.snapshots.get(league)
                if (
                    result
                    and not self.state[league].get("counts", {}).get("matched_events")
                    and (self.clock.now() - result.collected_at).total_seconds()
                    < self.settings.propline_collected_ttl
                ):
                    output, counts = await blocking_work(
                        boards,
                        result,
                        self.repository,
                        max_age=self.settings.propline_max_age,
                        collected_ttl=self.settings.propline_collected_ttl,
                    )
                    for board in output:
                        self.lease.ping()
                        await blocking_work(self.repository.save, board)
                    self.state[league]["counts"] = counts
                    self.state[league]["catalog_rejoined_at"] = self.clock.now().isoformat()
            self.snapshots.clear()
            if self.state:
                write_json(
                    Path(self.settings.propline_output_dir) / "status.json",
                    {
                        "updated_at": self.clock.now().isoformat(),
                        "leagues": self.state,
                        "requests_made": self.propline.requests,
                        "budget": request_budget(),
                    },
                )


async def run():
    configure_logging()
    settings, clock, stop = Settings(), SystemClock(), asyncio.Event()
    if settings.poll_interval != 480 or settings.propline_poll_interval != 480:
        raise RuntimeError("Combined collection requires POLL_INTERVAL=480 and PROPLINE_POLL_INTERVAL=480")
    if settings.collected_ttl < 480 or settings.propline_collected_ttl < 480:
        raise RuntimeError("Collection TTLs must cover the eight-minute cycle")
    if settings.unabated_enabled and not settings.unabated_api_key.get_secret_value():
        raise RuntimeError("Set UNABATED_API_KEY")
    if settings.propline_enabled and not settings.propline_api_key.get_secret_value():
        raise RuntimeError("Set PROPLINE_API_KEY")
    repository = create_repository(settings, clock)
    unabated = UnabatedClient(
        settings, clock, RateLimiter(clock, settings.rate_min_interval, settings.odds_min_interval)
    )
    propline = ProplineClient(settings, clock)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            signal.signal(signum, lambda *_: loop.call_soon_threadsafe(stop.set))
    try:
        with (
            collector_lease(repository) as lease,
            collector_lease(repository, key=911712352) as propline_lease,
        ):
            collection = CombinedCollection(settings, clock, repository, unabated, propline, lease)
            scheduler = FeedSchedule(clock, settings.collection_state_path)

            async def heartbeat():
                try:
                    while not stop.is_set():
                        lease.ping()
                        propline_lease.ping()
                        repository.heartbeat(clock.now(), unabated.metrics)
                        await asyncio.sleep(2)
                except Exception as error:
                    log.error("collector_heartbeat_failed", extra={"error_type": type(error).__name__})
                    raise

            tasks = [
                asyncio.create_task(scheduler.run(collection.collect, stop)),
                asyncio.create_task(heartbeat()),
                asyncio.create_task(stop.wait()),
            ]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                stop.set()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await unabated.close()
        await propline.close()
        repository.close()


if __name__ == "__main__":
    asyncio.run(run())
