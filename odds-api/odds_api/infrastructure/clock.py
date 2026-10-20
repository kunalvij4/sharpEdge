import asyncio
import time
from datetime import UTC, datetime


class SystemClock:
    def monotonic(self):
        return time.monotonic()

    def now(self):
        return datetime.now(UTC)

    async def sleep(self, seconds):
        await asyncio.sleep(max(0, seconds))
