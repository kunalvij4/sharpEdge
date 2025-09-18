import boto3
from botocore.exceptions import BotoCoreError, ClientError
from typing import Dict, Any
from decimal import Decimal
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Access the ODDS_API_KEY from the environment
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

if ODDS_API_KEY is None:
    raise ValueError("ODDS_API_KEY is not set in the .env file")

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

# Example usage
if __name__ == "__main__":
    # Initialize DynamoDB client
    region = "us-east-2"  # Replace with your AWS region
    table_name = "EV_Bets"
    dynamo_client = DynamoDBClient(region_name=region, table_name=table_name)

    # Example data to store
    example_data = {
        "id": "example_id_123",
        "game_id": "basketball_nba_Lakers_vs_Celtics",
        "sport": "basketball_nba",
        "home_team": "Lakers",
        "away_team": "Celtics",
        "commence_time": "2023-10-01T20:00:00Z",
        "markets": {
            "moneyline": {
                "FanDuel": {"home_odds": 1.9, "away_odds": 2.1}
            },
            "spreads": {
                "DraftKings": {"home_odds": 1.8, "home_point": -3.5, "away_odds": 2.0, "away_point": 3.5}
            },
            "totals": {
                "Caesars": {"over_odds": 1.95, "under_odds": 1.85, "point": 220.5}
            }
        }
    }

    # Store the data in DynamoDB
    success = dynamo_client.store_data(example_data)
    if success:
        print("Data stored successfully in DynamoDB.")
    else:
        print("Failed to store data in DynamoDB.")

    # Example usage
    print(f"Your ODDS_API_KEY is: {ODDS_API_KEY}")