"""Keep one last-known pre-start price per event, bookmaker, and bet."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import os

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.config import Config
from botocore.exceptions import ClientError

from .markets import bet_key, iter_quotes


WEEK_SECONDS = 7 * 24 * 60 * 60
WINDOW_SECONDS = 10 * 60


def utc_time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone")
    return result.astimezone(timezone.utc)


def within_window(commence_time, observed_at):
    seconds = (utc_time(commence_time) - utc_time(observed_at)).total_seconds()
    return 0 < seconds <= WINDOW_SECONDS


class ClosingOddsStore:
    def __init__(self, table_name=None, client=None):
        self.table_name = table_name or os.environ["CLOSING_ODDS_TABLE"]
        # A low-level client can be shared by worker threads; resource/Table
        # instances are avoided here because resources are not thread-safe.
        self.client = client if client is not None else boto3.client(
            "dynamodb",
            config=Config(connect_timeout=2, read_timeout=5, retries={"mode": "standard", "total_max_attempts": 3}),
        )

    def store_event(self, league, game, observed_at):
        observed_at = utc_time(observed_at)
        if not within_window(game["commence_time"], observed_at):
            return 0
        timestamp = observed_at.isoformat(timespec="microseconds")
        serializer = TypeSerializer()
        items = []
        for quote in iter_quotes(league, game):
            item = {
                **quote, "bet_key": bet_key(quote), "observed_at": timestamp,
                "expires_at": int(observed_at.timestamp()) + WEEK_SECONDS,
            }
            # Serialize on the calling thread before sharing only the client.
            items.append({
                key: serializer.serialize(Decimal(str(value)) if isinstance(value, float) else value)
                for key, value in item.items()
            })

        def put(item):
            try:
                self.client.put_item(
                    TableName=self.table_name, Item=item,
                    ConditionExpression="attribute_not_exists(#observed) OR #observed < :observed",
                    ExpressionAttributeNames={"#observed": "observed_at"},
                    ExpressionAttributeValues={":observed": {"S": timestamp}},
                )
            except ClientError as error:
                if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    return 0
                raise
            return 1

        with ThreadPoolExecutor(max_workers=8) as executor:
            return sum(executor.map(put, items))

    def get_event(self, event_id, now=None):
        """Query an event directly; hide expired rows while TTL deletion catches up."""
        now = utc_time(now or datetime.now(timezone.utc))
        arguments = {
            "TableName": self.table_name,
            "KeyConditionExpression": "#event = :event",
            "FilterExpression": "#expires > :now",
            "ExpressionAttributeNames": {"#event": "event_id", "#expires": "expires_at"},
            "ExpressionAttributeValues": {":event": {"S": event_id}, ":now": {"N": str(int(now.timestamp()))}},
            "ConsistentRead": True,
        }
        deserializer = TypeDeserializer()
        rows = []
        while True:
            response = self.client.query(**arguments)
            for item in response["Items"]:
                row = {key: deserializer.deserialize(value) for key, value in item.items()}
                rows.append({
                    key: (int(value) if value == value.to_integral_value() else float(value)) if isinstance(value, Decimal) else value
                    for key, value in row.items()
                })
            if not response.get("LastEvaluatedKey"):
                return rows
            arguments["ExclusiveStartKey"] = response["LastEvaluatedKey"]
