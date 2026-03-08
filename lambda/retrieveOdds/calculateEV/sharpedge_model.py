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

    def analyze_moneyline_market(self, odds_data, exchange_data=None):
        """Analyze moneyline market and return fair odds + EV opportunities."""
        return self.get_fair_odds_and_ev(odds_data, exchange_data)

    def analyze_spread_market(self, spreads_data, exchange_data=None):
        """
        Analyze point spread market.
        
        Parameters:
        - spreads_data (dict): {book_name: {"home_odds": 1.91, "home_point": -3.5, 
                                           "away_odds": 1.91, "away_point": 3.5}}
        """
        market_probs = []
        books_used = 0
        
        for book, spread_info in spreads_data.items():
            if book not in self.weights:
                continue
            
            try:
                # Extract odds for both sides of the spread
                home_odds = spread_info["home_odds"]
                away_odds = spread_info["away_odds"]
                
                # Devig the spread odds (two-way market)
                devigged = self.devig_multiplicative((home_odds, away_odds))
                
                market_probs.append({
                    'prob': devigged[0],  # Home team covering spread
                    'weight': self.weights[book]
                })
                books_used += 1
            except (ValueError, ZeroDivisionError):
                continue
        
        if not market_probs:
            raise ValueError("No valid spread odds data found")
        
        fair_prob = self.calculate_fair_probability(market_probs)
        fair_odds_decimal = 1 / fair_prob
        fair_odds_american = self.decimal_to_american(fair_odds_decimal)
        
        return {
            "fair_prob": fair_prob,
            "fair_odds_decimal": fair_odds_decimal,
            "fair_odds_american": fair_odds_american,
            "books_used": books_used,
            "exchanges_used": 0  # No exchange data for now
        }

    def analyze_totals_market(self, totals_data, exchange_data=None):
        """
        Analyze over/under totals market.
        
        Parameters:
        - totals_data (dict): {book_name: {"over_odds": 1.91, "under_odds": 1.91, "point": 45.5}}
        """
        market_probs = []
        books_used = 0
        
        for book, totals_info in totals_data.items():
            if book not in self.weights:
                continue
            
            try:
                # Extract odds for over/under
                over_odds = totals_info["over_odds"]
                under_odds = totals_info["under_odds"]
                
                # Devig the totals odds (two-way market)
                devigged = self.devig_multiplicative((over_odds, under_odds))
                
                market_probs.append({
                    'prob': devigged[0],  # Over probability
                    'weight': self.weights[book]
                })
                books_used += 1
            except (ValueError, ZeroDivisionError):
                continue
        
        if not market_probs:
            raise ValueError("No valid totals odds data found")
        
        fair_prob = self.calculate_fair_probability(market_probs)
        fair_odds_decimal = 1 / fair_prob
        fair_odds_american = self.decimal_to_american(fair_odds_decimal)
        
        return {
            "fair_prob": fair_prob,
            "fair_odds_decimal": fair_odds_decimal,
            "fair_odds_american": fair_odds_american,
            "books_used": books_used,
            "exchanges_used": 0
        }

    def get_fair_odds_and_ev(self, odds_data, exchange_data=None, offered_odds=None, game_info=None):
        """
        Enhanced method that returns comprehensive analysis results.
        """
        market_probs = []
        books_used = 0
        exchanges_used = 0
        book_contributions = {}  # Track each book's contribution
        
        # Process regular sportsbook odds (keep existing logic)
        for book, odds in odds_data.items():
            if book not in self.weights:
                continue
            
            try:
                devigged = self.devig_multiplicative(odds)
                weight = self.weights[book]
                
                market_probs.append({
                    'prob': devigged[0],
                    'weight': weight
                })
                
                # Track book contributions for transparency
                book_contributions[book] = {
                    'probability': devigged[0],
                    'weight': weight,
                    'original_odds': odds,
                    'devigged_odds': [1/devigged[0], 1/devigged[1]],
                    'book_type': self._classify_book_type(book)
                }
                books_used += 1
            except (ValueError, ZeroDivisionError):
                continue

        # Process exchanges (keep existing logic)
        if exchange_data:
            for exchange, data in exchange_data.items():
                if (exchange in self.exchange_weights and 
                    data.get("liquidity", 0) >= self.liquidity_threshold):
                    
                    try:
                        devigged = self.devig_multiplicative(data["odds"])
                        weight = self.exchange_weights[exchange]
                        
                        market_probs.append({
                            'prob': devigged[0],
                            'weight': weight
                        })
                        
                        book_contributions[exchange] = {
                            'probability': devigged[0],
                            'weight': weight,
                            'liquidity': data.get("liquidity", 0),
                            'original_odds': data["odds"],
                            'book_type': 'exchange'
                        }
                        exchanges_used += 1
                    except (ValueError, ZeroDivisionError):
                        continue

        if not market_probs:
            raise ValueError("No valid odds data found")
        
        # Calculate fair probability and total weights
        total_weight = sum(book['weight'] for book in market_probs)
        fair_prob = self.calculate_fair_probability(market_probs)
        fair_odds_decimal = 1 / fair_prob
        fair_odds_american = self.decimal_to_american(fair_odds_decimal)

        # Calculate comprehensive EV analysis
        ev_analysis = None
        if offered_odds:
            ev_analysis = self._calculate_comprehensive_ev(offered_odds, fair_prob, fair_odds_decimal)

        return {
            "fair_prob": fair_prob,
            "fair_odds_decimal": fair_odds_decimal,
            "fair_odds_american": fair_odds_american,
            "ev_analysis": ev_analysis,
            "books_used": books_used,
            "exchanges_used": exchanges_used,
            "book_contributions": book_contributions  # Return book contributions for transparency
        }

    def _classify_book_type(self, book_name):
        """
        Classify book type for analysis transparency.
        
        Parameters:
        - book_name (str): Name of the sportsbook
        
        Returns:
        - str: Book classification (sharp, recreational, hybrid)
        """
        sharp_books = ['Pinnacle', 'Circa', 'BetOnline', 'BookMaker']
        recreational_books = ['FanDuel', 'DraftKings', 'Caesars', 'BetMGM']
        
        if book_name in sharp_books:
            return 'sharp'
        elif book_name in recreational_books:
            return 'recreational'
        else:
            return 'hybrid'

    def _calculate_comprehensive_ev(self, offered_odds, fair_prob, fair_odds_decimal):
        """
        Calculate comprehensive EV analysis.
        
        Parameters:
        - offered_odds (float): Odds offered by the book
        - fair_prob (float): Fair probability from model
        - fair_odds_decimal (float): Fair decimal odds
        
        Returns:
        - dict: Comprehensive EV analysis
        """
        ev_percentage = self.calculate_ev(offered_odds, fair_prob)
        
        # Calculate edge metrics
        odds_edge = ((offered_odds / fair_odds_decimal) - 1) * 100
        prob_edge = fair_prob - (1 / offered_odds)
        
        # Classify EV quality
        if ev_percentage >= 3.0:
            ev_quality = 'excellent'
        elif ev_percentage >= 1.5:
            ev_quality = 'good'
        elif ev_percentage >= 0.5:
            ev_quality = 'marginal'
        else:
            ev_quality = 'poor'
        
        return {
            'ev_percentage': ev_percentage,
            'ev_quality': ev_quality,
            'odds_edge_percentage': odds_edge,
            'probability_edge': prob_edge,
            'offered_odds': offered_odds,
            'fair_odds': fair_odds_decimal,
            'implied_prob_offered': 1 / offered_odds,
            'fair_probability': fair_prob
        }
