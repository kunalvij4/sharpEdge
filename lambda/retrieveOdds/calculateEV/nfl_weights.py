class NFLWeightingEngine:
    """NFL-specific weighting with smart fallback strategy"""
    
    def __init__(self):
        # PRIMARY (SHARP) WEIGHTS
        self.nfl_weights_primary = {
            'moneyline': {
                "Pinnacle": 0.33,
                "Circa": 0.28, 
                "BetOnline": 0.19,
                "DraftKings": 0.09,
                "FanDuel": 0.05,
                "BetRivers": 0.04,
                "Bovada": 0.02,
            },
            'spreads': {
                "Pinnacle": 0.35,      # Reduced slightly
                "Circa": 0.30,         # Reduced slightly  
                "BetOnline": 0.20,     # Increased
                "BookMaker": 0.08,     # Reduced
                "DraftKings": 0.04,    # Add DK to primary with small weight
                "FanDuel": 0.03,       # Add FD to primary with small weight
            },
            'totals': {
                "Pinnacle": 0.43,
                "Circa": 0.24,
                "BetOnline": 0.19,
                "DraftKings": 0.10,
                "BetRivers": 0.04
            }
        }
        
        # FALLBACK WEIGHTS - Include previously excluded books with lower weights
        self.nfl_weights_fallback = {
            'moneyline': {
                "Pinnacle": 0.25,      # Reduced but still highest
                "Circa": 0.22,
                "BetOnline": 0.15,
                "DraftKings": 0.08,
                "FanDuel": 0.05,
                "BetRivers": 0.04,
                "Bovada": 0.03,
                # ADD FALLBACK BOOKS
                "BetMGM": 0.06,        # Soft but high volume
                "Caesars": 0.05,       # Slow but sometimes decent
                "BetUS": 0.04,         # Backup option
                "MyBookie": 0.03,      # Last resort
            },
            'spreads': {
                "Pinnacle": 0.30,
                "Circa": 0.25,
                "BetOnline": 0.12,
                "BookMaker": 0.08,
                # ADD FALLBACK BOOKS
                "DraftKings": 0.08,    # Include DK for spreads in fallback
                "BetMGM": 0.07,
                "FanDuel": 0.05,
                "BetRivers": 0.03,
                "Caesars": 0.02,
            },
            'totals': {
                "Pinnacle": 0.32,
                "Circa": 0.18,
                "BetOnline": 0.15,
                "DraftKings": 0.10,
                "BetRivers": 0.05,
                # ADD FALLBACK BOOKS  
                "FanDuel": 0.08,       # Include FD for totals in fallback
                "BetMGM": 0.06,
                "Bovada": 0.04,
                "Caesars": 0.02,
            }
        }
        
        # Minimum books required before fallback
        self.min_books_required = {
            'moneyline': 3,
            'spreads': 2, 
            'totals': 2
        }

        self.avoid_books = ['WynnBET', 'LowVig.ag']  
        
        
        self.never_use_books = ['WynnBET', 'LowVig.ag']
        
        self.liquidity_requirements = {
            'moneyline': 50000,
            'spreads': 100000,
            'totals': 30000
        }
    
    def get_available_books(self, market_type, available_book_names):
        """Get list of books that are actually available in the API response"""
        primary_weights = self.nfl_weights_primary[market_type]
        fallback_weights = self.nfl_weights_fallback[market_type]
        
        # Normalize book names
        normalized_available = []
        for book in available_book_names:
            normalized_available.append(self.normalize_book_name(book))
        
        # Check which primary books are available
        available_primary = {}
        for book, weight in primary_weights.items():
            if book in normalized_available:
                available_primary[book] = weight
        
        # Check which fallback books are available  
        available_fallback = {}
        for book, weight in fallback_weights.items():
            if book in normalized_available and book not in self.never_use_books:
                available_fallback[book] = weight
        
        return available_primary, available_fallback
    
    def get_nfl_weights(self, market_type, available_book_names=None):
        """Get optimized weights with smart fallback strategy"""
        
        # If no available books specified, return primary weights
        if available_book_names is None:
            return self.nfl_weights_primary.get(market_type, self.nfl_weights_primary['moneyline'])
        
        # Get available books
        available_primary, available_fallback = self.get_available_books(market_type, available_book_names)
        
        min_required = self.min_books_required[market_type]
        
        # Strategy 1: Use primary weights if we have enough books
        if len(available_primary) >= min_required:
            print(f"  💎 Using PRIMARY weights for {market_type} ({len(available_primary)} sharp books available)")
            
            # Normalize primary weights to sum to 1.0
            total_weight = sum(available_primary.values())
            return {book: weight/total_weight for book, weight in available_primary.items()}
        
        # Strategy 2: Use fallback weights (includes more books)
        elif len(available_fallback) >= min_required:
            print(f"  ⚠️ Using FALLBACK weights for {market_type} ({len(available_primary)} sharp + {len(available_fallback)-len(available_primary)} backup books)")
            
            # Normalize fallback weights to sum to 1.0
            total_weight = sum(available_fallback.values())
            return {book: weight/total_weight for book, weight in available_fallback.items()}
        
        # Strategy 3: Emergency mode - use whatever books are available
        else:
            print(f"   EMERGENCY MODE for {market_type}: Using all available books with equal weights")
            emergency_books = [book for book in available_book_names 
                             if self.normalize_book_name(book) not in self.never_use_books]
            
            if emergency_books:
                equal_weight = 1.0 / len(emergency_books)
                return {self.normalize_book_name(book): equal_weight for book in emergency_books}
            else:
                print(f"   No usable books available for {market_type}")
                return {}
    
    def should_include_book(self, book_name, market_type, available_book_names=None):
        """Determine if book should be included with fallback logic"""
        if book_name in self.never_use_books:
            return False
        
        # If no fallback logic needed, use primary weights
        if available_book_names is None:
            weights = self.nfl_weights_primary.get(market_type, {})
            return book_name in weights and weights[book_name] > 0
        
        # Use the dynamic weighting system
        weights = self.get_nfl_weights(market_type, available_book_names)
        return book_name in weights and weights[book_name] > 0
    
    def normalize_book_name(self, api_book_name):
        """Normalize API book names to match our weights"""
        mapping = {
            "BetOnline.ag": "BetOnline",
            "MyBookie.ag": "MyBookie",
            "Caesars Sportsbook": "Caesars",
            "BetMGM Sportsbook": "BetMGM",
            # Add more as needed
        }
        return mapping.get(api_book_name, api_book_name)
