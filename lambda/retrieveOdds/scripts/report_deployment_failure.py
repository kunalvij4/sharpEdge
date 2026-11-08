"""Report CloudFormation deployment failures without printing stack parameters."""

import argparse
import json
import os

import boto3


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
    args = parser.parse_args()
    cloudformation = boto3.client("cloudformation", region_name=args.region)
    report_failure(cloudformation, args.stack_name)


if __name__ == "__main__":
    main()
