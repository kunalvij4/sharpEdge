"""Verify real headed Edge, X display, HTTP and WebSocket capture locally."""

import argparse
import asyncio
import json
import os
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from scripts.bet365_browser_runtime import close_native_browser, launch_native_browser
from scripts.probe_bet365 import probe_page
from scripts.smoke_bet365_probe import Handler


async def smoke(output, no_sandbox):
    from playwright.async_api import async_playwright

    output.mkdir(parents=True, exist_ok=True)
    if not os.environ.get("DISPLAY"):
        raise RuntimeError("DISPLAY is missing; run this check under xvfb-run")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        async with async_playwright() as playwright:
            browser, process = await launch_native_browser(
                playwright,
                "msedge",
                Path(".cache/container-smoke-profile"),
                output / "browser.log",
                no_sandbox=no_sandbox,
            )
            try:
                context = browser.contexts[0]
                report = await probe_page(context, f"http://127.0.0.1:{server.server_port}", output, 3, 15)
                assert report["http_status"] == 200, report
                assert {item["transport"] for item in report["market_payload_candidates"]} == {
                    "http",
                    "websocket",
                }, report
                session = await browser.new_browser_cdp_session()
                version = await session.send("Browser.getVersion")
                assert "Edg/" in version["userAgent"], version
                assert "HeadlessChrome" not in version["userAgent"], version
                command = Path(f"/proc/{process.pid}/cmdline").read_bytes().split(b"\0")
                assert not any(arg.startswith(b"--headless") for arg in command), command
                result = {
                    "passed": True,
                    "display": os.environ["DISPLAY"],
                    "browser_version": browser.version,
                    "browser_product": version["product"],
                    "headless": False,
                    "user_agent": version["userAgent"],
                    "sandbox_disabled": no_sandbox,
                    "uid": os.getuid(),
                    "http_and_websocket_capture": True,
                }
                (output / "smoke-result.json").write_text(
                    json.dumps(result, indent=2) + "\n", encoding="utf-8"
                )
                print(json.dumps(result), flush=True)
            finally:
                await close_native_browser(browser, process)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/smoke"))
    parser.add_argument("--no-browser-sandbox", action="store_true")
    args = parser.parse_args()
    asyncio.run(smoke(args.output_dir.resolve(), args.no_browser_sandbox))


if __name__ == "__main__":
    main()
