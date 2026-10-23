import asyncio

from odds_api.runtime import supervise


async def test_exited_collector_is_restarted_without_stopping_healthy_sibling(caplog):
    stop = asyncio.Event()
    task = asyncio.create_task(
        supervise("collector", ["-c", "raise SystemExit(3)"], stop, 2, restart_delay=0.01)
    )
    try:
        async with asyncio.timeout(5):
            while len([r for r in caplog.records if r.message == "child_exited"]) < 2:
                await asyncio.sleep(0.01)
        assert not task.done()
        assert all(r.process_name == "collector" and r.exit_code == 3 for r in caplog.records)
    finally:
        stop.set()
        await asyncio.wait_for(task, 2)
