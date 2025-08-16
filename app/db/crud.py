from datetime import datetime
from typing import List, Dict, Any, Optional
from .connection import DatabaseConnection

class SharpEdgeDB:
    def __init__(self, db_path="data/sharpedge.db"):
        self.db = DatabaseConnection(db_path)
    
    def save_odds_data(self, market_id: str, odds_data: Dict[str, tuple], 
                       sport: str = None, market_type: str = "moneyline", 
                       team_home: str = None, team_away: str = None):
        """
        Save raw odds data from multiple sportsbooks.
        
        Parameters:
        - market_id (str): Unique identifier for the market
        - odds_data (dict): Dictionary of {book_name: (odds_for, odds_against)}
        - sport (str): Sport name (e.g., "NFL", "NBA")
        - market_type (str): Type of bet ("moneyline", "spread", "total")
        """
        with self.db.get_connection() as conn:
            for book_name, (odds_for, odds_against) in odds_data.items():
                conn.execute("""
                    INSERT INTO odds_data 
                    (market_id, book_name, odds_for, odds_against, sport, market_type, team_home, team_away)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (market_id, book_name, odds_for, odds_against, sport, market_type, team_home, team_away))
            conn.commit()
    
    def save_fair_odds(self, market_id: str, fair_prob: float, fair_odds_decimal: float,
                       fair_odds_american: str, books_used: int, exchanges_used: int,
                       sport: str = None, market_type: str = "moneyline"):
        """Save calculated fair odds."""
        with self.db.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO fair_odds 
                (market_id, fair_prob, fair_odds_decimal, fair_odds_american, 
                 books_used, exchanges_used, sport, market_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (market_id, fair_prob, fair_odds_decimal, fair_odds_american,
                  books_used, exchanges_used, sport, market_type))
            conn.commit()
    
    def save_ev_bet(self, market_id: str, book_name: str, offered_odds: float,
                    fair_odds: float, fair_prob: float, ev_percentage: float,
                    sport: str = None, market_type: str = "moneyline"):
        """Save an EV betting opportunity."""
        is_positive_ev = ev_percentage > 0
        
        with self.db.get_connection() as conn:
            conn.execute("""
                INSERT INTO ev_bets 
                (market_id, book_name, offered_odds, fair_odds, fair_prob, ev_percentage,
                 sport, market_type, is_positive_ev)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (market_id, book_name, offered_odds, fair_odds, fair_prob, ev_percentage,
                  sport, market_type, is_positive_ev))
            conn.commit()
    
    def get_positive_ev_bets(self, min_ev: float = 0.0, limit: int = 50) -> List[Dict]:
        """Retrieve positive EV bets."""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM ev_bets 
                WHERE ev_percentage >= ? AND is_positive_ev = 1
                ORDER BY ev_percentage DESC, timestamp DESC
                LIMIT ?
            """, (min_ev, limit))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_recent_fair_odds(self, hours: int = 24) -> List[Dict]:
        """Get recent fair odds calculations."""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM fair_odds 
                WHERE timestamp >= datetime('now', '-{} hours')
                ORDER BY timestamp DESC
            """.format(hours))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_market_history(self, market_id: str) -> Dict[str, List[Dict]]:
        """Get complete history for a specific market."""
        with self.db.get_connection() as conn:
            # Get odds data
            odds_cursor = conn.execute("""
                SELECT * FROM odds_data 
                WHERE market_id = ?
                ORDER BY timestamp DESC
            """, (market_id,))
            
            # Get EV opportunities
            ev_cursor = conn.execute("""
                SELECT * FROM ev_bets 
                WHERE market_id = ?
                ORDER BY ev_percentage DESC
            """, (market_id,))
            
            return {
                "odds_data": [dict(row) for row in odds_cursor.fetchall()],
                "ev_opportunities": [dict(row) for row in ev_cursor.fetchall()]
            }
    
    def get_best_ev_by_sport(self, sport: str, min_ev: float = 2.0, limit: int = 10) -> List[Dict]:
        """Get best EV opportunities for a specific sport."""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM ev_bets 
                WHERE sport = ? AND ev_percentage >= ? AND is_positive_ev = 1
                ORDER BY ev_percentage DESC
                LIMIT ?
            """, (sport, min_ev, limit))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def cleanup_old_data(self, days_old: int = 30):
        """Remove old data to keep database size manageable."""
        with self.db.get_connection() as conn:
            conn.execute("""
                DELETE FROM odds_data 
                WHERE timestamp < datetime('now', '-{} days')
            """.format(days_old))
            
            conn.execute("""
                DELETE FROM ev_bets 
                WHERE timestamp < datetime('now', '-{} days')
            """.format(days_old))
            
            conn.commit()
            
            # Return count of remaining records
            cursor = conn.execute("SELECT COUNT(*) FROM odds_data")
            odds_count = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COUNT(*) FROM ev_bets")
            ev_count = cursor.fetchone()[0]
            
            return {"odds_records": odds_count, "ev_records": ev_count}