import statistics
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

class PlayerPropsModel:
    def __init__(self, main_line_weights: Dict[str, float] = None, min_books: int = 3):
        """
        Initialize Player Props Model with specialized prop weighting.
        
        Parameters:
        - main_line_weights: Your existing weights (for reference/fallback)
        - min_books: Minimum number of books required for analysis
        """
        self.main_line_weights = main_line_weights or {}
        self.min_books = min_books
        
        # SPECIALIZED PLAYER PROP WEIGHTS
        # Based on prop market sharpness and liquidity
        self.prop_weights = {
            # Top tier - Sharp on props OR high recreational volume
            "FanDuel": 0.28,        # Huge recreational volume, softer prop lines
            "Circa": 0.22,          # Sharp across all markets including props
            
            # Second tier - Moderate prop sharpness
            "Pinnacle": 0.12,       # Sharp but lower prop liquidity
            "Caesars": 0.12,        # Good prop volume, moderate sharpness
            "PropBuilder": 0.10,    # Prop-focused book (if available)
            
            # Third tier - Less reliable on props
            "DraftKings": 0.08,     # Large volume but can be slower to adjust props
            "BetMGM": 0.06,         # Growing but still developing prop markets
            "BetOnline": 0.02,      # Sharp on main lines, less prop focus
            
            # Books with minimal prop weight
            "BookMaker": 0.00,      # Primarily main line focused
            "WynnBET": 0.00,        # Limited prop offerings
        }
        
        # Player prop market types and their characteristics
        self.prop_types = {
            "passing_yards": {"type": "over_under", "unit": "yards", "variance": "medium"},
            "passing_touchdowns": {"type": "over_under", "unit": "touchdowns", "variance": "high"},
            "rushing_yards": {"type": "over_under", "unit": "yards", "variance": "high"},
            "rushing_touchdowns": {"type": "over_under", "unit": "touchdowns", "variance": "high"},
            "receiving_yards": {"type": "over_under", "unit": "yards", "variance": "high"},
            "receiving_touchdowns": {"type": "over_under", "unit": "touchdowns", "variance": "very_high"},
            "receptions": {"type": "over_under", "unit": "receptions", "variance": "medium"},
            "points": {"type": "over_under", "unit": "points", "variance": "high"},
            "rebounds": {"type": "over_under", "unit": "rebounds", "variance": "medium"},
            "assists": {"type": "over_under", "unit": "assists", "variance": "medium"},
            "first_touchdown": {"type": "yes_no", "unit": "boolean", "variance": "very_high"},
            "anytime_touchdown": {"type": "yes_no", "unit": "boolean", "variance": "high"}
        }
    
    def get_effective_weights(self) -> Dict[str, float]:
        """Return the prop-specific weights (for transparency/debugging)."""
        return self.prop_weights.copy()
    
    def decimal_to_american(self, decimal_odds: float) -> str:
        """Convert decimal odds to American format."""
        if decimal_odds < 1.0:
            raise ValueError("Decimal odds must be 1.0 or greater")
        
        if decimal_odds >= 2.0:
            american_odds = int((decimal_odds - 1) * 100)
            return f"+{american_odds}"
        else:
            american_odds = int(-100 / (decimal_odds - 1))
            return str(american_odds)
    
    def devig_multiplicative(self, odds: Tuple[float, float]) -> List[float]:
        """Remove vig from two-way market using multiplicative method."""
        if len(odds) != 2:
            raise ValueError("Must provide exactly 2 odds for two-way market")
        
        # Convert to implied probabilities
        implied_probs = [1 / odd for odd in odds]
        
        # Calculate overround and normalize
        overround = sum(implied_probs)
        devigged_probs = [prob / overround for prob in implied_probs]
        
        return devigged_probs
    
    def calculate_consensus_line(self, prop_data: Dict[str, Dict]) -> float:
        """
        Calculate the consensus line value across all books, weighted by prop expertise.
        
        Parameters:
        - prop_data: {book_name: {"over_odds": 1.91, "under_odds": 1.91, "line": 250.5}}
        
        Returns:
        - float: Consensus line value
        """
        weighted_lines = []
        total_weight = 0
        
        for book_name, data in prop_data.items():
            if book_name in self.prop_weights and "line" in data and self.prop_weights[book_name] > 0:
                weight = self.prop_weights[book_name]
                weighted_lines.append(data["line"] * weight)
                total_weight += weight
        
        if not weighted_lines or total_weight == 0:
            # Fallback to simple median if no weighted books
            lines = [data["line"] for data in prop_data.values() if "line" in data]
            if lines:
                return statistics.median(lines)
            raise ValueError("No valid lines found for consensus calculation")
        
        return sum(weighted_lines) / total_weight
    
    def analyze_over_under_prop(self, prop_data: Dict[str, Dict], player_name: str, 
                               prop_type: str) -> Dict:
        """
        Analyze an over/under player prop market using specialized prop weights.
        
        Parameters:
        - prop_data: {book_name: {"over_odds": 1.91, "under_odds": 1.91, "line": 250.5}}
        - player_name: Name of the player
        - prop_type: Type of prop (e.g., "passing_yards", "points")
        
        Returns:
        - Dict with fair odds analysis
        """
        if len(prop_data) < self.min_books:
            raise ValueError(f"Need at least {self.min_books} books for analysis")
        
        market_probs = []
        books_used = 0
        total_weight_used = 0
        consensus_line = self.calculate_consensus_line(prop_data)
        
        # Calculate fair probability for "over" using PROP-SPECIFIC weights
        for book_name, data in prop_data.items():
            if book_name not in self.prop_weights or self.prop_weights[book_name] == 0:
                continue
            
            try:
                over_odds = data["over_odds"]
                under_odds = data["under_odds"]
                
                # Devig the odds
                devigged = self.devig_multiplicative((over_odds, under_odds))
                
                prop_weight = self.prop_weights[book_name]
                market_probs.append({
                    'prob': devigged[0],  # Over probability
                    'weight': prop_weight
                })
                books_used += 1
                total_weight_used += prop_weight
            except (ValueError, ZeroDivisionError, KeyError):
                continue
        
        if not market_probs:
            raise ValueError("No valid prop odds found from weighted books")
        
        # Calculate weighted fair probability
        total_weight = sum(book['weight'] for book in market_probs)
        weighted_prob_sum = sum(book['prob'] * book['weight'] for book in market_probs)
        fair_over_prob = weighted_prob_sum / total_weight
        
        fair_over_odds = 1 / fair_over_prob
        fair_under_odds = 1 / (1 - fair_over_prob)
        
        return {
            "player": player_name,
            "prop_type": prop_type,
            "consensus_line": consensus_line,
            "fair_over_prob": fair_over_prob,
            "fair_under_prob": 1 - fair_over_prob,
            "fair_over_odds_decimal": fair_over_odds,
            "fair_under_odds_decimal": fair_under_odds,
            "fair_over_odds_american": self.decimal_to_american(fair_over_odds),
            "fair_under_odds_american": self.decimal_to_american(fair_under_odds),
            "books_used": books_used,
            "total_weight_used": total_weight_used,
            "prop_characteristics": self.prop_types.get(prop_type, {"variance": "unknown"}),
            "weighting_scheme": "prop_specialized"  # Flag to show this used prop weights
        }
    
    def analyze_yes_no_prop(self, prop_data: Dict[str, Dict], player_name: str, 
                           prop_type: str) -> Dict:
        """
        Analyze a yes/no player prop market using specialized prop weights.
        """
        if len(prop_data) < self.min_books:
            raise ValueError(f"Need at least {self.min_books} books for analysis")
        
        market_probs = []
        books_used = 0
        total_weight_used = 0
        
        for book_name, data in prop_data.items():
            if book_name not in self.prop_weights or self.prop_weights[book_name] == 0:
                continue
            
            try:
                yes_odds = data["yes_odds"]
                no_odds = data["no_odds"]
                
                # Devig the odds
                devigged = self.devig_multiplicative((yes_odds, no_odds))
                
                prop_weight = self.prop_weights[book_name]
                market_probs.append({
                    'prob': devigged[0],  # Yes probability
                    'weight': prop_weight
                })
                books_used += 1
                total_weight_used += prop_weight
            except (ValueError, ZeroDivisionError, KeyError):
                continue
        
        if not market_probs:
            raise ValueError("No valid prop odds found from weighted books")
        
        # Calculate weighted fair probability
        total_weight = sum(book['weight'] for book in market_probs)
        weighted_prob_sum = sum(book['prob'] * book['weight'] for book in market_probs)
        fair_yes_prob = weighted_prob_sum / total_weight
        
        fair_yes_odds = 1 / fair_yes_prob
        fair_no_odds = 1 / (1 - fair_yes_prob)
        
        return {
            "player": player_name,
            "prop_type": prop_type,
            "fair_yes_prob": fair_yes_prob,
            "fair_no_prob": 1 - fair_yes_prob,
            "fair_yes_odds_decimal": fair_yes_odds,
            "fair_no_odds_decimal": fair_no_odds,
            "fair_yes_odds_american": self.decimal_to_american(fair_yes_odds),
            "fair_no_odds_american": self.decimal_to_american(fair_no_odds),
            "books_used": books_used,
            "total_weight_used": total_weight_used,
            "prop_characteristics": self.prop_types.get(prop_type, {"variance": "unknown"}),
            "weighting_scheme": "prop_specialized"
        }
    
    def calculate_ev(self, offered_odds: float, fair_prob: float) -> float:
        """Calculate Expected Value for a player prop bet."""
        if offered_odds <= 1.0:
            raise ValueError("Offered odds must be greater than 1.0")
        
        if not (0.0 < fair_prob < 1.0):
            raise ValueError("Fair probability must be between 0.0 and 1.0")
        
        payout = offered_odds - 1
        ev_decimal = (fair_prob * payout) - (1 - fair_prob)
        ev_percentage = ev_decimal * 100
        
        return ev_percentage
    
    def find_prop_ev_opportunities(self, analysis: Dict, prop_data: Dict[str, Dict], 
                                  min_ev: float = 0.5) -> List[Dict]:
        """
        Find +EV opportunities for a specific prop across all books.
        Enhanced to show which books we're betting against vs. using for fair value.
        """
        opportunities = []
        
        if analysis["prop_type"] in ["first_touchdown", "anytime_touchdown"] or "yes_odds" in next(iter(prop_data.values()), {}):
            # Yes/No prop
            for book_name, data in prop_data.items():
                # Check if this book has meaningful weight in our model
                book_weight = self.prop_weights.get(book_name, 0)
                book_tier = "Sharp" if book_weight >= 0.15 else "Recreational" if book_weight > 0 else "Unweighted"
                
                # Check YES bet
                ev_yes = self.calculate_ev(data["yes_odds"], analysis["fair_yes_prob"])
                if ev_yes >= min_ev:
                    opportunities.append({
                        "player": analysis["player"],
                        "prop_type": analysis["prop_type"],
                        "bet_type": "YES",
                        "book_name": book_name,
                        "book_tier": book_tier,
                        "book_weight": book_weight,
                        "offered_odds": data["yes_odds"],
                        "fair_odds": analysis["fair_yes_odds_decimal"],
                        "fair_prob": analysis["fair_yes_prob"],
                        "ev_percentage": ev_yes,
                        "variance_level": analysis["prop_characteristics"]["variance"]
                    })
                
                # Check NO bet
                ev_no = self.calculate_ev(data["no_odds"], analysis["fair_no_prob"])
                if ev_no >= min_ev:
                    opportunities.append({
                        "player": analysis["player"],
                        "prop_type": analysis["prop_type"],
                        "bet_type": "NO",
                        "book_name": book_name,
                        "book_tier": book_tier,
                        "book_weight": book_weight,
                        "offered_odds": data["no_odds"],
                        "fair_odds": analysis["fair_no_odds_decimal"],
                        "fair_prob": analysis["fair_no_prob"],
                        "ev_percentage": ev_no,
                        "variance_level": analysis["prop_characteristics"]["variance"]
                    })
        
        else:
            # Over/Under prop
            for book_name, data in prop_data.items():
                book_weight = self.prop_weights.get(book_name, 0)
                book_tier = "Sharp" if book_weight >= 0.15 else "Recreational" if book_weight > 0 else "Unweighted"
                
                # Check OVER bet
                ev_over = self.calculate_ev(data["over_odds"], analysis["fair_over_prob"])
                if ev_over >= min_ev:
                    opportunities.append({
                        "player": analysis["player"],
                        "prop_type": analysis["prop_type"],
                        "bet_type": "OVER",
                        "line": analysis["consensus_line"],
                        "book_name": book_name,
                        "book_tier": book_tier,
                        "book_weight": book_weight,
                        "offered_odds": data["over_odds"],
                        "fair_odds": analysis["fair_over_odds_decimal"],
                        "fair_prob": analysis["fair_over_prob"],
                        "ev_percentage": ev_over,
                        "variance_level": analysis["prop_characteristics"]["variance"]
                    })
                
                # Check UNDER bet
                ev_under = self.calculate_ev(data["under_odds"], analysis["fair_under_prob"])
                if ev_under >= min_ev:
                    opportunities.append({
                        "player": analysis["player"],
                        "prop_type": analysis["prop_type"],
                        "bet_type": "UNDER", 
                        "line": analysis["consensus_line"],
                        "book_name": book_name,
                        "book_tier": book_tier,
                        "book_weight": book_weight,
                        "offered_odds": data["under_odds"],
                        "fair_odds": analysis["fair_under_odds_decimal"],
                        "fair_prob": analysis["fair_under_prob"],
                        "ev_percentage": ev_under,
                        "variance_level": analysis["prop_characteristics"]["variance"]
                    })
        
        # Sort by EV percentage (highest first)
        opportunities.sort(key=lambda x: x['ev_percentage'], reverse=True)
        return opportunities
