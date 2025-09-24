import os
import boto3
from boto3.dynamodb.conditions import Key, Attr
from decimal import Decimal
from dotenv import load_dotenv
from datetime import datetime
from typing import Dict, List, Optional

load_dotenv()

class SharpEdgeDB:
    def __init__(self):
        # AWS Configuration
        self.aws_region = os.getenv('AWS_REGION', 'us-east-2')
        self.ev_bets_table_name = "EV_Bets"
        
        # Use default credentials from environment/profile
        self.dynamodb = boto3.resource(
            'dynamodb',
            region_name=self.aws_region
        )
        
        # Get table reference
        self.ev_bets_table = self.dynamodb.Table(self.ev_bets_table_name)
    
    def _convert_floats_to_decimal(self, obj):
        """Convert all float values to Decimal for DynamoDB compatibility."""
        if isinstance(obj, float):
            return Decimal(str(obj))
        elif isinstance(obj, dict):
            return {k: self._convert_floats_to_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_floats_to_decimal(i) for i in obj]
        return obj
    
    def save_ev_bet(self, market_id: str, book_name: str, offered_odds: float, 
                    fair_odds: float, fair_prob: float, ev_percentage: float,
                    sport: str, market_type: str, **kwargs):
        """Save a +EV betting opportunity to DynamoDB."""
        
        item = {
            'id': f"{market_id}_{book_name}_{int(datetime.now().timestamp())}",  # Use 'id' as primary key
            'market_id': market_id,
            'book_name': book_name,
            'offered_odds': Decimal(str(offered_odds)),
            'fair_odds': Decimal(str(fair_odds)),
            'fair_prob': Decimal(str(fair_prob)),
            'ev_percentage': Decimal(str(ev_percentage)),
            'sport': sport,
            'market_type': market_type,
            'timestamp': datetime.now().isoformat(),
            'date_created': datetime.now().strftime('%Y-%m-%d'),
            **self._convert_floats_to_decimal(kwargs)
        }
        
        try:
            response = self.ev_bets_table.put_item(Item=item)
            print(f"✅ Saved +EV bet: {book_name} {float(ev_percentage):.2f}% EV to DynamoDB")
            return response
        except Exception as e:
            print(f"❌ Error saving EV bet to DynamoDB: {e}")
            return None
    
    def get_positive_ev_bets(self, min_ev: float = 1.0, limit: int = 50) -> List[Dict]:
        """Get recent positive EV bets from DynamoDB."""
        
        try:
            response = self.ev_bets_table.scan(
                FilterExpression=Attr('ev_percentage').gte(Decimal(str(min_ev))),
                Limit=limit
            )
            
            items = response.get('Items', [])
            
            # Convert Decimal back to float for display
            for item in items:
                for key, value in item.items():
                    if isinstance(value, Decimal):
                        item[key] = float(value)
            
            # Sort by EV percentage descending
            items.sort(key=lambda x: float(x.get('ev_percentage', 0)), reverse=True)
            return items
            
        except Exception as e:
            print(f"❌ Error querying EV bets from DynamoDB: {e}")
            return []
    
    def test_connection(self) -> Dict:
        """Test AWS DynamoDB connection and return table info."""
        
        try:
            # Test the single table
            try:
                response = self.ev_bets_table.describe_table()
                table_info = {
                    'status': response['Table']['TableStatus'],
                    'item_count': response['Table']['ItemCount']
                }
            except Exception as e:
                table_info = {'status': 'ERROR', 'error': str(e)}
            
            return {
                'connection': 'SUCCESS',
                'region': self.aws_region,
                'tables': {self.ev_bets_table_name: table_info}
            }
            
        except Exception as e:
            return {'connection': 'FAILURE', 'error': str(e)}