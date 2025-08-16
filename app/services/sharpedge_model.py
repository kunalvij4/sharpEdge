class SharpEdge:
    def __init__(self, weights, exchange_weights, liquidity_threshold=1000):
        self.weights = weights
        self.exchange_weights = exchange_weights
        self.liquidity_threshold = liquidity_threshold

    def decimal_to_american(self, decimal_odds):
        """
        Converts decimal odds to American format.
        
        Parameters:
        - decimal_odds (float): Decimal odds (e.g., 1.91, 2.50)
        
        Returns:
        - str: American odds format (e.g., "-110", "+150")
        """
        if decimal_odds < 1.0:
            raise ValueError("Decimal odds must be 1.0 or greater")
        
        if decimal_odds >= 2.0:
            # Positive American odds (underdog)
            american_odds = int((decimal_odds - 1) * 100)
            return f"+{american_odds}"
        else:
            # Negative American odds (favorite)
            american_odds = int(-100 / (decimal_odds - 1))
            return str(american_odds)

    def devig_multiplicative(self, odds): 
        """
        Devigs a two-way market using the multiplicative model.
        
        Parameters:
        - odds (tuple): A tuple of decimal odds (odds_for, odds_against)
        
        Returns:
        - list: [prob_for, prob_against] - devigged probabilities that sum to 1.0
        """
        if len(odds) != 2:
            raise ValueError("Multiplicative devig requires exactly 2 odds (for a two-way market)")
        
        # Convert decimal odds to implied probabilities
        implied_probs = [1 / odd for odd in odds]
        
        # Calculate the overround (total implied probability > 1.0 due to vig)
        overround = sum(implied_probs)
        
        # Remove vig by normalizing probabilities to sum to 1.0
        devigged_probs = [prob / overround for prob in implied_probs]
        
        return devigged_probs

    def calculate_fair_probability(self, market_probs):
        """
        Calculates the weighted fair probability from multiple sportsbooks.
        
        Parameters:
        - market_probs (list): List of dictionaries, each containing:
                              {'prob': float, 'weight': float}
                              Example: [{'prob': 0.52, 'weight': 0.30}, ...]
        
        Returns:
        - float: Weighted fair probability
        """
        if not market_probs:
            raise ValueError("market_probs cannot be empty")
        
        # Calculate total weight
        total_weight = sum(book['weight'] for book in market_probs)
        
        if total_weight == 0:
            raise ValueError("Total weight cannot be zero")
        
        # Calculate weighted average probability
        weighted_prob_sum = sum(book['prob'] * book['weight'] for book in market_probs)
        fair_prob = weighted_prob_sum / total_weight
        
        return fair_prob

    def calculate_ev(self, offered_odds, fair_prob):
        """
        Calculates the Expected Value (EV) of a bet as a percentage.
        
        Parameters:
        - offered_odds (float): Decimal odds being offered by a sportsbook
        - fair_prob (float): Fair probability from your weighted model (0.0 to 1.0)
        
        Returns:
        - float: Expected Value as a percentage (e.g., 2.62 for 2.62%)
        
        Formula: EV = (P * payout) - (1 - P)
        where payout = odds - 1
        """
        if offered_odds <= 1.0:
            raise ValueError("Offered odds must be greater than 1.0")
        
        if not (0.0 < fair_prob < 1.0):
            raise ValueError("Fair probability must be between 0.0 and 1.0")
        
        # Calculate net payout if bet wins (odds - 1)
        payout = offered_odds - 1
        
        # EV = (probability of winning * net profit) - (probability of losing * stake)
        # Since stake = 1, this simplifies to: (fair_prob * payout) - (1 - fair_prob)
        ev_decimal = (fair_prob * payout) - (1 - fair_prob)
        
        # Convert to percentage
        ev_percentage = ev_decimal * 100
        
        return ev_percentage

    def get_fair_odds_and_ev(self, odds_data, exchange_data=None, offered_odds=None):
        """
        Main method that processes all odds data and calculates fair odds + EV.
        
        Parameters:
        - odds_data (dict): Regular sportsbook odds
                           Format: {"Pinnacle": (1.91, 1.91), "Circa": (1.92, 1.90), ...}
        - exchange_data (dict, optional): Exchange odds with liquidity
                                         Format: {"ProphetX": {"odds": (1.93, 1.93), "liquidity": 1200}, ...}
        - offered_odds (float, optional): Specific odds to calculate EV against
        
        Returns:
        - dict: {
            "fair_prob": float,
            "fair_odds_decimal": float,
            "fair_odds_american": str,
            "ev_percentage": float (or None if no offered_odds provided),
            "books_used": int,
            "exchanges_used": int
        }
        """
        market_probs = []
        books_used = 0
        exchanges_used = 0

        # Process regular sportsbook odds
        for book, odds in odds_data.items():
            if book not in self.weights:
                continue
            
            try:
                devigged = self.devig_multiplicative(odds)
                market_probs.append({
                    'prob': devigged[0],  # Probability for the "for" side
                    'weight': self.weights[book]
                })
                books_used += 1
            except (ValueError, ZeroDivisionError):
                # Skip invalid odds
                continue

        # Process exchange data conditionally (based on liquidity)
        if exchange_data:
            for exchange, data in exchange_data.items():
                if (exchange in self.exchange_weights and 
                    data.get("liquidity", 0) >= self.liquidity_threshold):
                    
                    try:
                        devigged = self.devig_multiplicative(data["odds"])
                        market_probs.append({
                            'prob': devigged[0],
                            'weight': self.exchange_weights[exchange]
                        })
                        exchanges_used += 1
                    except (ValueError, ZeroDivisionError):
                        continue

        # Calculate fair probability and odds
        if not market_probs:
            raise ValueError("No valid odds data found to calculate fair probability")
        
        fair_prob = self.calculate_fair_probability(market_probs)
        fair_odds_decimal = 1 / fair_prob
        fair_odds_american = self.decimal_to_american(fair_odds_decimal)

        # Calculate EV if offered odds provided
        ev_percentage = None
        if offered_odds:
            ev_percentage = self.calculate_ev(offered_odds, fair_prob)

        return {
            "fair_prob": fair_prob,
            "fair_odds_decimal": fair_odds_decimal,
            "fair_odds_american": fair_odds_american,
            "ev_percentage": ev_percentage,
            "books_used": books_used,
            "exchanges_used": exchanges_used
        }