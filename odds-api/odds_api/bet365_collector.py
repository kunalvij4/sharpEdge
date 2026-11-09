"""Collect sequentially on the user's machine and send verified snapshots over HTTPS."""

import asyncio
import json
import logging
import os
import signal
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from odds_api.infrastructure.bet365_ingestion import MAX_CAPTURE_BYTES, Capture
from odds_api.infrastructure.bet365_runtime import command, prune_runs, write_json
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.logging import configure_logging
from scripts.organize_bet365_league_dump import organize_leagues
from scripts.verify_bet365_dump import verify

log = logging.getLogger(__name__)
TABS = {
    "nhl": ["Shots on Goal O/U", "Points O/U", "Assists O/U", "Saves O/U"],
    "nba": ["Points O/U", "Rebounds O/U", "Assists O/U", "Threes Made O/U"],
    "nfl": ["Pass Yds O/U", "Passing TDs O/U", "Receiving Yds O/U", "Rush Yds O/U"],
    "ncaaf": ["Pass Yds O/U", "Passing TDs O/U", "Receiving Yds O/U", "Rush Yds O/U"],
    "ncaab": ["Points O/U", "Rebounds O/U", "Assists O/U"],
    "mlb": ["Pitcher Strikeouts O/U", "Pitcher Outs O/U", "Hits O/U"],
}


def jobs(settings):
    return [
        (value["title"].lower(), key)
        for key, value in settings.collection_leagues.items()
        if value["title"].lower() in TABS
    ]


def destination(settings):
    url = urlsplit(settings.bet365_server_url)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("BET365_SERVER_URL must be an HTTPS API base URL without credentials")
    if not settings.bet365_ingest_key.get_secret_value():
        raise ValueError("Set BET365_INGEST_KEY to the server's dedicated collector key")
    return settings.bet365_server_url.rstrip("/") + "/v1/ingest/bet365"


def capture_payload(directory, settings, league):
    messages = [
        {key: message[key] for key in ("stage", "received_at", "source_url", "records")}
        for message in json.loads((directory / "messages.json").read_text(encoding="utf-8"))
        if message.get("transport") != "websocket"
    ]
    report = organize_leagues(messages, region=settings.bet365_region)
    verification = verify(report, messages)
    write_json(directory / "verification.json", verification)
    if not verification["source_checks_passed"] or report["normalization_issues"]:
        raise ValueError("Bet365 source validation failed")
    payload = Capture(region=settings.bet365_region, league=league, messages=messages).model_dump_json()
    if len(payload.encode()) > MAX_CAPTURE_BYTES:
        raise ValueError("Capture exceeds the ingestion size limit")
    return payload


async def transmit(client, url, payload, *, sleep=asyncio.sleep):
    """Retry the identical observation; timestamps and selection identities never change."""
    for attempt in range(3):
        try:
            response = await client.post(url, content=payload, headers={"Content-Type": "application/json"})
            response.raise_for_status()
            result = response.json()
            if not isinstance(result.get("accepted_selections"), int):
                raise ValueError("Invalid ingestion acknowledgment")
            return result
        except (httpx.TransportError, httpx.HTTPStatusError) as error:
            retryable = not isinstance(error, httpx.HTTPStatusError) or error.response.status_code >= 500
            if not retryable or attempt == 2:
                raise
            await sleep(2**attempt)


def browser_environment():
    excluded = {
        "DATABASE_URL",
        "REDIS_URL",
        "API_KEYS",
        "UNABATED_API_KEY",
        "PROPLINE_API_KEY",
        "POSTGRES_PASSWORD",
        "BET365_INGEST_KEY",
        "BET365_SERVER_URL",
    }
    return {key: value for key, value in os.environ.items() if key not in excluded}


async def collect_once(settings, name, league, root, client, url, states):
    output = root / name
    directory = output / "runs" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    directory.mkdir(parents=True)
    start = asyncio.get_running_loop().time()
    state = {"state": "collecting", "last_attempt": datetime.now(UTC).isoformat()}
    states[name] = state
    write_json(root / "status.json", states)
    try:
        await command(
            [
                "scripts.capture_bet365_league",
                "--league",
                name,
                "--region",
                settings.bet365_region,
                "--channel",
                "msedge",
                "--cdp",
                "--lightweight",
                "--wait-seconds",
                str(settings.bet365_wait),
                "--output-dir",
                str(directory),
                "--profile-dir",
                str(directory / "profile"),
                "--skip-unavailable-tabs",
                "--tabs",
                *TABS[name],
            ],
            settings.bet365_command_timeout,
            environment=browser_environment(),
        )
        payload = await asyncio.to_thread(capture_payload, directory, settings, league)
        (directory / "pending.json").write_text(payload, encoding="utf-8")
        result = await transmit(client, url, payload)
        (directory / "pending.json").unlink()
        write_json(directory / "delivery.json", result)
        state.update(
            state="success" if result["accepted_selections"] else "no_matching_prices",
            last_delivery=datetime.now(UTC).isoformat(),
            **result,
        )
    except Exception as error:
        state.update(state="failed", error_type=type(error).__name__)
    finally:
        state["duration_seconds"] = round(asyncio.get_running_loop().time() - start, 2)
        write_json(root / "status.json", states)
        log.info("bet365_collection", extra={"job": name, **state})
        prune_runs(output, 2)


async def run():
    configure_logging()
    settings = Settings()
    url = destination(settings)
    scheduled = jobs(settings)
    if not scheduled:
        raise ValueError("No supported collection leagues configured")
    root = Path(settings.bet365_output_dir)
    root.mkdir(parents=True, exist_ok=True)
    states, next_run = {}, {name: 0.0 for name, _ in scheduled}
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, task.cancel)
        except NotImplementedError:
            pass
    async with httpx.AsyncClient(
        headers={"X-Collector-Key": settings.bet365_ingest_key.get_secret_value()},
        timeout=30,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        while True:
            # One subprocess/browser at a time, with fair round-robin scheduling.
            for name, league in scheduled:
                if loop.time() >= next_run[name]:
                    await collect_once(settings, name, league, root, client, url, states)
                    next_run[name] = loop.time() + settings.bet365_interval
            await asyncio.sleep(max(1, min(next_run.values()) - loop.time()))


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
