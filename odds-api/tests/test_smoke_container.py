"""Verify the container's embedded seed and HTTP checks against Redis storage."""

import ast
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import fakeredis
from fastapi.testclient import TestClient

from odds_api.http.app import create_app
from odds_api.infrastructure import storage
from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings
from odds_api.infrastructure.redis_repository import RedisRepository


def test_smoke_seed_and_api_checks_use_redis(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "scripts/smoke_container.py").read_text())
    assignments = {
        node.targets[0].id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    fixture = json.loads((root / "tests/fixtures/provider.json").read_text())
    seed = eval(
        compile(ast.Expression(assignments["seed"]), "seed", "eval"), {"json": json, "fixture": fixture}
    )
    repository = RedisRepository("", DEFAULT_LEAGUES, client=fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(storage, "create_repository", lambda _: repository)
    monkeypatch.setattr(repository, "close", lambda: None)
    exec(seed, {})
    assert len(repository.events("nba_basketball")) == 1
    assert len(repository.quotes("nba_basketball")) == 5
    settings = Settings(_env_file=None, api_keys="smoke-product-key")
    with TestClient(create_app(settings, repository)) as client:

        def urlopen(request, timeout):
            response = client.get(request.full_url, headers=dict(request.header_items()))
            if response.status_code >= 400:
                raise HTTPError(request.full_url, response.status_code, "", {}, None)
            return io.BytesIO(response.content)

        monkeypatch.setattr("urllib.request.urlopen", urlopen)
        exec(ast.literal_eval(assignments["check"]), {})
