"""Read-only bulk retrieval verification; no database or running collector changes.

Run from odds-api: python -m scripts.probe_propline
"""

import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from odds_api.infrastructure.clock import SystemClock
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.propline import (
    SPORT_KEYS,
    ProplineClient,
    ProplineError,
    request_budget,
    summarize,
)

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value, key):
    # Guard raw diagnostic captures too, in case an upstream response echoes a secret.
    text = json.dumps(value, indent=2, ensure_ascii=False)
    path.write_text(text.replace(key, "[REDACTED]"), encoding="utf-8")


async def probe(settings, output, leagues, *, http=None, clock=None):
    key = settings.propline_api_key.get_secret_value()
    if not key or key.startswith("replace-with"):
        raise ProplineError("missing_PROPLINE_API_KEY")
    clock = clock or SystemClock()
    output.mkdir(parents=True, exist_ok=True)
    client = ProplineClient(settings, clock, http=http)
    report = {
        "started_at": clock.now().isoformat(),
        "budget": request_budget(settings.propline_poll_interval, len(leagues)),
        "results": [],
        "errors": [],
    }
    try:
        for league in leagues:
            try:
                result = await client.fetch_bulk(league)
                write_json(output / f"{league}.json", result.raw, key)
                summary = summarize(result)
                report["results"].append(summary)
                print(
                    json.dumps(
                        {
                            "league": league,
                            "events": summary["events"],
                            "bookmakers": summary["bookmakers"],
                            "counts": summary["counts"],
                            "retrieval_verified": summary["retrieval_verified"],
                            "headers": summary["headers"],
                        }
                    ).replace(key, "[REDACTED]"),
                    flush=True,
                )
            except ProplineError as error:
                report["errors"].append(
                    {
                        "league": league,
                        "code": error.code,
                        "http_status": error.status,
                        "headers": error.headers,
                        "retry_seconds": error.retry_seconds,
                    }
                )
                # Stop on auth, quota, burst/concurrency throttles, or transport failure.
                # No hidden retries or requests to the other sports after a key-wide failure.
                if error.status in {401, 403, 429, 503} or error.code in {
                    "transport_error",
                    "daily_quota_exhausted",
                    "provider_cooldown",
                }:
                    break
    finally:
        await client.close()
        report["requests_made"] = client.requests
        report["completed_at"] = clock.now().isoformat()
        report["retrieval_verified"] = (
            len(report["results"]) == len(leagues)
            and not report["errors"]
            and all(row["retrieval_verified"] for row in report["results"])
        )
        write_json(output / "summary.json", report, key)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--leagues", nargs="+", choices=SPORT_KEYS, default=list(SPORT_KEYS))
    args = parser.parse_args()
    if len(set(args.leagues)) != len(args.leagues):
        parser.error("Each league may appear only once")
    settings = Settings(_env_file=args.env_file)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = args.output_dir or ROOT / "artifacts" / "propline" / stamp
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        report = asyncio.run(probe(settings, output, args.leagues))
    except ProplineError as error:
        raise SystemExit(f"{error.code}: set PROPLINE_API_KEY in odds-api/.env") from None
    print(
        json.dumps(
            {
                "summary": str(output / "summary.json"),
                "requests_made": report["requests_made"],
                "retrieval_verified": report["retrieval_verified"],
                "errors": report["errors"],
            }
        ).replace(settings.propline_api_key.get_secret_value(), "[REDACTED]")
    )
    return 0 if report["retrieval_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
