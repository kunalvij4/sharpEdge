"""Exercise the real browser capture against synthetic HTTP and WebSocket odds.

No external requests, account credentials, or application database are used.
"""

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
from types import SimpleNamespace

from scripts.probe_bet365 import run

HTML = b"""<!doctype html><title>Probe fixture</title><body>NBA fixture
<script>
fetch('/odds').then(r => r.json());
const socket = new WebSocket('ws://' + location.host + '/socket');
socket.onmessage = () => document.body.dataset.received = 'true';
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
        if self.path == "/blocked":
            status, content_type, body = 403, "text/html", b"<body>Sorry, you have been blocked</body>"
        elif self.path == "/odds":
            status, content_type = 200, "application/json"
            body = json.dumps({"markets": [{"odds": 1.91}]}).encode()
        else:
            status, content_type, body = 200, "text/html", HTML
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


async def smoke(output):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        args = SimpleNamespace(
            output_dir=output,
            execution_location="local loopback fixture; synthetic data",
            url=[base, base + "/blocked"],
            observe_seconds=2,
            navigation_timeout=10,
        )
        await run(args)
        loaded = json.loads((output / "page-1" / "report.json").read_text())
        blocked = json.loads((output / "page-2" / "report.json").read_text())
        assert loaded["http_status"] == 200
        assert loaded["classification"] == "market_payload_candidates_unvalidated"
        assert {c["transport"] for c in loaded["market_payload_candidates"]} == {"http", "websocket"}
        assert any(c.get("priced_participant_records") == 1 for c in loaded["market_payload_candidates"])
        assert blocked["http_status"] == 403 and blocked["classification"] == "access_blocked"
        assert loaded["validated_selections"] == blocked["validated_selections"] == 0
        print("PASS: real Chromium HTTP/WebSocket capture and blocked-page classification", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    cache = Path(__file__).resolve().parents[1] / ".cache" / "ms-playwright"
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(cache))
    if args.output_dir:
        asyncio.run(smoke(args.output_dir.resolve()))
    else:
        with TemporaryDirectory() as directory:
            asyncio.run(smoke(Path(directory)))


if __name__ == "__main__":
    main()
