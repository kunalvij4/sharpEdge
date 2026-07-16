import boto3
from botocore.exceptions import BotoCoreError, ClientError
from typing import Dict, Any
from decimal import Decimal
import os

class DynamoDBClient:
    def __init__(self, region_name: str, table_name: str):
        self.dynamodb = boto3.resource('dynamodb', region_name=region_name)
        self.table = self.dynamodb.Table(table_name)

    def store_data(self, data: Dict[str, Any]) -> bool:
        """
        Store data in the DynamoDB table.

        Parameters:
        - data: A dictionary containing the data to store.

        Returns:
        - True if the operation is successful, False otherwise.
        """
        try:
            # Convert floats to Decimal
            data = self._convert_floats_to_decimal(data)
            self.table.put_item(Item=data)
            return True
        except (BotoCoreError, ClientError) as e:
            print(f"Error storing data in DynamoDB: {e}")
            return False

    def _convert_floats_to_decimal(self, data: Any) -> Any:
        """
        Recursively convert all float values in a dictionary to Decimal.

        Parameters:
        - data: The data to convert.

        Returns:
        - The data with floats converted to Decimal.
        """
        if isinstance(data, float):
            return Decimal(str(data))
        elif isinstance(data, dict):
            return {k: self._convert_floats_to_decimal(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._convert_floats_to_decimal(i) for i in data]
        return data

