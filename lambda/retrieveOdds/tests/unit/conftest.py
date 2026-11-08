from pathlib import Path

from botocore.client import BaseClient
import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def pipeline_path(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))


@pytest.fixture(autouse=True)
def forbid_dynamodb_calls(monkeypatch):
    original = BaseClient._make_api_call

    def call(client, operation, parameters):
        assert client.meta.service_model.service_name != "dynamodb", "DynamoDB storage is disabled"
        return original(client, operation, parameters)

    monkeypatch.setattr(BaseClient, "_make_api_call", call)


@pytest.fixture
def aws_mock(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        yield
