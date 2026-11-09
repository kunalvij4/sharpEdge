"""Invoke the deployed pipeline once and report its publication/link summary."""

import argparse
import json

import boto3
from botocore.config import Config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack-name", required=True)
    args = parser.parse_args()
    function = boto3.client("cloudformation").describe_stack_resource(
        StackName=args.stack_name, LogicalResourceId="RetrieveOddsFunction",
    )["StackResourceDetail"]["PhysicalResourceId"]
    response = boto3.client("lambda", config=Config(read_timeout=360, retries={"max_attempts": 0})).invoke(
        FunctionName=function, InvocationType="RequestResponse", Payload=b'{"deployment_verification":true}',
    )
    summary = json.load(response["Payload"])
    if response.get("FunctionError"):
        raise RuntimeError("Deployed pipeline invocation failed")
    print(json.dumps(summary, sort_keys=True))
    if summary.get("status") != "complete" or not summary.get("events_fetched"):
        raise RuntimeError("Deployed pipeline did not complete a populated slate")
    if summary.get("ev_bets_found", 0) and not sum(summary.get("bet_links", {}).get(key, 0) for key in ("provided", "event")):
        raise RuntimeError("Published EV slate contains no supplied sportsbook links")


if __name__ == "__main__":
    main()
