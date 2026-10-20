"""Monotonic fixed deadlines; no catch-up bursts or overlapping scope jobs."""

import asyncio
from dataclasses import dataclass
from math import floor

from odds_api.application.ports import Clock


@dataclass
class Slot:
    league: str
    kind: str
    next_due: float
    task: asyncio.Task | None = None


class Scheduler:
    def __init__(self, clock: Clock, collect, missed, leagues: list[str], interval: float = 30):
        if not leagues or interval <= 0:
            raise ValueError("Positive interval and at least one league required")
        self.clock, self.collect, self.missed, self.interval = clock, collect, missed, interval
        origin = clock.monotonic()
        step = interval / (2 * len(leagues))
        self.slots = [
            Slot(league, kind, origin + (2 * i + j) * step)
            for i, league in enumerate(leagues)
            for j, kind in enumerate(("moneyline", "props"))
        ]

    async def tick(self):
        now = self.clock.monotonic()
        for slot in self.slots:
            if now < slot.next_due:
                continue
            lag = now - slot.next_due
            elapsed = floor(lag / self.interval)
            busy = slot.task is not None and not slot.task.done()
            self.missed(slot.league, slot.kind, elapsed + int(busy), lag)
            slot.next_due += (elapsed + 1) * self.interval
            if not busy:
                slot.task = asyncio.create_task(self.collect(slot.league, slot.kind))

    async def run(self, stop: asyncio.Event):
        try:
            while not stop.is_set():
                await self.tick()
                await self.clock.sleep(
                    min(0.25, max(0, min(s.next_due for s in self.slots) - self.clock.monotonic()))
                )
        finally:
            jobs = [s.task for s in self.slots if s.task is not None]
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
