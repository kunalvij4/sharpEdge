"""Run the real deployment script against a fake Docker CLI in temporary releases."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not shutil.which("bash") or not shutil.which("flock"),
    reason="Production deployment requires Linux, Bash, and flock",
)
ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ghcr.io/example/odds-api@sha256:" + "a" * 64
FAKE_DOCKER = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
with open(os.environ["DOCKER_CALLS"], "a") as calls:
    calls.write(json.dumps({
        "args": args,
        "image": os.environ.get("ODDS_API_IMAGE"),
        "config": os.environ.get("DOCKER_CONFIG"),
    }) + "\\n")
if args[0] == "login":
    assert sys.stdin.read().strip() == "test-registry-token"
    Path(os.environ["DOCKER_CONFIG"], "config.json").write_text("test credentials")
failure = os.environ.get("FAIL_AT")
if failure == "pull" and "pull" in args:
    sys.exit(11)
if failure == "migration" and "--exit-code-from" in args:
    sys.exit(12)
if failure == "redis_preflight" and "run" in args and "--entrypoint" in args:
    sys.exit(14)
if failure == "readiness" and "--wait" in args and args[-1] == "api":
    sys.exit(13)
"""


@pytest.fixture
def deployment(tmp_path):
    deploy_dir = tmp_path / "production"
    release = deploy_dir / "releases/new"
    (release / "deploy").mkdir(parents=True)
    shutil.copy2(ROOT / "deploy/deploy.sh", release / "deploy/deploy.sh")
    shutil.copy2(ROOT / "compose.yaml", release / "compose.yaml")
    (deploy_dir / ".env").write_text("POSTGRES_PASSWORD=existing-database-password\n")
    previous = deploy_dir / "releases/old"
    previous.mkdir()
    (deploy_dir / "current").symlink_to(previous)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o700)
    calls_path = tmp_path / "calls.jsonl"
    env = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "DOCKER_CALLS": str(calls_path),
    }

    def run(*, failure="", image=IMAGE, redis_url="rediss://default:test-redis-secret@example.test:6379"):
        result = subprocess.run(
            ["bash", str(release / "deploy/deploy.sh"), str(deploy_dir), image, "test-user", "existing-odds"],
            input="test-registry-token\n" + redis_url + "\n",
            text=True,
            capture_output=True,
            env={**env, "FAIL_AT": failure},
            timeout=15,
        )
        calls = (
            [json.loads(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
        )
        return result, calls

    return deploy_dir, release, previous, run


def test_deployment_preserves_project_and_pins_api_to_digest(deployment):
    deploy_dir, release, previous, run = deployment
    result, calls = run()
    assert result.returncode == 0, result.stderr
    assert (deploy_dir / "current").resolve() == release
    assert (deploy_dir / "previous").resolve() == previous
    assert (release / "image").read_text().strip() == IMAGE
    assert (deploy_dir / ".env").read_text() == (
        "POSTGRES_PASSWORD=existing-database-password\n\n"
        "REDIS_URL='rediss://default:test-redis-secret@example.test:6379'\n"
    )
    assert (deploy_dir / ".env").stat().st_mode & 0o777 == 0o600
    assert "test-redis-secret" not in result.stdout + result.stderr
    assert all(call["image"] == IMAGE for call in calls)
    assert all(not Path(call["config"]).exists() for call in calls)
    assert "test-registry-token" not in result.stdout + result.stderr
    compose_calls = [call["args"] for call in calls if call["args"][0] == "compose"]
    prefix = [
        "compose",
        "--project-name",
        "existing-odds",
        "--env-file",
        str(deploy_dir / ".env"),
        "--file",
        str(release / "compose.yaml"),
    ]
    assert all(args[: len(prefix)] == prefix for args in compose_calls)
    operations = [args[len(prefix) :] for args in compose_calls]
    assert ["pull", "api"] in operations
    preflight = next(args for args in operations if args[0] == "run")
    assert preflight[:7] == ["run", "--rm", "--no-deps", "--entrypoint", "python", "api", "-c"]
    assert operations.index(["pull", "api"]) < operations.index(preflight)
    assert operations.index(preflight) < next(i for i, args in enumerate(operations) if args[0] == "up")
    assert any("--remove-orphans" in args and "--wait" in args for args in operations)
    assert not any("migrate" in args or "db" in args for args in operations)
    assert all("--no-build" in args for args in operations if args[0] == "up")
    assert not any("down" in args or "build" in args for args in operations)


@pytest.mark.parametrize("failure", ["pull", "redis_preflight", "readiness"])
def test_failed_deployment_keeps_successful_release_and_cleans_registry_credentials(deployment, failure):
    deploy_dir, release, previous, run = deployment
    result, calls = run(failure=failure)
    assert result.returncode != 0
    assert (deploy_dir / "current").resolve() == previous
    assert not (deploy_dir / "previous").exists()
    assert not (release / "image").exists()
    assert all(not Path(call["config"]).exists() for call in calls)
    args = [call["args"] for call in calls]
    if failure in {"pull", "redis_preflight"}:
        assert not any("stop" in call for call in args)
        assert not any("up" in call for call in args)
    if failure == "migration":
        assert not any("up" in call and call[-1] == "api" for call in args)


def test_missing_runtime_secrets_fail_before_touching_docker(deployment):
    deploy_dir, _, previous, run = deployment
    (deploy_dir / ".env").unlink()
    result, calls = run()
    assert result.returncode != 0
    assert "Missing" in result.stderr
    assert calls == []
    assert (deploy_dir / "current").resolve() == previous


def test_mutable_image_tag_is_rejected_before_touching_docker(deployment):
    _, _, _, run = deployment
    result, calls = run(image="ghcr.io/example/odds-api:latest")
    assert result.returncode != 0
    assert "digest" in result.stderr
    assert calls == []


@pytest.mark.parametrize(
    "existing", ["REDIS_URL='rediss://existing:6379'", "export REDIS_URL = existing", "REDIS_URL="]
)
def test_existing_redis_url_is_preserved(deployment, existing):
    deploy_dir, _, _, run = deployment
    (deploy_dir / ".env").write_text(existing + "\n")
    result, _ = run(redis_url="")
    assert result.returncode == 0, result.stderr
    assert (deploy_dir / ".env").read_text() == existing + "\n"


def test_missing_redis_secret_fails_before_docker(deployment):
    _, _, _, run = deployment
    result, calls = run(redis_url="")
    assert result.returncode != 0
    assert "ODDS_REDIS_URL" in result.stderr
    assert not calls


def test_redis_credentials_are_literal_and_not_executed(deployment):
    deploy_dir, _, _, run = deployment
    url = "rediss://default:p$word$(false)`false`#x@example.test:6379"
    result, _ = run(redis_url=url)
    assert result.returncode == 0, result.stderr
    assert "REDIS_URL='" + url + "'" in (deploy_dir / ".env").read_text()
    assert url not in result.stdout + result.stderr
