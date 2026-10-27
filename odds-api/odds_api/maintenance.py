"""Expire commenced events even when both upstream collectors are unavailable."""

import asyncio
import logging
import signal

from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.logging import configure_logging
from odds_api.infrastructure.storage import create_repository

log = logging.getLogger(__name__)


async def run():
    configure_logging()
    settings, stop = Settings(), asyncio.Event()
    repository = create_repository(settings)
    for signum in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(signum, stop.set)
    try:
        while not stop.is_set():
            removed = await asyncio.to_thread(repository.prune_started)
            if removed:
                log.info("commenced_events_deleted", extra={"events": removed})
            try:
                await asyncio.wait_for(stop.wait(), 60)
            except TimeoutError:
                pass
    finally:
        repository.close()


if __name__ == "__main__":
    asyncio.run(run())
