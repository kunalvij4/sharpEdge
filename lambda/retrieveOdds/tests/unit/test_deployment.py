from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml


STACK = "retrieve-odds-stack"


@pytest.fixture
def deployment():
    return importlib.import_module("scripts.report_deployment_failure"), Mock()


def test_diagnostics_report_validation_reason_for_latest_change_set(deployment, capsys):
    module, cloudformation = deployment
    changes, events = Mock(), Mock()
    cloudformation.get_paginator.side_effect = {"list_change_sets": changes, "describe_events": events}.__getitem__
    changes.paginate.return_value = [{"Summaries": [{
        "ChangeSetId": "old", "ChangeSetName": "old", "CreationTime": datetime(2026, 10, 25, tzinfo=timezone.utc),
    }]}, {"Summaries": [{
        "ChangeSetId": "latest", "ChangeSetName": "latest", "CreationTime": datetime(2026, 10, 26, tzinfo=timezone.utc),
        "Parameters": [{"ParameterValue": "test-password"}],
    }]}]
    events.paginate.return_value = [{"OperationEvents": [{
        "LogicalResourceId": "RetrieveOddsFunction", "EventType": "VALIDATION_ERROR",
        "ValidationStatusReason": "Invalid function configuration", "ValidationPath": "/Resources/RetrieveOddsFunction",
    }]}]
    module.report_failure(cloudformation, STACK)
    events.paginate.assert_called_once_with(ChangeSetName="latest", Filters={"FailedEvents": True})
    output = capsys.readouterr().out
    assert json.loads(output.splitlines()[-1])["reason"] == "Invalid function configuration"
    assert "test-password" not in output



def test_diagnostics_handle_missing_change_sets(deployment, capsys):
    module, cloudformation = deployment
    cloudformation.get_paginator.return_value.paginate.return_value = [{"Summaries": []}]
    module.report_failure(cloudformation, STACK)
    assert "No change set" in capsys.readouterr().out


def test_diagnostics_cli_only_connects_to_cloudformation(deployment, monkeypatch):
    module, cloudformation = deployment
    cloudformation.get_paginator.return_value.paginate.return_value = [{"Summaries": []}]
    client = Mock(return_value=cloudformation)
    monkeypatch.setattr(module.boto3, "client", client)
    monkeypatch.setattr("sys.argv", ["report_deployment_failure.py", "--stack-name", STACK, "--region", "us-east-1"])
    module.main()
    client.assert_called_once_with("cloudformation", region_name="us-east-1")


def test_sam_provisions_no_dynamodb_resources_permissions_or_settings():
    pipeline = Path(__file__).resolve().parents[2]
    template = yaml.load((pipeline / "template.yaml").read_text(), Loader=yaml.BaseLoader)
    resources = template["Resources"]
    assert all(resource["Type"] != "AWS::DynamoDB::Table" for resource in resources.values())
    function = resources["RetrieveOddsFunction"]["Properties"]
    assert function["Events"]["EveryFiveMinutes"]["Properties"]["Enabled"] == "true"
    assert function["Policies"] == [{"S3WritePolicy": {"BucketName": "OddsCacheBucket"}}]
    assert set(function["Environment"]["Variables"]) == {
        "ODDS_API_KEY", "ODDS_API_BASE_URL", "RESULTS_BUCKET", "REDIS_URL",
        "UNABATED_PARTNER_CODE",
    }
    assert "ExistingClosingOddsTableName" not in template["Parameters"]
    local_settings = json.loads((pipeline / "env.example.json").read_text())
    assert "CLOSING_ODDS_TABLE" not in local_settings["RetrieveOddsFunction"]


@pytest.mark.parametrize("summary, error", [
    ({"status": "complete", "events_fetched": 2, "ev_bets_found": 1, "bet_links": {"event": 1}}, False),
    ({"status": "complete", "events_fetched": 2, "ev_bets_found": 0}, False),
    ({"status": "partial", "events_fetched": 2}, True),
    ({"status": "complete", "events_fetched": 0}, True),
    ({"status": "complete", "events_fetched": 2, "ev_bets_found": 1, "bet_links": {}}, True),
])
def test_deployment_verification_checks_real_pipeline_summary(monkeypatch, summary, error):
    import io

    module = importlib.import_module("scripts.verify_deployment")
    cloudformation, runtime = Mock(), Mock()
    cloudformation.describe_stack_resource.return_value = {"StackResourceDetail": {"PhysicalResourceId": "actual-function"}}
    runtime.invoke.return_value = {"Payload": io.BytesIO(json.dumps(summary).encode())}
    client = Mock(side_effect=lambda service, **kwargs: {"cloudformation": cloudformation, "lambda": runtime}[service])
    monkeypatch.setattr(module.boto3, "client", client)
    monkeypatch.setattr("sys.argv", ["verify_deployment.py", "--stack-name", STACK])
    if error:
        with pytest.raises(RuntimeError):
            module.main()
    else:
        module.main()
    runtime.invoke.assert_called_once_with(
        FunctionName="actual-function", InvocationType="RequestResponse", Payload=b'{"deployment_verification":true}',
    )
