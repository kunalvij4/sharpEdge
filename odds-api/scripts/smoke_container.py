"""Exercise the built image with disposable containers and synthetic data only."""

import argparse
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4


def docker(*args, check=True, input=None):
    return subprocess.run(
        ["docker", *args], check=check, input=input, capture_output=True, text=True, timeout=90
    )


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
    url = f"postgresql+psycopg://odds:smoke-only@{database}:5432/odds"
    common = ["--network", network, "--env", "DATABASE_URL=" + url]
    try:
        docker("network", "create", network)
        docker(
            "run",
            "-d",
            "--name",
            database,
            "--network",
            network,
            "--env",
            "POSTGRES_USER=odds",
            "--env",
            "POSTGRES_PASSWORD=smoke-only",
            "--env",
            "POSTGRES_DB=odds",
            "postgres:17.6-bookworm",
        )
        wait_for(
            lambda: docker(
                "exec", database, "pg_isready", "-h", "127.0.0.1", "-U", "odds", "-d", "odds", check=False
            ).returncode
            == 0
        )
        docker("run", "--rm", *common, args.image, "alembic", "upgrade", "head")

        fixture = json.loads(
            (Path(__file__).resolve().parents[1] / "tests/fixtures/provider.json").read_text()
        )
        seed = """
import json, os
from datetime import UTC, datetime, timedelta
from odds_api.domain.models import League
from odds_api.infrastructure.config import DEFAULT_LEAGUES
from odds_api.infrastructure.normalization import Normalizer
from odds_api.infrastructure.repository import SqlRepository
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
repository = SqlRepository(os.environ["DATABASE_URL"], DEFAULT_LEAGUES)
for kind in ("moneyline", "props"):
    board = Normalizer().parse(League("basketball_nba", "NBA", "nba", "42"), kind,
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
assert len(get("/v4/sports")) == 3
odds = get("/v4/sports/basketball_nba/odds?oddsFormat=american")
assert len(odds) == 1 and len(odds[0]["bookmakers"][0]["markets"][0]["outcomes"]) == 2
eid = odds[0]["id"]
props = get("/v4/sports/basketball_nba/events/"+eid+"/odds?markets=player_points")
assert props["bookmakers"][0]["markets"][0]["outcomes"][0]["description"] == "Sample Player"
all_props = get("/v4/sports/basketball_nba/events/"+eid+"/props")
assert {m["key"] for b in all_props["bookmakers"] for m in b["markets"]} == {"player_points", "player_points_alternate"}
assert all_props["freshness"]["status"] == "fresh"
assert all(o["freshness"]["actionable"] for b in all_props["bookmakers"] for m in b["markets"] for o in m["outcomes"])
assert get("/health/live", auth=False)["status"] == "ok"
assert "openapi" in get("/openapi.json", auth=False)
try:
    get("/v4/sports", auth=False)
except urllib.error.HTTPError as error:
    assert error.code == 401
else:
    raise AssertionError("Product access was unauthenticated")
print("two-worker API, authentication, persisted moneylines/props, and OpenAPI passed")
"""
        print(docker("exec", api, "python", "-c", check).stdout.strip())
        assert docker("exec", api, "id", "-u").stdout.strip() == "10001"

        docker("restart", database)
        wait_for(
            lambda: docker(
                "exec", database, "pg_isready", "-h", "127.0.0.1", "-U", "odds", "-d", "odds", check=False
            ).returncode
            == 0
        )
        docker("restart", api)
        wait_for(lambda: docker("exec", api, "python", "-c", ready, check=False).returncode == 0)
        docker("exec", api, "python", "-c", check)
        print("data survived database and API container restarts")

        # A local closed port exercises an outage; no request is made to Unabated.
        collector_env = [
            "--env",
            "UNABATED_API_KEY=smoke-provider-key",
            "--env",
            "UNABATED_API_BASE_URL=https://127.0.0.1:9",
            "--env",
            "MAX_ATTEMPTS=1",
            "--env",
            "REQUEST_TIMEOUT=1",
        ]
        docker(
            "run",
            "-d",
            "--name",
            collector,
            *common,
            *collector_env,
            args.image,
            "python",
            "-m",
            "odds_api.collector",
        )
        check_health = """
import json,urllib.request
request=urllib.request.Request("http://localhost:8000/status",headers={"X-API-Key":"smoke-product-key"})
with urllib.request.urlopen(request,timeout=3) as response:
    status=json.load(response)
assert status["collector_healthy"]
assert any(scope["failures"] for scope in status["scopes"])
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
        docker("stop", "--time", "10", collector)
        logs = docker("logs", collector)
        assert "smoke-provider-key" not in logs.stdout + logs.stderr
        assert "collector_stopped" in logs.stdout + logs.stderr
        print(
            "provider outage cache, collector ownership, credential redaction, and graceful shutdown passed"
        )
    finally:
        for name in names:
            docker("rm", "--force", "--volumes", name, check=False)
        docker("network", "rm", network, check=False)


if __name__ == "__main__":
    main()
