import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from odds_api.domain.models import League
from odds_api.infrastructure.config import DEFAULT_LEAGUES
from odds_api.infrastructure.normalization import Normalizer
from odds_api.infrastructure.repository import SqlRepository

ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.origin = datetime(2026, 10, 19, tzinfo=UTC)
        self.sleeps = []

    def monotonic(self):
        return self.value

    def now(self):
        return self.origin + timedelta(seconds=self.value)

    async def sleep(self, seconds):
        import asyncio

        self.sleeps.append(seconds)
        self.value += seconds
        await asyncio.sleep(0)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def raw():
    return json.loads((ROOT / "tests/fixtures/provider.json").read_text())


@pytest.fixture
def league():
    return League("basketball_nba", "NBA", "nba", "42")


@pytest.fixture
def board(raw, league, clock):
    def make(kind="moneyline", complete=True):
        return Normalizer().parse(
            league,
            kind,
            raw[kind]["data"],
            raw["sources"],
            raw["bets"],
            raw["periods"],
            raw["events"],
            raw["people"],
            raw["teams"],
            clock.now(),
            complete,
        )

    return make


@pytest.fixture(params=["sqlite"] + (["postgres"] if os.getenv("TEST_DATABASE_URL") else []))
def repo(request, tmp_path):
    url = (
        os.environ["TEST_DATABASE_URL"]
        if request.param == "postgres"
        else "sqlite:///" + (tmp_path / "test.db").as_posix()
    )
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    if request.param == "postgres":
        command.downgrade(config, "base")
    command.upgrade(config, "head")
    repository = SqlRepository(url, DEFAULT_LEAGUES)
    yield repository
    repository.close()
    if request.param == "postgres":
        command.downgrade(config, "base")
