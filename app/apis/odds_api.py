import requests
from typing import Dict, List, Optional
from datetime import datetime

class OddsAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.the-odds-api.com/v4"
        self.session = requests.Session()
    
    def get_sports(self) -> List[Dict]:
        """Get list of available sports."""
        url = f"{self.base_url}/sports"
        params = {"apiKey": self.api_key}
        
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()
    
    def get_odds(self, sport: str, markets: str = "h2h", 
                 bookmakers: str = None, odds_format: str = "decimal") -> List[Dict]:
        """
        Get odds for a specific sport.
        
        Parameters:
        - sport: Sport key (e.g., 'americanfootball_nfl', 'basketball_nba')
        - markets: Type of bet ('h2h' for moneyline, 'spreads', 'totals', or comma-separated)
        - bookmakers: Comma-separated bookmaker keys
        - odds_format: 'decimal' or 'american'
        """
        url = f"{self.base_url}/sports/{sport}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": markets,
            "oddsFormat": odds_format
        }
        
        if bookmakers:
            params["bookmakers"] = bookmakers
        
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()
    
    def parse_moneyline_odds(self, raw_odds: List[Dict]) -> Dict[str, Dict]:
        """
        Parse raw API response into SharpEdge format for MONEYLINE ONLY.
        
        Returns:
        Dict with game_id as keys, containing odds data for each book
        """
        parsed_games = {}
        
        for game in raw_odds:
            game_id = f"{game['sport_title']}_{game['home_team']}_vs_{game['away_team']}_ML"
            game_time = game['commence_time']
            
            # Initialize game data
            if game_id not in parsed_games:
                parsed_games[game_id] = {
                    "sport": game['sport_title'],
                    "home_team": game['home_team'],
                    "away_team": game['away_team'],
                    "commence_time": game_time,
                    "odds_data": {},
                    "market_type": "moneyline"
                }
            
            # Parse bookmaker odds
            for bookmaker in game['bookmakers']:
                book_name = bookmaker['title']
                
                # Map API bookmaker names to your weight system names
                book_mapping = {
                    "FanDuel": "FanDuel",
                    "DraftKings": "DraftKings", 
                    "Caesars Sportsbook": "Caesars",
                    "BetMGM": "BetMGM",
                    "PointsBet": "PointsBet",
                    "WynnBET": "WynnBET",
                    "Bovada": "Bovada",
                    "BetOnline.ag": "BetOnline",
                    "MyBookie.ag": "MyBookie"
                }
                
                mapped_name = book_mapping.get(book_name, book_name)
                
                if 'markets' in bookmaker:
                    for market in bookmaker['markets']:
                        if market['key'] == 'h2h':  # moneyline
                            outcomes = market['outcomes']
                            if len(outcomes) == 2:
                                # Find home and away odds
                                home_odds = next(o['price'] for o in outcomes if o['name'] == game['home_team'])
                                away_odds = next(o['price'] for o in outcomes if o['name'] == game['away_team'])
                                
                                # Store as (home_odds, away_odds) to match your format
                                parsed_games[game_id]["odds_data"][mapped_name] = (home_odds, away_odds)
        
        return parsed_games
    
    def parse_all_markets_odds(self, raw_odds: List[Dict]) -> Dict[str, Dict]:
        """
        Parse raw API response for ALL markets (moneyline, spreads, totals).
        
        Returns:
        Dict with game_id as keys, containing all market data for each book
        """
        parsed_games = {}
        
        for game in raw_odds:
            base_game_id = f"{game['sport_title']}_{game['home_team']}_vs_{game['away_team']}"
            game_time = game['commence_time']
            
            # Initialize base game data if not exists
            if base_game_id not in parsed_games:
                parsed_games[base_game_id] = {
                    "sport": game['sport_title'],
                    "home_team": game['home_team'],
                    "away_team": game['away_team'],
                    "commence_time": game_time,
                    "markets": {
                        "moneyline": {"odds_data": {}},
                        "spreads": {"odds_data": {}},
                        "totals": {"odds_data": {}}
                    }
                }
            
            # Parse bookmaker odds for all markets
            for bookmaker in game['bookmakers']:
                book_name = bookmaker['title']
                
                # Map API bookmaker names to your weight system names
                book_mapping = {
                    "FanDuel": "FanDuel",
                    "DraftKings": "DraftKings", 
                    "Caesars Sportsbook": "Caesars",
                    "BetMGM": "BetMGM",
                    "PointsBet": "PointsBet",
                    "WynnBET": "WynnBET",
                    "Bovada": "Bovada",
                    "BetOnline.ag": "BetOnline",
                    "MyBookie.ag": "MyBookie"
                }
                
                mapped_name = book_mapping.get(book_name, book_name)
                
                if 'markets' in bookmaker:
                    for market in bookmaker['markets']:
                        market_key = market['key']
                        outcomes = market['outcomes']
                        
                        if market_key == 'h2h' and len(outcomes) == 2:
                            # Moneyline: (home_odds, away_odds)
                            home_odds = next(o['price'] for o in outcomes if o['name'] == game['home_team'])
                            away_odds = next(o['price'] for o in outcomes if o['name'] == game['away_team'])
                            parsed_games[base_game_id]["markets"]["moneyline"]["odds_data"][mapped_name] = (home_odds, away_odds)
                        
                        elif market_key == 'spreads' and len(outcomes) == 2:
                            # Spreads: (home_odds, home_point, away_odds, away_point)
                            home_outcome = next(o for o in outcomes if o['name'] == game['home_team'])
                            away_outcome = next(o for o in outcomes if o['name'] == game['away_team'])
                            
                            parsed_games[base_game_id]["markets"]["spreads"]["odds_data"][mapped_name] = {
                                "home_odds": home_outcome['price'],
                                "home_point": home_outcome['point'],
                                "away_odds": away_outcome['price'],
                                "away_point": away_outcome['point']
                            }
                        
                        elif market_key == 'totals' and len(outcomes) == 2:
                            # Totals: (over_odds, under_odds, point)
                            over_outcome = next(o for o in outcomes if o['name'] == 'Over')
                            under_outcome = next(o for o in outcomes if o['name'] == 'Under')
                            
                            parsed_games[base_game_id]["markets"]["totals"]["odds_data"][mapped_name] = {
                                "over_odds": over_outcome['price'],
                                "under_odds": under_outcome['price'],
                                "point": over_outcome['point']
                            }
        
        return parsed_games
    
    def get_nfl_games(self) -> Dict[str, Dict]:
        """Get current NFL games with moneyline odds (BACKWARD COMPATIBILITY)."""
        raw_odds = self.get_odds("americanfootball_nfl", markets="h2h")
        return self.parse_moneyline_odds(raw_odds)
    
    def get_nba_games(self) -> Dict[str, Dict]:
        """Get current NBA games with moneyline odds (BACKWARD COMPATIBILITY)."""
        raw_odds = self.get_odds("basketball_nba", markets="h2h")
        return self.parse_moneyline_odds(raw_odds)
    
    def get_nfl_all_markets(self) -> Dict[str, Dict]:
        """Get current NFL games with ALL markets (moneyline, spreads, totals)."""
        raw_odds = self.get_odds("americanfootball_nfl", markets="h2h,spreads,totals")
        return self.parse_all_markets_odds(raw_odds)
    
    def get_nba_all_markets(self) -> Dict[str, Dict]:
        """Get current NBA games with ALL markets (moneyline, spreads, totals)."""
        raw_odds = self.get_odds("basketball_nba", markets="h2h,spreads,totals")
        return self.parse_all_markets_odds(raw_odds)
