"""Durable alternating slots: restart-safe, serial, and without catch-up bursts."""

import asyncio
import json
import logging
from pathlib import Path


class FeedSchedule:
    spacing = 240
    feeds = ("propline", "unabated")

    def __init__(self, clock, path):
        self.clock, self.path = clock, Path(path)
        if self.path.exists():
            state = json.loads(self.path.read_text(encoding="utf-8"))
            self.origin, self.slot = float(state["origin"]), int(state["slot"])
        else:
            self.origin, self.slot = clock.now().timestamp(), 0

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"origin": self.origin, "slot": self.slot}), encoding="utf-8")
        temporary.replace(self.path)

    async def tick(self, collect):
        now = self.clock.now().timestamp()
        if now < self.origin + self.slot * self.spacing:
            return
        # Preserve whose turn it is after downtime. Re-anchor to now instead
        # of skipping the other feed or replaying all missed deadlines.
        if now > self.origin + self.slot * self.spacing:
            self.origin = now - self.slot * self.spacing
        feed = self.feeds[self.slot % 2]
        self.slot += 1
        # Claim before I/O so crashes cannot immediately repeat a billed request.
        self.save()
        logging.getLogger(__name__).info("feed_cycle_started", extra={"feed": feed, "slot": self.slot - 1})
        await collect(feed)
        logging.getLogger(__name__).info("feed_cycle_finished", extra={"feed": feed, "slot": self.slot - 1})
        # A slow provider must never starve its sibling by repeatedly skipping
        # the sibling's slot. Delay the next turn, keeping all starts >=4m apart.
        finished = self.clock.now().timestamp()
        if finished > self.origin + self.slot * self.spacing:
            self.origin = finished - self.slot * self.spacing
        self.save()

    async def run(self, collect, stop):
        while not stop.is_set():
            await self.tick(collect)
            try:
                await asyncio.wait_for(stop.wait(), 1)
            except TimeoutError:
                pass
