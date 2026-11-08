import importlib.util
from pathlib import Path
from unittest.mock import Mock

import boto3
import pytest


ROOT = Path(__file__).resolve().parents[4]


def load_legacy(monkeypatch, relative_path):
    monkeypatch.syspath_prepend(str(ROOT / "app"))
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(f"legacy_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def no_aws(monkeypatch):
    client, resource = Mock(side_effect=AssertionError("AWS access is disabled")), Mock(side_effect=AssertionError("AWS access is disabled"))
    monkeypatch.setattr(boto3, "client", client)
    monkeypatch.setattr(boto3, "resource", resource)
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    yield
    client.assert_not_called()
    resource.assert_not_called()


def test_legacy_database_skips_writes_reads_and_health_queries(monkeypatch, no_aws):
    db = load_legacy(monkeypatch, "app/db/crud.py").SharpEdgeDB()
    assert db.save_ev_bet("event", "FanDuel", 2.2, 2.0, 0.5, 10.0, "NBA", "moneyline") is None
    assert db.get_positive_ev_bets() == []
    assert db.test_connection() == {"connection": "DISABLED", "tables": {}}


def test_legacy_writer_does_not_connect_or_report_success(monkeypatch, no_aws):
    writer = load_legacy(monkeypatch, "app/db/dynamodb_store_ev_bets.py").DynamoDBClient("us-east-2", "EV_Bets")
    assert writer.store_data({"id": "event", "odds": 2.2}) is False


@pytest.mark.parametrize("payload", [None, {"id": "event", "odds": 2.2}])
def test_retired_store_bet_endpoint_returns_gone(monkeypatch, no_aws, payload):
    app = load_legacy(monkeypatch, "app/app.py").app
    response = app.test_client().put("/storeBet", json=payload)
    assert response.status_code == 410
    assert response.json == {"error": "Bet storage has been disabled", "stored": False}
