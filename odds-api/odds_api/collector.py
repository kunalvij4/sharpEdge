import asyncio
import logging
import signal

from odds_api.application.scheduling import Scheduler
from odds_api.application.services import CollectionService
from odds_api.infrastructure.clock import SystemClock
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.lease import CollectorLease
from odds_api.infrastructure.logging import configure_logging
from odds_api.infrastructure.provider import UnabatedClient
from odds_api.infrastructure.rate_limit import RateLimiter
from odds_api.infrastructure.repository import SqlRepository


async def run():
    configure_logging()
    settings, clock = Settings(), SystemClock()
    if not settings.unabated_api_key.get_secret_value():
        raise RuntimeError("Set UNABATED_API_KEY in environment or a secret file")
    repository = SqlRepository(settings.database_url, settings.leagues, settings.snapshot_retention_days)
    provider = UnabatedClient(
        settings, clock, RateLimiter(clock, settings.rate_min_interval, settings.odds_min_interval)
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            signal.signal(signum, lambda *_: loop.call_soon_threadsafe(stop.set))
    service = CollectionService(provider, repository, clock)
    scheduler = Scheduler(
        clock, service.collect, repository.missed, list(settings.leagues), settings.poll_interval
    )
    try:
        lease = CollectorLease(repository.engine)
        lease.__enter__()
        acquired = True

        async def heartbeat():
            while not stop.is_set():
                # Losing the ownership connection terminates scheduling and in-flight jobs.
                lease.ping()
                repository.heartbeat(clock.now(), provider.metrics)
                await clock.sleep(2)

        scheduling = asyncio.create_task(scheduler.run(stop))
        health = asyncio.create_task(heartbeat())
        stopping = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait((scheduling, health, stopping), return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is not stopping:
                task.result()
    finally:
        stop.set()
        active = [
            t for t in (locals().get("scheduling"), locals().get("health"), locals().get("stopping")) if t
        ]
        for task in active:
            task.cancel()
        await asyncio.wait_for(asyncio.gather(*active, return_exceptions=True), settings.shutdown_timeout)
        await provider.close()
        if locals().get("acquired"):
            lease.__exit__(None, None, None)
        repository.close()
        logging.getLogger(__name__).info("collector_stopped")


if __name__ == "__main__":
    asyncio.run(run())
