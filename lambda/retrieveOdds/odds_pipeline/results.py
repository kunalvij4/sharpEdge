"""Publish derived results to S3, then mirror those snapshots to Redis."""

import json
import logging
import os

import boto3

from .cache import cache_snapshot
from .markets import CATEGORIES


logger = logging.getLogger(__name__)


class ResultsPublisher:
    def __init__(self, bucket=None, s3=None):
        self.bucket = bucket or os.environ["RESULTS_BUCKET"]
        self.s3 = s3 if s3 is not None else boto3.client("s3")

    def publish(self, league, ev, arbitrage, retrieved_at, include_props=True):
        failures = []
        for table, prefix, suffix, results in (
            ("EV", "ev", "ev", ev), ("arbitrage", "arbitrage", "arb", arbitrage),
        ):
            for category in CATEGORIES:
                if category == "props" and not include_props:
                    continue
                rows = results[category]
                key = f"{prefix}/{league}/{category}_{suffix}.json"
                if any(not isinstance(row.get("event_id"), str) or not row["event_id"] or row.get("sport") != league for row in rows):
                    logger.warning("Invalid result identity for %s", key)
                    failures.append(key)
                    continue
                try:
                    self.s3.put_object(
                        Bucket=self.bucket, Key=key,
                        Body=json.dumps(rows, separators=(",", ":"), allow_nan=False).encode(),
                        ContentType="application/json", CacheControl="max-age=60",
                        Metadata={"retrieved-at": retrieved_at},
                    )
                except Exception as error:
                    logger.warning("S3 result write failed for %s (%s)", key, type(error).__name__)
                    failures.append(key)
                if not cache_snapshot(table, league, category, rows, retrieved_at=retrieved_at):
                    failures.append(f"Redis:{table}/{league}/{category}")
        return failures
