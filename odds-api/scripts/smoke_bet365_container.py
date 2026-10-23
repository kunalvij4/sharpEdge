"""Verify headed Edge, Xvfb, and production record parsing against a local fixture."""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.bet365_browser_runtime import close_native_browser, launch_native_browser
from scripts.capture_bet365_markets import records

HTML = b"""<!doctype html><title>Browser fixture</title><body>NBA fixture
<script>
fetch('/odds').then(r => r.text());
const socket = new WebSocket('ws://' + location.host + '/socket');
</script></body>"""
WIRE = b"\x14fixture\x01F|EV;ID=event;|MA;ID=market;|PA;ID=selection;OD=10/11;|"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/socket":
            key = self.headers["Sec-WebSocket-Key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
            accept = base64.b64encode(hashlib.sha1(key.encode()).digest()).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.wfile.write(bytes([0x81, len(WIRE)]) + WIRE)
            self.wfile.flush()
            return
        body, content_type = (WIRE, "text/plain") if self.path == "/odds" else (HTML, "text/html")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


async def smoke(output):
    from playwright.async_api import async_playwright

    output.mkdir(parents=True, exist_ok=True)
    if not os.environ.get("DISPLAY"):
        raise RuntimeError("DISPLAY is missing; run this check in the application container")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TemporaryDirectory(prefix="bet365-smoke-") as profile:
            async with async_playwright() as playwright:
                browser, process = await launch_native_browser(
                    playwright, "msedge", Path(profile), output / "browser.log"
                )
                tasks = set()
                try:
                    page = await browser.contexts[0].new_page()
                    base = f"http://127.0.0.1:{server.server_port}"
                    captured = {}
                    http_ready, websocket_ready = asyncio.Event(), asyncio.Event()

                    async def response_body(response):
                        if response.url == base + "/odds":
                            assert response.status == 200
                            captured["http"] = records(await response.text())
                            http_ready.set()

                    def received(response):
                        task = asyncio.create_task(response_body(response))
                        tasks.add(task)

                    def socket_opened(socket):
                        def frame(payload):
                            text = payload.decode() if isinstance(payload, bytes) else payload
                            captured["websocket"] = records(text)
                            websocket_ready.set()

                        socket.on("framereceived", frame)

                    page.on("response", received)
                    page.on("websocket", socket_opened)
                    await page.goto(base)
                    await asyncio.wait_for(asyncio.gather(http_ready.wait(), websocket_ready.wait()), 10)
                    for transport in ("http", "websocket"):
                        assert any(
                            row["type"] == "PA" and row["fields"].get("OD") == "10/11"
                            for row in captured[transport]
                        )
                    session = await browser.new_browser_cdp_session()
                    version = await session.send("Browser.getVersion")
                    assert "Edg/" in version["userAgent"] and "HeadlessChrome" not in version["userAgent"]
                    command = Path(f"/proc/{process.pid}/cmdline").read_bytes().split(b"\0")
                    assert not any(arg.startswith(b"--headless") or arg == b"--no-sandbox" for arg in command)
                    await page.screenshot(path=str(output / "browser.png"))
                    result = {
                        "passed": True,
                        "display": os.environ["DISPLAY"],
                        "browser_version": browser.version,
                        "headless": False,
                        "sandbox_disabled": False,
                        "uid": os.getuid(),
                        "http_and_websocket_capture": True,
                    }
                    (output / "smoke-result.json").write_text(json.dumps(result, indent=2) + "\n")
                    print(json.dumps(result), flush=True)
                    page.remove_listener("response", received)
                finally:
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                    await close_native_browser(browser, process)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("/app/artifacts/smoke"))
    args = parser.parse_args()
    asyncio.run(smoke(args.output_dir.resolve()))


if __name__ == "__main__":
    main()
