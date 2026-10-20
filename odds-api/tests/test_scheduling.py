import asyncio

import pytest

from odds_api.application.scheduling import Scheduler
from odds_api.infrastructure.rate_limit import RateLimiter


async def test_staggered_schedule_and_no_drift(clock):
    calls, missed = [], []

    async def collect(league, kind):
        calls.append((clock.monotonic(), league, kind))

    scheduler = Scheduler(clock, collect, lambda *args: missed.append(args), ["NBA", "NFL", "MLB"])
    for offset in range(0, 61, 5):
        clock.value = offset
        await scheduler.tick()
        await asyncio.sleep(0)
    assert calls[:6] == [
        (0, "NBA", "moneyline"),
        (5, "NBA", "props"),
        (10, "NFL", "moneyline"),
        (15, "NFL", "props"),
        (20, "MLB", "moneyline"),
        (25, "MLB", "props"),
    ]
    assert [c[0] for c in calls if c[1:] == ("NBA", "moneyline")] == [0, 30, 60]
    assert all(count == 0 for _, _, count, _ in missed)


async def test_overlapping_jobs_skip_deadline_without_drift(clock):
    gate, calls, misses = asyncio.Event(), [], []

    async def collect(league, kind):
        calls.append((league, kind))
        await gate.wait()

    scheduler = Scheduler(clock, collect, lambda *args: misses.append(args), ["NBA"])
    await scheduler.tick()
    await asyncio.sleep(0)
    clock.value = 30
    await scheduler.tick()
    await asyncio.sleep(0)
    assert calls.count(("NBA", "moneyline")) == 1
    assert any(league == "NBA" and kind == "moneyline" and count == 1 for league, kind, count, _ in misses)
    assert scheduler.slots[0].next_due == 60
    gate.set()
    await asyncio.gather(*(s.task for s in scheduler.slots if s.task))


async def test_missed_cycles_do_not_replay_burst(clock):
    calls, misses = [], []

    async def collect(*args):
        calls.append(args)

    scheduler = Scheduler(clock, collect, lambda *args: misses.append(args), ["NBA"])
    clock.value = 100
    await scheduler.tick()
    await asyncio.sleep(0)
    assert len(calls) == 2
    assert scheduler.slots[0].next_due == 120
    await scheduler.tick()
    assert len(calls) == 2
    assert sum(m[2] for m in misses) == 5


async def test_shared_limiter_enforces_starts_across_scopes(clock):
    limiter = RateLimiter(clock, minimum=0.1, odds_minimum=5)
    starts = []

    async def call(odds):
        await limiter.acquire(odds)
        starts.append((clock.monotonic(), odds))

    # FakeClock advances automatically; sequential calls avoid concurrent virtual-time jumps.
    for odds in (True, False, True, True):
        await call(odds)
    odds = [time for time, is_odds in starts if is_odds]
    assert odds == [0, 5, 10]
    assert starts[1][0] == 0.1


class ControlledClock:
    """Advance all waiters on one timeline without depending on wall-clock sleeps."""

    def __init__(self):
        self.value, self.waiters = 0.0, []

    def monotonic(self):
        return self.value

    async def sleep(self, seconds):
        future = asyncio.get_running_loop().create_future()
        self.waiters.append((self.value + seconds, future))
        await future

    async def advance(self, value):
        self.value = value
        for deadline, future in self.waiters:
            if deadline <= value and not future.done():
                future.set_result(None)
        # Allow awakened tasks to finish admission and acquire their request slots.
        for _ in range(3):
            await asyncio.sleep(0)


async def test_discovery_is_not_blocked_by_waiting_odds():
    clock = ControlledClock()
    limiter = RateLimiter(clock, 0.1, 5)
    await limiter.acquire(odds=True)
    odds = asyncio.create_task(limiter.acquire(odds=True))
    await asyncio.sleep(0)
    discovery = asyncio.create_task(limiter.acquire())
    await asyncio.sleep(0)
    await clock.advance(0.1)
    assert discovery.done() and not odds.done()
    await clock.advance(5)
    await asyncio.gather(odds, discovery)


async def test_waiting_request_rechecks_extended_shared_cooldown():
    clock = ControlledClock()
    limiter = RateLimiter(clock, 0.1, 5)
    await limiter.acquire(odds=True)
    pending = asyncio.create_task(limiter.acquire(odds=True))
    await asyncio.sleep(0)
    await clock.advance(1)
    limiter.defer(10)
    await clock.advance(5)
    assert not pending.done()
    await clock.advance(11)
    await pending
    assert limiter.next_odds == 16


async def test_odds_serialize_slow_http_and_space_from_completion():
    clock = ControlledClock()
    limiter = RateLimiter(clock, 0.1, 5)
    first_response, starts = asyncio.Event(), []

    async def call(gate=None):
        async with limiter.request(odds=True):
            starts.append(clock.monotonic())
            if gate:
                await gate.wait()

    first = asyncio.create_task(call(first_response))
    await asyncio.sleep(0)
    second = asyncio.create_task(call())
    await clock.advance(7)
    assert starts == [0]
    first_response.set()
    await first
    await clock.advance(11)
    assert starts == [0]
    await clock.advance(12)
    await second
    assert starts == [0, 12]


async def test_cancelled_odds_request_releases_slot_and_keeps_interval():
    clock = ControlledClock()
    limiter = RateLimiter(clock, 0.1, 5)
    gate = asyncio.Event()

    async def call():
        async with limiter.request(odds=True):
            await gate.wait()

    first = asyncio.create_task(call())
    await asyncio.sleep(0)
    await clock.advance(3)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not limiter.odds_lock.locked() and limiter.next_odds == 8


async def test_shutdown_cancels_inflight_collection(clock):
    gate, cancelled = asyncio.Event(), []

    async def collect(*_):
        try:
            await gate.wait()
        finally:
            cancelled.append(True)

    scheduler = Scheduler(clock, collect, lambda *_: None, ["NBA"])
    stop = asyncio.Event()
    running = asyncio.create_task(scheduler.run(stop))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    stop.set()
    await running
    assert cancelled
