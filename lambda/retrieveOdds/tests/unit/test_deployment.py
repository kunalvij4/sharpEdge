from datetime import datetime, timezone
import importlib
import json
from unittest.mock import Mock

from botocore.exceptions import ClientError
import pytest


STACK = "retrieve-odds-stack"
TABLE = f"{STACK}-ClosingOdds"


def aws_error(code, operation, message="test failure"):
    return ClientError({"Error": {"Code": code, "Message": message}}, operation)


@pytest.fixture
def deployment():
    module = importlib.import_module("scripts.resolve_closing_table")
    cloudformation, dynamodb = Mock(), Mock()
    cloudformation.describe_stacks.return_value = {"Stacks": [{"Parameters": []}]}
    cloudformation.get_paginator.return_value.paginate.return_value = [{"StackResourceSummaries": []}]
    dynamodb.describe_table.return_value = {"Table": {
        "KeySchema": [{"AttributeName": "event_id", "KeyType": "HASH"}, {"AttributeName": "bet_key", "KeyType": "RANGE"}],
        "AttributeDefinitions": [{"AttributeName": name, "AttributeType": "S"} for name in ("event_id", "bet_key")],
    }}
    dynamodb.describe_time_to_live.return_value = {"TimeToLiveDescription": {
        "TimeToLiveStatus": "ENABLED", "AttributeName": "expires_at",
    }}
    return module, cloudformation, dynamodb


def test_retained_table_is_discovered_with_no_repository_variable(deployment):
    module, cloudformation, dynamodb = deployment
    assert module.resolve_table(cloudformation, dynamodb, STACK) == TABLE
    dynamodb.describe_table.assert_called_once_with(TableName=TABLE)


@pytest.mark.parametrize("status", ["DELETE_SKIPPED", "DELETE_COMPLETE"])
def test_rolled_back_resource_is_reused_as_an_external_table(deployment, status):
    module, cloudformation, dynamodb = deployment
    cloudformation.get_paginator.return_value.paginate.return_value = [{"StackResourceSummaries": [{
        "LogicalResourceId": "ClosingOddsTable", "ResourceStatus": status, "PhysicalResourceId": TABLE,
    }]}]
    assert module.resolve_table(cloudformation, dynamodb, STACK) == TABLE


def test_managed_table_on_later_resource_page_keeps_cloudformation_ownership(deployment):
    module, cloudformation, dynamodb = deployment
    cloudformation.get_paginator.return_value.paginate.return_value = [
        {"StackResourceSummaries": []},
        {"StackResourceSummaries": [{
            "LogicalResourceId": "ClosingOddsTable", "ResourceStatus": "CREATE_COMPLETE", "PhysicalResourceId": TABLE,
        }]},
    ]
    assert module.resolve_table(cloudformation, dynamodb, STACK, TABLE) == ""
    dynamodb.describe_table.assert_not_called()
    with pytest.raises(ValueError, match="already managed"):
        module.resolve_table(cloudformation, dynamodb, STACK, "other-table")


@pytest.mark.parametrize("stack_exists", [False, True])
def test_missing_table_is_created_normally(deployment, stack_exists):
    module, cloudformation, dynamodb = deployment
    if not stack_exists:
        cloudformation.describe_stacks.side_effect = aws_error(
            "ValidationError", "DescribeStacks", f"Stack with id {STACK} does not exist",
        )
    dynamodb.describe_table.side_effect = aws_error("ResourceNotFoundException", "DescribeTable")
    assert module.resolve_table(cloudformation, dynamodb, STACK) == ""
    dynamodb.describe_time_to_live.assert_not_called()


def test_previous_external_table_is_preserved_when_variable_is_unset(deployment):
    module, cloudformation, dynamodb = deployment
    cloudformation.describe_stacks.return_value["Stacks"][0]["Parameters"] = [{
        "ParameterKey": "ExistingClosingOddsTableName", "ParameterValue": "previous-table",
    }]
    assert module.resolve_table(cloudformation, dynamodb, STACK) == "previous-table"
    dynamodb.describe_table.assert_called_once_with(TableName="previous-table")
    assert module.resolve_table(cloudformation, dynamodb, STACK, "override-table") == "override-table"


def test_missing_configured_table_does_not_silently_switch_to_a_new_table(deployment):
    module, cloudformation, dynamodb = deployment
    dynamodb.describe_table.side_effect = aws_error("ResourceNotFoundException", "DescribeTable")
    with pytest.raises(ValueError, match="does not exist"):
        module.resolve_table(cloudformation, dynamodb, STACK, "configured-table")


@pytest.mark.parametrize("service, method", [
    ("cloudformation", "describe_stacks"), ("dynamodb", "describe_table"), ("dynamodb", "describe_time_to_live"),
])
def test_aws_read_errors_stop_deployment(deployment, service, method):
    module, cloudformation, dynamodb = deployment
    client = cloudformation if service == "cloudformation" else dynamodb
    getattr(client, method).side_effect = aws_error("AccessDeniedException", method)
    with pytest.raises(ClientError, match="AccessDeniedException"):
        module.resolve_table(cloudformation, dynamodb, STACK)


@pytest.mark.parametrize("invalid", ["key_name", "key_type", "ttl_attribute", "ttl_disabled"])
def test_incompatible_table_is_rejected(deployment, invalid):
    module, cloudformation, dynamodb = deployment
    if invalid == "key_name":
        dynamodb.describe_table.return_value["Table"]["KeySchema"][0]["AttributeName"] = "game_id"
    elif invalid == "key_type":
        dynamodb.describe_table.return_value["Table"]["AttributeDefinitions"][0]["AttributeType"] = "N"
    elif invalid == "ttl_attribute":
        dynamodb.describe_time_to_live.return_value["TimeToLiveDescription"]["AttributeName"] = "wrong_attribute"
    else:
        dynamodb.describe_time_to_live.return_value["TimeToLiveDescription"]["TimeToLiveStatus"] = "DISABLED"
    with pytest.raises(ValueError, match="Cannot reuse"):
        module.resolve_table(cloudformation, dynamodb, STACK)


def test_diagnostics_report_validation_reason_for_latest_change_set(deployment, capsys):
    module, cloudformation, _ = deployment
    changes, events = Mock(), Mock()
    cloudformation.get_paginator.side_effect = {"list_change_sets": changes, "describe_events": events}.__getitem__
    changes.paginate.return_value = [{"Summaries": [{
        "ChangeSetId": "old", "ChangeSetName": "old", "CreationTime": datetime(2026, 10, 25, tzinfo=timezone.utc),
    }]}, {"Summaries": [{
        "ChangeSetId": "latest", "ChangeSetName": "latest", "CreationTime": datetime(2026, 10, 26, tzinfo=timezone.utc),
        "Parameters": [{"ParameterValue": "test-password"}],
    }]}]
    events.paginate.return_value = [{"OperationEvents": [{
        "LogicalResourceId": "ClosingOddsTable", "EventType": "VALIDATION_ERROR",
        "ValidationStatusReason": "Table already exists", "ValidationPath": "/Resources/ClosingOddsTable",
    }]}]
    module.report_failure(cloudformation, STACK)
    events.paginate.assert_called_once_with(ChangeSetName="latest", Filters={"FailedEvents": True})
    output = capsys.readouterr().out
    assert json.loads(output.splitlines()[-1])["reason"] == "Table already exists"
    assert "test-password" not in output


def test_main_exports_discovered_table_to_github_actions(deployment, monkeypatch, tmp_path):
    module, cloudformation, dynamodb = deployment
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.delenv("EXISTING_CLOSING_ODDS_TABLE_NAME", raising=False)
    monkeypatch.setattr("sys.argv", ["resolve_closing_table.py", "--stack-name", STACK, "--region", "us-east-1"])
    monkeypatch.setattr(module.boto3, "client", lambda service, **kwargs: cloudformation if service == "cloudformation" else dynamodb)
    module.main()
    assert output.read_text() == f"table_name={TABLE}\n"
