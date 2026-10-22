"""Repeat verified Bet365 snapshot collection in the headed Edge/Xvfb container.

Research artifacts only. No API database/provider credentials are used.
"""

import argparse
import asyncio
import json
import re
import shutil
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def publish_verified(output, verified):
    report = json.loads((verified / "odds.json").read_text(encoding="utf-8"))
    verification = json.loads((verified / "verification.json").read_text(encoding="utf-8"))
    counts = report["summary"]
    if not verification["source_checks_passed"] or verification["errors"]:
        raise RuntimeError("Snapshot source verification failed")
    if report["normalization_issues"]:
        raise RuntimeError("Snapshot contains normalization issues")
    if not all(
        counts.get(key, 0) > 0
        for key in ("moneyline_outcomes", "player_prop_selections", "over_under_complete_pairs")
    ):
        raise RuntimeError("Snapshot is missing moneylines, player props, or complete O/U pairs")
    # A failed/empty capture must never advance the pointer to verified data.
    manifest = {
        "verified_at": datetime.now(UTC).isoformat(),
        "odds_file": str((verified / "odds.json").relative_to(output)),
        "verification_file": str((verified / "verification.json").relative_to(output)),
        "summary": counts,
        "coverage_complete": False,
    }
    write_json(output / "latest.json", manifest)
    return manifest


def prune_runs(output, keep):
    root = output / "runs"
    if not root.exists():
        return
    if root.is_symlink() or root.resolve().parent != output.resolve():
        raise RuntimeError("Run directory must be a direct directory under the artifact output")
    protected = None
    if (output / "latest.json").exists():
        latest = json.loads((output / "latest.json").read_text(encoding="utf-8"))
        protected = (output / latest["odds_file"]).resolve().parent.parent
    directories = sorted(
        (
            path
            for path in root.iterdir()
            if re.fullmatch(r"\d{8}T\d{6}\.\d{6}Z", path.name) and path.is_dir() and not path.is_symlink()
        ),
        reverse=True,
    )
    for path in directories[keep:]:
        resolved = path.resolve()
        # Validate every recursive-delete target and retain the published run.
        if resolved.parent == root.resolve() and resolved != protected:
            shutil.rmtree(resolved)


async def command(arguments, timeout):
    child = await asyncio.create_subprocess_exec(sys.executable, "-m", *arguments)
    try:
        code = await asyncio.wait_for(child.wait(), timeout)
        if code:
            raise RuntimeError(f"{arguments[0]} exited with code {code}")
    finally:
        if child.returncode is None:
            try:
                child.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(child.wait(), 15)
            except TimeoutError:
                child.kill()
                await child.wait()


async def collect(args):
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
    successes, attempts = 0, 0
    try:
        while args.cycles == 0 or attempts < args.cycles:
            start = loop.time()
            attempts += 1
            run = output / "runs" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
            status = {
                "last_attempt": datetime.now(UTC).isoformat(),
                "attempt": attempts,
                "run": str(run.relative_to(output)),
                "state": "collecting",
            }
            write_json(output / "worker-status.json", status)
            print(json.dumps(status), flush=True)
            try:
                # Initial homepage responses include all three leagues' widgets.
                await command(
                    [
                        "scripts.capture_bet365_markets",
                        "--region",
                        args.region,
                        "--channel",
                        "msedge",
                        "--cdp",
                        "--home-only",
                        "--wait-seconds",
                        str(args.wait_seconds),
                        "--output-dir",
                        str(run / "homepage"),
                    ],
                    args.command_timeout,
                )
                await command(
                    [
                        "scripts.capture_bet365_league",
                        "--region",
                        args.region,
                        "--league",
                        "nba",
                        "--channel",
                        "msedge",
                        "--cdp",
                        "--tabs",
                        "Points O/U",
                        "--wait-seconds",
                        str(args.wait_seconds),
                        "--output-dir",
                        str(run / "nba"),
                    ],
                    args.command_timeout,
                )
                await command(
                    [
                        "scripts.organize_bet365_league_dump",
                        "--region",
                        args.region,
                        "--input-dir",
                        str(run / "homepage"),
                        str(run / "nba"),
                        "--output-dir",
                        str(run / "verified"),
                    ],
                    args.command_timeout,
                )
                await command(
                    ["scripts.verify_bet365_dump", "--input-dir", str(run / "verified")], args.command_timeout
                )
                latest = publish_verified(output, run / "verified")
                successes += 1
                status.update(
                    state="verified",
                    verified_at=latest["verified_at"],
                    summary=latest["summary"],
                    elapsed_seconds=round(loop.time() - start, 2),
                )
            except (RuntimeError, TimeoutError) as error:
                status.update(state="failed", error=str(error), elapsed_seconds=round(loop.time() - start, 2))
            write_json(output / "worker-status.json", status)
            print(json.dumps(status), flush=True)
            prune_runs(output, getattr(args, "retain_runs", 5))
            if args.cycles and attempts >= args.cycles:
                break
            await asyncio.sleep(max(0, args.interval_seconds - (loop.time() - start)))
    except asyncio.CancelledError:
        write_json(
            output / "worker-status.json",
            {
                "state": "stopped",
                "stopped_at": datetime.now(UTC).isoformat(),
                "attempts": attempts,
                "successes": successes,
            },
        )
        return 0
    return 0 if successes == attempts else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=("nj", "va"), default="nj")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/collector"))
    parser.add_argument("--interval-seconds", type=float, default=120)
    parser.add_argument("--wait-seconds", type=float, default=8)
    parser.add_argument("--command-timeout", type=float, default=120)
    parser.add_argument("--retain-runs", type=int, default=5)
    parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="0 runs continuously; a positive count performs a finite verification run",
    )
    args = parser.parse_args()
    if (
        args.interval_seconds < 60
        or not 1 <= args.wait_seconds <= 30
        or args.command_timeout < 30
        or args.cycles < 0
        or args.retain_runs < 1
    ):
        parser.error(
            "interval must be at least 60s, wait 1-30s, timeout at least 30s, cycles nonnegative, and retain-runs positive"
        )
    raise SystemExit(asyncio.run(collect(args)))


if __name__ == "__main__":
    main()
