"""Exercise the built image with disposable containers and synthetic data only."""

import argparse
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4


def docker(*args, check=True, input=None):
    result = subprocess.run(["docker", *args], input=input, capture_output=True, text=True, timeout=90)
    if check and result.returncode:
        raise RuntimeError("Container smoke operation failed: " + result.stderr)
    return result


def wait_for(check, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.5)
    raise RuntimeError("Container smoke check did not become ready")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="odds-api:phase1")
    args = parser.parse_args()
    prefix = "odds-smoke-" + uuid4().hex[:10]
    network, database, api, collector = (prefix + suffix for suffix in ("-net", "-db", "-api", "-collector"))
    names = [collector, api, database]
    url = f"redis://{database}:6379/0"
    common = ["--network", network, "--env", "STORAGE_BACKEND=redis", "--env", "REDIS_URL=" + url]
    try:
        docker("network", "create", network)
        docker(
            "run",
            "-d",
            "--name",
            database,
            "--network",
            network,
            "redis:7.4.2-bookworm",
            "redis-server",
            "--appendonly",
            "yes",
            "--appendfsync",
            "always",
        )
        wait_for(lambda: docker("exec", database, "redis-cli", "ping", check=False).stdout.strip() == "PONG")

        fixture = json.loads(
            (Path(__file__).resolve().parents[1] / "tests/fixtures/provider.json").read_text()
        )
        seed = """
import json, os
from datetime import UTC, datetime, timedelta
from odds_api.domain.models import League
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.normalization import Normalizer
from odds_api.infrastructure.storage import create_repository
raw = json.loads(FIXTURE)
now = datetime.now(UTC)
def refresh(node):
    if isinstance(node, dict):
        if "modifiedOn" in node: node["modifiedOn"] = now.isoformat()
        if "eventStart" in node: node["eventStart"] = (now + timedelta(hours=1)).isoformat()
        for value in node.values(): refresh(value)
    elif isinstance(node, list):
        for value in node: refresh(value)
refresh(raw)
repository = create_repository(Settings())
for kind in ("moneyline", "props"):
    board = Normalizer().parse(League("nba_basketball", "NBA", "nba", "42"), kind,
        raw[kind]["data"], raw["sources"], raw["bets"], raw["periods"], raw["events"],
        raw["people"], raw["teams"], now)
    repository.save(board)
repository.close()
""".replace("FIXTURE", repr(json.dumps(fixture)))
        docker("run", "--rm", "-i", *common, args.image, "python", "-", input=seed)
        docker(
            "run",
            "-d",
            "--name",
            api,
            *common,
            "--env",
            "API_KEYS=smoke-product-key",
            "--env",
            "BET365_ENABLED=true",
            "--env",
            "BET365_INGEST_KEY=smoke-collector-key",
            args.image,
            "uvicorn",
            "odds_api.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--workers",
            "2",
            "--no-access-log",
        )

        ready = (
            "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready',timeout=2)"
        )
        wait_for(lambda: docker("exec", api, "python", "-c", ready, check=False).returncode == 0)
        check = """
import json, urllib.request, urllib.error
base = "http://localhost:8000"
def get(path, auth=True):
    request = urllib.request.Request(base+path, headers={"X-API-Key": "smoke-product-key"} if auth else {})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)
assert len(get("/v1/sports")) == 6
odds = get("/v1/sports/nba_basketball/odds?oddsFormat=american")
assert len(odds) == 1 and len(odds[0]["bookmakers"][0]["markets"][0]["outcomes"]) == 2
eid = odds[0]["id"]
props = get("/v1/events/"+eid+"/odds?markets=player_points")
assert props["bookmakers"][0]["markets"][0]["outcomes"][0]["description"] == "Sample Player"
all_props = get("/v1/events/"+eid+"/props")
assert {m["key"] for b in all_props["bookmakers"] for m in b["markets"]} == {"player_points", "player_points_alternate"}
assert all_props["freshness"]["status"] == "fresh"
assert all(set(o) == {"name", "price", "point", "description"} for b in all_props["bookmakers"] for m in b["markets"] for o in m["outcomes"])
assert get("/health/live", auth=False)["status"] == "ok"
assert "openapi" in get("/openapi.json", auth=False)
try:
    get("/v1/sports", auth=False)
except urllib.error.HTTPError as error:
    assert error.code == 401
else:
    raise AssertionError("Product access was unauthenticated")
print("two-worker API, authentication, persisted moneylines/props, and OpenAPI passed")
"""
        print(docker("exec", api, "python", "-c", check).stdout.strip())
        assert docker("exec", api, "id", "-u").stdout.strip() == "10001"

        streaming = """
import json, urllib.request, urllib.error
from datetime import UTC, datetime
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.storage import create_repository
repository = create_repository(Settings())
event = repository.events("nba_basketball")[0]
before = repository.quotes("nba_basketball")
expiry = repository.client.pexpiretime(repository.key("event:" + event["id"]))
def row(kind, **fields): return {"type": kind, "fields": fields}
payload = {"version":1,"region":"nj","league":"nba_basketball","messages":[{
    "stage":"nba_lines", "received_at":datetime.now(UTC).isoformat(),
    "source_url":"https://www.nj.bet365.com/contentdata/matchmarketscontentapi/markets",
    "records":[row("CL",L3="NBA"), row("MG",SY="cmx"), row("MA",SY="ef"),
        row("PA",OI="local-capture",NA=event["away"],N2=event["home"],BC=event["start"].strftime("%Y%m%d%H%M%S")),
        row("MA",SY="eo",NA="Money"),
        row("PA",OI="local-capture",FI="market",ID="away",OD="7/5"),
        row("PA",OI="local-capture",FI="market",ID="home",OD="4/7")]}]}
base = "http://localhost:8000"
for attempt in range(2):
    request = urllib.request.Request(base+"/v1/ingest/bet365",data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json","X-Collector-Key":"smoke-collector-key"})
    with urllib.request.urlopen(request,timeout=10) as response:
        assert json.load(response)["accepted_selections"] == 2
assert len(repository.quotes("nba_basketball")) == len(before)+2
assert [r for r in repository.quotes("nba_basketball") if r["book_key"]!="bet365"] == before
assert repository.client.pexpiretime(repository.key("event:"+event["id"])) == expiry
request = urllib.request.Request(base+"/v1/sports/nba_basketball/odds?oddsFormat=american",headers={"X-API-Key":"smoke-product-key"})
with urllib.request.urlopen(request,timeout=10) as response:
    event = json.load(response)[0]
    assert len(event["bookmakers"]) == 2
    bet365 = next(b for b in event["bookmakers"] if b["key"]=="bet365")
    assert {o["price"] for o in bet365["markets"][0]["outcomes"]} == {140,-175}
repository.close()
print("Bet365 HTTP ingestion, replay deduplication, real Redis merge, and public API passed")
"""
        print(docker("exec", api, "python", "-c", streaming).stdout.strip())

        compact = """
from redis.exceptions import OutOfMemoryError
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.redis_repository import decode_document, encode
from odds_api.infrastructure.storage import create_repository
repository = create_repository(Settings())
event = repository.events("nba_basketball")[0]
key = repository.key("event:" + event["id"])
legacy = encode(decode_document(repository.client.get(key)))
repository.client.set(key, legacy, keepttl=True)
expiry = repository.client.pexpiretime(key)
before = repository.quotes("nba_basketball")
try:
    repository.client.config_set("maxmemory", 1)
    try:
        repository.client.set(repository.key("oom-probe"), "blocked")
    except OutOfMemoryError:
        pass
    else:
        raise AssertionError("Redis did not enforce the synthetic memory limit")
    counts = repository.compact_event_documents()
    assert counts["compressed_events"] == 1
    assert counts["bytes_after"] < counts["bytes_before"]
    assert decode_document(repository.client.get(key)) == decode_document(legacy)
    assert repository.client.pexpiretime(key) == expiry
    assert repository.quotes("nba_basketball") == before
finally:
    repository.client.config_set("maxmemory", 0)
    repository.close()
print("lossless event compression recovered a full Redis and preserved quotes/expiry")
"""
        print(docker("exec", api, "python", "-c", compact).stdout.strip())
        docker("exec", api, "python", "-c", check)

        docker("restart", database)
        wait_for(lambda: docker("exec", database, "redis-cli", "ping", check=False).stdout.strip() == "PONG")
        docker("restart", api)
        wait_for(lambda: docker("exec", api, "python", "-c", ready, check=False).returncode == 0)
        docker("exec", api, "python", "-c", check)
        print("data survived database and API container restarts")

        # A local closed port exercises an outage; no request is made to Unabated.
        collector_env = [
            "--env",
            "API_KEYS=smoke-product-key",
            "--env",
            "PROPLINE_ENABLED=false",
            "--env",
            "UNABATED_API_KEY=smoke-provider-key",
            "--env",
            "UNABATED_API_BASE_URL=https://127.0.0.1:9",
            "--env",
            "MAX_ATTEMPTS=1",
            "--env",
            "REQUEST_TIMEOUT=1",
            "--env",
            "COLLECTION_STATE_PATH=/app/artifacts/smoke-schedule.json",
        ]
        # Resume at the Unabated slot so the outage is exercised immediately,
        # without waiting four minutes or changing production scheduling.
        start_runtime = """
import json, os, time
from pathlib import Path
Path(os.environ["COLLECTION_STATE_PATH"]).write_text(json.dumps({"origin": time.time()-240, "slot": 1}))
os.execvp("python", ["python", "-m", "odds_api.runtime"])
"""
        docker(
            "run",
            "-d",
            "--name",
            collector,
            *common,
            *collector_env,
            args.image,
            "python",
            "-c",
            start_runtime,
        )
        wait_for(lambda: docker("exec", collector, "python", "-c", ready, check=False).returncode == 0)
        check_health = """
import json,urllib.request
request=urllib.request.Request("http://localhost:8000/v1/status",headers={"X-API-Key":"smoke-product-key"})
with urllib.request.urlopen(request,timeout=3) as response:
    status=json.load(response)
assert status["collector_healthy"]
assert status["provider_metrics"].get("requests", 0) > 0
assert status["unabated"]["odds_enabled"] is True
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.storage import create_repository
repository = create_repository(Settings())
assert repository.client.hlen(repository.key("failures")) > 0
repository.close()
"""
        wait_for(lambda: docker("exec", api, "python", "-c", check_health, check=False).returncode == 0)
        second = docker(
            "run",
            "--rm",
            *common,
            *collector_env,
            args.image,
            "python",
            "-m",
            "odds_api.collector",
            check=False,
        )
        assert second.returncode != 0 and "Another collector owns" in second.stderr
        docker("exec", api, "python", "-c", check)
        expiry_seed = seed.replace(
            "repository.close()",
            """
from dataclasses import replace
expiring = replace(board.events[0], source_id="expires-during-outage", start=now+timedelta(seconds=3))
repository.save(replace(board, events=(expiring,), quotes=tuple(replace(q, event_id=expiring.id) for q in board.quotes), complete=False))
repository.close()
""",
        )
        docker("run", "--rm", "-i", *common, args.image, "python", "-", input=expiry_seed)
        expiry_check = """
import os
from odds_api.infrastructure.storage import create_repository
from odds_api.infrastructure.config import Settings
from odds_api.domain.models import Event
from datetime import UTC, datetime
repository = create_repository(Settings())
expired = Event("expires-during-outage", "nba_basketball", datetime.now(UTC), "home", "away", "pregame")
assert not repository.client.exists(repository.key("event:" + expired.id))
assert len(repository.events("nba_basketball")) == 1
rows = repository.quotes("nba_basketball")
assert len([r for r in rows if r["book_key"] != "bet365"]) == 5
assert len([r for r in rows if r["book_key"] == "bet365"]) == 2
repository.close()
"""
        wait_for(lambda: docker("exec", api, "python", "-c", expiry_check, check=False).returncode == 0)
        docker("exec", api, "python", "-c", check)
        print("commenced events and all child odds deleted during provider outage")
        docker("stop", "--time", "10", collector)
        logs = docker("logs", collector)
        assert "smoke-provider-key" not in logs.stdout + logs.stderr
        assert docker("inspect", "--format", "{{.State.ExitCode}}", collector).stdout.strip() == "0"
        print(
            "provider outage cache, collector ownership, credential redaction, and graceful shutdown passed"
        )
    except Exception:
        # Only synthetic credentials are used by these disposable containers.
        for name in (api, collector, database):
            logs = docker("logs", "--tail", "80", name, check=False)
            output = logs.stdout + logs.stderr
            for secret in ("smoke-product-key", "smoke-provider-key"):
                output = output.replace(secret, "[REDACTED]")
            print(f"Smoke failure logs ({name}):\n{output}", flush=True)
        raise
    finally:
        for name in names:
            docker("rm", "--force", "--volumes", name, check=False)
        docker("network", "rm", network, check=False)


if __name__ == "__main__":
    main()
