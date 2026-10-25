"""Standalone browser capture service. Runtime writes artifacts only, never SQL."""

import asyncio
import json
import logging
import os
import signal
from datetime import UTC, datetime
from pathlib import Path

from odds_api.infrastructure.bet365 import MARKETS, boards
from odds_api.infrastructure.bet365_runtime import command, prune_runs, write_json
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.logging import configure_logging
from scripts.organize_bet365_league_dump import organize_leagues
from scripts.verify_bet365_dump import verify

log = logging.getLogger(__name__)
JOBS = {
    "homepage": ("scripts.capture_bet365_markets", ["--home-only"], None),
    "nba": ("scripts.capture_bet365_league", ["--league", "nba", "--tabs", "Points O/U"], "nba_basketball"),
    "nfl": (
        "scripts.capture_bet365_league",
        [
            "--league",
            "nfl",
            "--entry",
            "event",
            "--tabs",
            "Pass Yds O/U",
            "Passing TDs O/U",
            "Receiving Yds O/U",
            "Rush Yds O/U",
        ],
        "nfl_football",
    ),
    "mlb": (
        "scripts.capture_bet365_league",
        [
            "--league",
            "mlb",
            "--entry",
            "event",
            "--tabs",
            "Pitcher Props",
            "Pitcher Strikeouts O/U",
            "Pitcher Outs O/U",
            "Batter Props",
            "Hits O/U",
        ],
        "mlb_baseball",
    ),
}


class MarketsUnavailable(Exception):
    """Navigation succeeded but the source offered no supported prices."""


def ingest(directory, repository, settings, job):
    messages = [
        m for m in json.loads((directory / "messages.json").read_text()) if m.get("transport") != "websocket"
    ]
    pages = json.loads((directory / "pages.json").read_text())
    report = organize_leagues(messages, pages, settings.bet365_region)
    verification = verify(report, messages)
    if not verification["source_checks_passed"] or verification["errors"] or report["normalization_issues"]:
        raise ValueError("Bet365 source validation failed")
    if not report["summary"].get("moneyline_outcomes") and not report["summary"].get("over_under_selections"):
        raise ValueError("Bet365 capture has no usable prices")
    coverage = {}
    for league in report["leagues"]:
        if job == "homepage":
            coverage[league["key"]] = ("h2h",)
        elif league["key"] == JOBS[job][2]:
            # Only the requested/observed explicit O/U types are a complete refresh.
            labels = {p["source_label"] for e in league["events"] for p in e["player_props"] if "point" in p}
            coverage[league["key"]] = tuple(
                MARKETS[league["title"]][label] for label in labels if label in MARKETS[league["title"]]
            )
    output, counts = boards(
        report,
        repository,
        datetime.now(UTC),
        max_age=settings.bet365_max_age,
        support_age=max(settings.collected_ttl, settings.props_cache_ttl),
        coverage=coverage,
    )
    if job != "homepage" and not output:
        raise MarketsUnavailable("Requested Bet365 O/U market content was not received")
    for board in output:
        repository.save(board)
    write_json(directory / "normalized.json", report)
    write_json(directory / "verification.json", verification)
    return counts


def archive_capture(directory, settings):
    messages = [
        m for m in json.loads((directory / "messages.json").read_text()) if m.get("transport") != "websocket"
    ]
    pages = json.loads((directory / "pages.json").read_text())
    report = organize_leagues(messages, pages, settings.bet365_region)
    verification = verify(report, messages)
    write_json(directory / "normalized.json", report)
    write_json(directory / "verification.json", verification)
    if not verification["source_checks_passed"] or verification["errors"] or report["normalization_issues"]:
        raise ValueError("Bet365 source validation failed")
    return report["summary"]


async def run():
    configure_logging()
    settings = Settings()
    root = Path(settings.bet365_output_dir)
    root.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(2)
    states = {}
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    loop.add_signal_handler(signal.SIGINT, task.cancel)

    async def collect_job(name, module, options):
        output = root / name
        output.mkdir(parents=True, exist_ok=True)
        while True:
            async with semaphore:
                start = loop.time()
                directory = output / "runs" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
                state = {"state": "collecting", "last_attempt": datetime.now(UTC).isoformat()}
                states[name] = state
                write_json(root / "status.json", states)
                try:
                    await command(
                        [
                            module,
                            "--region",
                            settings.bet365_region,
                            "--channel",
                            "msedge",
                            "--cdp",
                            "--wait-seconds",
                            str(settings.bet365_wait),
                            "--output-dir",
                            str(directory),
                            "--profile-dir",
                            str(directory / "profile"),
                            *options,
                            *(["--skip-unavailable-tabs"] if name != "homepage" else []),
                        ],
                        settings.bet365_command_timeout,
                        environment={
                            k: v
                            for k, v in os.environ.items()
                            if k
                            not in {
                                "DATABASE_URL",
                                "API_KEYS",
                                "UNABATED_API_KEY",
                                "PROPLINE_API_KEY",
                                "POSTGRES_PASSWORD",
                            }
                        },
                    )
                    counts = await asyncio.to_thread(archive_capture, directory, settings)
                    state.update(state="success", last_success=datetime.now(UTC).isoformat(), counts=counts)
                except MarketsUnavailable:
                    state.update(state="unavailable", reason="no_supported_markets_offered")
                except Exception as error:
                    state.update(state="failed", error_type=type(error).__name__)
                state["duration_seconds"] = round(loop.time() - start, 2)
                write_json(root / "status.json", states)
                log.info("bet365_collection", extra={"job": name, **state})
                prune_runs(output, 3)
            await asyncio.sleep(max(1, settings.bet365_interval - (loop.time() - start)))

    tasks = [
        asyncio.create_task(collect_job(name, module, options))
        for name, (module, options, league) in JOBS.items()
        if league is None or league in settings.leagues
    ]

    try:
        await asyncio.gather(*tasks)
    finally:
        for child in tasks:
            child.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
