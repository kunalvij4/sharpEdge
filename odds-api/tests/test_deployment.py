"""Run the real deployment script against a fake Docker CLI in temporary releases."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not shutil.which("bash") or not shutil.which("flock"),
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

    def run(*, failure="", image=IMAGE):
        result = subprocess.run(
            ["bash", str(release / "deploy/deploy.sh"), str(deploy_dir), image, "test-user", "existing-odds"],
            input="test-registry-token\n",
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


def test_deployment_preserves_project_and_pins_migration_and_api_to_one_digest(deployment):
    deploy_dir, release, previous, run = deployment
    result, calls = run()
    assert result.returncode == 0, result.stderr
    assert (deploy_dir / "current").resolve() == release
    assert (deploy_dir / "previous").resolve() == previous
    assert (release / "image").read_text().strip() == IMAGE
    assert (deploy_dir / ".env").read_text() == "POSTGRES_PASSWORD=existing-database-password\n"
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
    stop = next(i for i, args in enumerate(operations) if args == ["stop", "api"])
    migration = next(i for i, args in enumerate(operations) if "--exit-code-from" in args)
    ready = next(i for i, args in enumerate(operations) if "--wait" in args and args[-1] == "api")
    assert stop < migration < ready
    assert all("--no-build" in args for args in operations if args[0] == "up")
    assert not any("down" in args or "build" in args for args in operations)


@pytest.mark.parametrize("failure", ["pull", "migration", "readiness"])
def test_failed_deployment_keeps_successful_release_and_cleans_registry_credentials(deployment, failure):
    deploy_dir, release, previous, run = deployment
    result, calls = run(failure=failure)
    assert result.returncode != 0
    assert (deploy_dir / "current").resolve() == previous
    assert not (deploy_dir / "previous").exists()
    assert not (release / "image").exists()
    assert all(not Path(call["config"]).exists() for call in calls)
    args = [call["args"] for call in calls]
    if failure == "pull":
        assert not any("stop" in call for call in args)
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
