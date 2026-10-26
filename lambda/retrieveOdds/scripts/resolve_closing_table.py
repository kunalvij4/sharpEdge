"""Find a closing-odds table before SAM deploys, without changing AWS resources."""

import argparse
import json
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


def resolve_table(cloudformation, dynamodb, stack_name, requested_table=""):
    try:
        stack = cloudformation.describe_stacks(StackName=stack_name)["Stacks"][0]
    except ClientError as error:
        if error.response["Error"]["Code"] != "ValidationError" or "does not exist" not in error.response["Error"]["Message"]:
            raise
        stack = None

    if stack:
        pages = cloudformation.get_paginator("list_stack_resources").paginate(StackName=stack_name)
        for page in pages:
            for resource in page["StackResourceSummaries"]:
                if resource["LogicalResourceId"] == "ClosingOddsTable" and resource["ResourceStatus"] not in (
                    "DELETE_COMPLETE", "DELETE_SKIPPED",
                ):
                    if requested_table and requested_table != resource["PhysicalResourceId"]:
                        raise ValueError("ClosingOddsTable is already managed by the stack; unset EXISTING_CLOSING_ODDS_TABLE_NAME.")
                    return ""

    previous_table = next((
        parameter["ParameterValue"] for parameter in (stack or {}).get("Parameters", [])
        if parameter["ParameterKey"] == "ExistingClosingOddsTableName"
    ), "")
    table_name = requested_table or previous_table or f"{stack_name}-ClosingOdds"
    try:
        table = dynamodb.describe_table(TableName=table_name)["Table"]
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        if requested_table or previous_table:
            raise ValueError(f"Configured closing-odds table {table_name} does not exist.") from error
        return ""

    keys = {key["KeyType"]: key["AttributeName"] for key in table["KeySchema"]}
    attributes = {attribute["AttributeName"]: attribute["AttributeType"] for attribute in table["AttributeDefinitions"]}
    if keys != {"HASH": "event_id", "RANGE": "bet_key"} or any(
        attributes.get(key) != "S" for key in ("event_id", "bet_key")
    ):
        raise ValueError(f"Cannot reuse {table_name}: expected string event_id/bet_key keys.")
    ttl = dynamodb.describe_time_to_live(TableName=table_name)["TimeToLiveDescription"]
    if ttl.get("AttributeName") != "expires_at" or ttl["TimeToLiveStatus"] not in ("ENABLED", "ENABLING"):
        raise ValueError(f"Cannot reuse {table_name}: TTL must be enabled on expires_at.")
    return table_name


def report_failure(cloudformation, stack_name):
    changes = [
        change for page in cloudformation.get_paginator("list_change_sets").paginate(StackName=stack_name)
        for change in page["Summaries"]
    ]
    if not changes:
        print("No change set is available for deployment diagnostics.")
        return
    latest = max(changes, key=lambda change: change["CreationTime"])
    print(f"CloudFormation failure details for {latest['ChangeSetName']}:")
    pages = cloudformation.get_paginator("describe_events").paginate(
        ChangeSetName=latest["ChangeSetId"], Filters={"FailedEvents": True},
    )
    for page in pages:
        for event in page["OperationEvents"]:
            print(json.dumps({
                "resource": event.get("LogicalResourceId"),
                "type": event.get("EventType"),
                "reason": event.get("ValidationStatusReason") or event.get("ResourceStatusReason") or event.get("HookStatusReason"),
                "path": event.get("ValidationPath"),
            }))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-name", required=True)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION"))
    parser.add_argument("--report-failure", action="store_true")
    args = parser.parse_args()
    cloudformation = boto3.client("cloudformation", region_name=args.region)
    if args.report_failure:
        report_failure(cloudformation, args.stack_name)
        return
    table_name = resolve_table(
        cloudformation, boto3.client("dynamodb", region_name=args.region), args.stack_name,
        os.environ.get("EXISTING_CLOSING_ODDS_TABLE_NAME", "").strip(),
    )
    print(f"Closing-odds table: {table_name or 'managed by CloudFormation'}")
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write(f"table_name={table_name}\n")


if __name__ == "__main__":
    main()
