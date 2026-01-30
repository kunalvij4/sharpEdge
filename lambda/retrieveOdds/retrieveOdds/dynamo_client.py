import boto3
from botocore.exceptions import BotoCoreError, ClientError
from typing import Any, Dict
from decimal import Decimal


class DynamoDBClient:
    def __init__(self, table_name: str, region_name: str | None = None):
        # region_name can be omitted in Lambda; AWS sets it automatically
        self.dynamodb = boto3.resource("dynamodb", region_name=region_name) if region_name else boto3.resource("dynamodb")
        self.table = self.dynamodb.Table(table_name)

    def store_item(self, item: Dict[str, Any]) -> None:
        try:
            item = self._convert_floats_to_decimal(item)
            self.table.put_item(Item=item)
        except (BotoCoreError, ClientError) as e:
            print(f"Error storing data in DynamoDB: {e}")
            raise

    def _convert_floats_to_decimal(self, data: Any) -> Any:
        if isinstance(data, float):
            return Decimal(str(data))
        if isinstance(data, dict):
            return {k: self._convert_floats_to_decimal(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._convert_floats_to_decimal(i) for i in data]
        return data
