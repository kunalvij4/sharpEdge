"""Observe public sportsbook traffic without changing the database or signing in.

Run with the optional bet365-probe dependency. Artifacts are local and gitignored.
Wire-format/JSON signals are research candidates, never validated normalized odds.
"""

import argparse
import asyncio
import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

BLOCK_MARKERS = (
    "access denied",
    "request blocked",
    "sorry, you have been blocked",
    "verify you are human",
    "pardon our interruption",
    "checking your browser",
    "unusual traffic",
)
LOCATION_MARKERS = (
    "unable to verify your location",
    "cannot verify your location",
    "not available in your location",
    "not available in your region",
    "not available in your country",
    "restricted location",
)
SPORT_PATTERN = re.compile(r"\b(NBA|NFL|MLB|basketball|baseball|american football)\b", re.I)
PROP_PATTERN = re.compile(
    r"\b(player (?:props|points|rebounds|assists)|passing yards|rushing yards|"
    r"receiving yards|pitcher strikeouts)\b",
    re.I,
)
JSON_MARKET_PATTERN = re.compile(r'"(?:markets|selections|outcomes|odds)"\s*:', re.I)
MAX_BODY_BYTES = 2_000_000


def safe_url(value):
    """Omit credentials, queries, fragments, and long opaque path components."""
    parts = urlsplit(value)
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    path = "/".join("[opaque]" if len(p) > 64 else p for p in parts.path.split("/"))
    return urlunsplit((parts.scheme, host, path, "", ""))


def safe_text(value, limit=2000):
    value = re.sub(r"https?://\S+", "[URL]", value)
    value = re.sub(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", "[email]", value)
    value = re.sub(r"\b[A-Za-z0-9_+=/-]{32,}\b", "[opaque]", value)
    return value[:limit]


def payload_signals(payload):
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    records = Counter(re.findall(r"(?:^|[|\x01])(?:F\|)?(EV|MA|PA);", payload))
    return {
        "bytes": len(payload.encode("utf-8")),
        "records": dict(records),
        "priced_participant_records": len(re.findall(r"(?:^|[|])PA;[^|]*\bOD=[^;|]+", payload)),
        "json_market_keys": len(JSON_MARKET_PATTERN.findall(payload)),
        "sports": sorted({m.upper() for m in SPORT_PATTERN.findall(payload)}),
        "prop_labels": sorted({m.lower() for m in PROP_PATTERN.findall(payload)}),
    }


def classify(status, text, candidates, navigation_error=None):
    lower = text.lower()
    if status in {401, 403, 429} or any(marker in lower for marker in BLOCK_MARKERS):
        return "access_blocked"
    if any(marker in lower for marker in LOCATION_MARKERS):
        return "location_restricted"
    if status is not None and status >= 400:
        return "http_error"
    if navigation_error:
        return "navigation_error"
    if not text.strip():
        return "empty_page"
    if candidates:
        return "market_payload_candidates_unvalidated"
    return "page_loaded_no_market_payload"


async def probe_page(context, url, directory, observe_seconds, navigation_timeout):
    from playwright.async_api import Error as PlaywrightError

    page = await context.new_page()
    network = []
    failed = []
    sockets = []
    candidates = []
    tasks = set()
    body_budget = 20_000_000
    http_counts = Counter()
    started = asyncio.get_running_loop().time()
    report = {"requested_url": safe_url(url), "started_at": datetime.now(UTC).isoformat()}

    async def response_received(response):
        nonlocal body_budget
        resource_type = response.request.resource_type
        http_counts[f"{resource_type}:{response.status}"] += 1
        if len(network) < 200:
            network.append({"url": safe_url(response.url), "status": response.status, "type": resource_type})
        if resource_type not in {"xhr", "fetch"} or response.status != 200 or body_budget <= 0:
            return
        host = urlsplit(response.url).hostname or ""
        target_host = urlsplit(url).hostname or ""
        if host != target_host and not host.endswith(".bet365.com"):
            return
        try:
            declared = int(response.headers.get("content-length", "0"))
            if declared > MAX_BODY_BYTES:
                return
            # Bound body reading as well as observation time during page shutdown.
            body = await asyncio.wait_for(response.body(), timeout=5)
            body_budget -= len(body)
            if len(body) > MAX_BODY_BYTES:
                return
            signals = payload_signals(body)
            if signals["records"] or signals["json_market_keys"]:
                if len(candidates) < 100:
                    candidates.append({"transport": "http", "url": safe_url(response.url), **signals})
        except (PlaywrightError, ValueError, TimeoutError):
            pass

    def response_event(response):
        task = asyncio.create_task(response_received(response))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def socket_opened(socket):
        socket_report = {"url": safe_url(socket.url), "frames_received": 0, "bytes_received": 0}
        sockets.append(socket_report)

        def received(payload):
            socket_report["frames_received"] += 1
            signals = payload_signals(payload)
            socket_report["bytes_received"] += signals["bytes"]
            if (signals["records"] or signals["json_market_keys"]) and len(candidates) < 100:
                candidates.append({"transport": "websocket", "url": safe_url(socket.url), **signals})

        socket.on("framereceived", received)

    page.on("response", response_event)
    page.on("websocket", socket_opened)
    page.on(
        "requestfailed",
        lambda request: failed.append(
            {
                "url": safe_url(request.url),
                "type": request.resource_type,
                "error": safe_text(request.failure or "unknown", 160),
            }
        )
        if len(failed) < 100
        else None,
    )
    status = None
    navigation_error = None
    text = ""
    try:
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=navigation_timeout * 1000)
            status = response.status if response else None
        except PlaywrightError as error:
            match = re.search(r"net::ERR_[A-Z_]+", str(error))
            navigation_error = match[0] if match else type(error).__name__
        # Do not retry, click through, or wait out an explicit access challenge.
        deadline = asyncio.get_running_loop().time() + observe_seconds
        while True:
            try:
                text = await page.locator("body").inner_text(timeout=2000)
            except PlaywrightError:
                text = ""
            disposition = classify(status, text, candidates, navigation_error)
            if disposition in {"access_blocked", "location_restricted", "http_error", "navigation_error"}:
                break
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(2, remaining))
        report.update(
            {
                "final_url": safe_url(page.url),
                "http_status": status,
                "navigation_error": navigation_error,
                "title": safe_text(await page.title(), 200),
                "classification": classify(status, text, candidates, navigation_error),
                "visible_text_excerpt": safe_text(text),
            }
        )
        if report["classification"] not in {"access_blocked", "location_restricted"}:
            links = await page.locator("a[href]").evaluate_all(
                "els => els.map(a => ({text: a.innerText, href: a.href})).slice(0, 500)"
            )
            report["league_links"] = [
                {"text": safe_text(link["text"], 100), "url": safe_url(link["href"])}
                for link in links
                if SPORT_PATTERN.search(link["text"]) and urlsplit(link["href"]).scheme in {"https", "http"}
            ][:30]
        try:
            await page.screenshot(path=str(directory / "page.png"), timeout=5000)
            report["screenshot"] = "page.png"
        except PlaywrightError:
            report["screenshot"] = None
    finally:
        page.remove_listener("response", response_event)
        pending = list(tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await page.close()
    report.update(
        {
            "elapsed_seconds": round(asyncio.get_running_loop().time() - started, 2),
            "http_counts": dict(http_counts),
            "network": network,
            "failed_requests": failed,
            "websockets": sockets,
            "market_payload_candidates": candidates,
            "validated_selections": 0,
            "coverage_verified": False,
        }
    )
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


async def run(args):
    from playwright.async_api import async_playwright

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary = {
        "started_at": datetime.now(UTC).isoformat(),
        "playwright_version": version("playwright"),
        "execution_location": args.execution_location,
        "headless": not getattr(args, "headed", False),
        "browser_channel": getattr(args, "channel", "chromium"),
        "pages": [],
        "production_database_modified": False,
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel=summary["browser_channel"], headless=summary["headless"]
        )
        summary["browser_version"] = browser.version
        try:
            context = await browser.new_context()
            for index, url in enumerate(args.url or ["https://va.bet365.com/"]):
                directory = output / f"page-{index + 1}"
                directory.mkdir(exist_ok=True)
                report = await probe_page(
                    context, url, directory, args.observe_seconds, args.navigation_timeout
                )
                item = {
                    k: report[k]
                    for k in (
                        "requested_url",
                        "final_url",
                        "http_status",
                        "classification",
                        "elapsed_seconds",
                        "validated_selections",
                        "coverage_verified",
                    )
                }
                item["websockets"] = len(report["websockets"])
                item["market_payload_candidates"] = len(report["market_payload_candidates"])
                item["report"] = f"page-{index + 1}/report.json"
                summary["pages"].append(item)
                print(json.dumps(item), flush=True)
            await context.close()
        finally:
            await browser.close()
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return (
        0
        if all(p["classification"] == "market_payload_candidates_unvalidated" for p in summary["pages"])
        else 2
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", help="Public page to observe; repeatable")
    parser.add_argument("--channel", choices=("chromium", "chrome", "msedge"), default="chromium")
    parser.add_argument(
        "--headed", action="store_true", help="Show a browser window for a local access check"
    )
    parser.add_argument("--observe-seconds", type=float, default=20)
    parser.add_argument("--navigation-timeout", type=float, default=30)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/bet365-probe"))
    parser.add_argument("--execution-location", default="local; AWS accessibility unverified")
    args = parser.parse_args()
    if not 0 <= args.observe_seconds <= 120 or not 0 < args.navigation_timeout <= 120:
        parser.error("observation must be 0-120 seconds; navigation timeout must be 1-120 seconds")
    for url in args.url or []:
        parts = urlsplit(url)
        if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
            parser.error("URLs must be HTTP(S), without embedded credentials")
    # Keep downloaded browsers inside the workspace; honor an explicitly configured external installation.
    cache = Path(__file__).resolve().parents[1] / ".cache" / "ms-playwright"
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(cache))
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
