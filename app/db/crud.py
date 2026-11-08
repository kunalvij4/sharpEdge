"""Compatibility API for callers of the retired DynamoDB bet store.

Bet persistence is disabled. These methods never create an AWS client or make
network calls, including when old AWS settings are still present.
"""

from typing import Dict, List


class SharpEdgeDB:
    def save_ev_bet(self, market_id: str, book_name: str, offered_odds: float,
                    fair_odds: float, fair_prob: float, ev_percentage: float,
                    sport: str, market_type: str, **kwargs):
        """Skip persistence; return no storage response."""
        return None

    def get_positive_ev_bets(self, min_ev: float = 1.0, limit: int = 50) -> List[Dict]:
        """Historical bet storage is no longer available."""
        return []

    def test_connection(self) -> Dict:
        return {"connection": "DISABLED", "tables": {}}
