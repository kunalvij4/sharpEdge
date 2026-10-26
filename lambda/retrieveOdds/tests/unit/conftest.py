import importlib
from pathlib import Path

import boto3
import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def pipeline_path(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))


@pytest.fixture
def closing_store(monkeypatch):
    monkeypatch.setenv("CLOSING_ODDS_TABLE", "test-closing-odds")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="test-closing-odds", BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "event_id", "KeyType": "HASH"},
                {"AttributeName": "bet_key", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "event_id", "AttributeType": "S"},
                {"AttributeName": "bet_key", "AttributeType": "S"},
            ],
        )
        client.update_time_to_live(
            TableName="test-closing-odds",
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"},
        )
        yield importlib.import_module("odds_pipeline.archive").ClosingOddsStore(client=client)
