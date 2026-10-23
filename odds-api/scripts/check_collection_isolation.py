"""Restart only Bet365 and verify the real API/normal collector stay running."""

import json
import os
import signal
import time
import urllib.request
from pathlib import Path

from odds_api.infrastructure.config import Settings


def process(module):
    for path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            arguments = path.read_bytes().decode().strip("\0").split("\0")
            if arguments[1:3] == ["-m", module]:
                return int(path.parent.name)
        except (OSError, UnicodeError):
            continue
    return None


def main():
    settings = Settings()
    key = settings.api_keys.get_secret_value().split(",")[0].strip()

    def status():
        request = urllib.request.Request("http://localhost:8000/status", headers={"X-API-Key": key})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)

    api, collector, bet365 = (
        process(m) for m in ("uvicorn", "odds_api.collector", "odds_api.bet365_collector")
    )
    assert all((api, collector, bet365)), "All three application processes must be running"
    before = status()
    os.kill(bet365, signal.SIGTERM)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        time.sleep(2)
        after = status()
        replacement = process("odds_api.bet365_collector")
        assert process("uvicorn") == api and process("odds_api.collector") == collector
        if (
            replacement
            and replacement != bet365
            and after["collector_heartbeat"] > before["collector_heartbeat"]
        ):
            result = {
                "bet365_restarted": True,
                "api_pid_unchanged": True,
                "normal_collector_pid_unchanged": True,
                "heartbeat_advanced": True,
                "collector_healthy": after["collector_healthy"],
                "before_heartbeat": before["collector_heartbeat"],
                "after_heartbeat": after["collector_heartbeat"],
            }
            assert result["collector_healthy"]
            Path("/app/artifacts/isolation.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result))
            return
    raise RuntimeError("Independent Bet365 restart did not complete")


if __name__ == "__main__":
    main()
