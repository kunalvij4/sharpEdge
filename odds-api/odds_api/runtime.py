"""Supervise API and isolated collection processes in one application container."""

import asyncio
import logging
import signal
import sys

from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.logging import configure_logging
from odds_api.infrastructure.storage import create_repository

log = logging.getLogger(__name__)


async def supervise(name, arguments, stop, shutdown_timeout, restart_delay=5):
    while not stop.is_set():
        child = await asyncio.create_subprocess_exec(sys.executable, *arguments)
        try:
            code = await child.wait()
            log.error("child_exited", extra={"process_name": name, "exit_code": code})
        finally:
            if child.returncode is None:
                try:
                    child.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(child.wait(), shutdown_timeout)
                except TimeoutError:
                    child.kill()
                    await child.wait()
        try:
            await asyncio.wait_for(stop.wait(), restart_delay)
        except TimeoutError:
            pass


async def run():
    configure_logging()
    settings, stop = Settings(), asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    if settings.storage_backend == "redis":
        # Only the new, compression-aware processes start after this migration.
        # Every rewrite is atomic; interrupted runs can safely resume.
        repository = create_repository(settings)
        try:
            counts = await asyncio.to_thread(repository.compact_event_documents)
            log.info("redis_event_compaction", extra={"counts": counts})
        finally:
            repository.close()
        if stop.is_set():
            return
    jobs = {
        "api": [
            "-m",
            "uvicorn",
            "odds_api.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--no-access-log",
        ],
        "collector": ["-m", "odds_api.collector"],
        "maintenance": ["-m", "odds_api.maintenance"],
    }
    tasks = [
        asyncio.create_task(supervise(name, arguments, stop, settings.shutdown_timeout))
        for name, arguments in jobs.items()
    ]
    try:
        stopping = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait([*tasks, stopping], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is not stopping:
                task.result()
    finally:
        stop.set()
        stopping.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, stopping, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(run())
