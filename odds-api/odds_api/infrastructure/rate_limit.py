import asyncio
from contextlib import asynccontextmanager


class RateLimiter:
    """One admission controller for discovery, every odds scope and all retries."""

    def __init__(self, clock, minimum: float, odds_minimum: float):
        self.clock, self.minimum, self.odds_minimum = clock, minimum, odds_minimum
        self.next_all = self.next_odds = self.cooldown = 0.0
        self.lock = asyncio.Lock()
        self.odds_lock = asyncio.Lock()

    async def acquire(self, odds=False):
        while True:
            async with self.lock:
                now = self.clock.monotonic()
                deadline = max(self.next_all, self.cooldown, self.next_odds if odds else 0)
                if deadline <= now:
                    self.next_all = now + self.minimum
                    if odds:
                        self.next_odds = now + self.odds_minimum
                    return
            # Never hold the shared lock while waiting for an odds-only interval.
            # Recheck admission after waking: another response may extend Retry-After.
            await self.clock.sleep(deadline - now)

    @asynccontextmanager
    async def request(self, odds=False):
        if not odds:
            await self.acquire()
            yield
            return
        # Serialize odds HTTP calls, including slow responses, across every scope.
        async with self.odds_lock:
            await self.acquire(odds=True)
            try:
                yield
            finally:
                self.next_odds = max(self.next_odds, self.clock.monotonic() + self.odds_minimum)

    def defer(self, seconds: float):
        self.cooldown = max(self.cooldown, self.clock.monotonic() + max(0, seconds))
