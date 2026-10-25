"""Keep heartbeats responsive while finishing SQL work before releasing ownership."""

import asyncio


async def blocking_work(function, *args, **kwargs):
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A thread cannot be cancelled. Do not release the lease beneath its transaction.
        await task
        raise
