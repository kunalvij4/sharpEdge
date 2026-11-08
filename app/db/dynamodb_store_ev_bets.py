"""Compatibility adapter for the retired DynamoDB writer. Nothing is stored."""

from typing import Any, Dict


class DynamoDBClient:
    def __init__(self, region_name: str, table_name: str):
        """Accept legacy configuration without connecting to AWS."""

    def store_data(self, data: Dict[str, Any]) -> bool:
        """Report that the data was not stored."""
        return False
