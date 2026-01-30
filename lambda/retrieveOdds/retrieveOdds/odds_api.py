import requests
from typing import Dict, List, Optional


class OddsAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.the-odds-api.com/v4"
        self.session = requests.Session()

    def get_odds(
        self,
        sport: str,
        markets: str = "h2h",
        bookmakers: Optional[str] = None,
        odds_format: str = "decimal",
    ) -> List[Dict]:
        url = f"{self.base_url}/sports/{sport}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": markets,
            "oddsFormat": odds_format,
        }
        if bookmakers:
            params["bookmakers"] = bookmakers

        response = self.session.get(url, params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def parse_all_markets_odds(self, raw_odds: List[Dict]) -> Dict[str, Dict]:
        """
        Parse raw API response for ALL markets (moneyline, spreads, totals)
        into DynamoDB-safe JSON (no tuples).
        """
        parsed_games: Dict[str, Dict] = {}

        book_mapping = {
            "FanDuel": "FanDuel",
            "DraftKings": "DraftKings",
            "Caesars Sportsbook": "Caesars",
            "BetMGM": "BetMGM",
            "PointsBet": "PointsBet",
            "WynnBET": "WynnBET",
            "Bovada": "Bovada",
            "BetOnline.ag": "BetOnline",
            "MyBookie.ag": "MyBookie",
        }

        for game in raw_odds:
            base_game_id = f"{game['sport_title']}_{game['home_team']}_vs_{game['away_team']}"
            game_time = game["commence_time"]

            if base_game_id not in parsed_games:
                parsed_games[base_game_id] = {
                    "sport": game["sport_title"],
                    "home_team": game["home_team"],
                    "away_team": game["away_team"],
                    "commence_time": game_time,
                    "markets": {
                        "moneyline": {"odds_data": {}},
                        "spreads": {"odds_data": {}},
                        "totals": {"odds_data": {}},
                    },
                }

            for bookmaker in game.get("bookmakers", []):
                book_name = bookmaker.get("title", "UnknownBook")
                mapped_name = book_mapping.get(book_name, book_name)

                for market in bookmaker.get("markets", []):
                    market_key = market.get("key")
                    outcomes = market.get("outcomes", [])

                    # Moneyline
                    if market_key == "h2h" and len(outcomes) == 2:
                        home_odds = next(
                            o["price"] for o in outcomes if o["name"] == game["home_team"]
                        )
                        away_odds = next(
                            o["price"] for o in outcomes if o["name"] == game["away_team"]
                        )
                        parsed_games[base_game_id]["markets"]["moneyline"]["odds_data"][mapped_name] = {
                            "home_odds": home_odds,
                            "away_odds": away_odds,
                        }

                    # Spreads
                    elif market_key == "spreads" and len(outcomes) == 2:
                        home_outcome = next(o for o in outcomes if o["name"] == game["home_team"])
                        away_outcome = next(o for o in outcomes if o["name"] == game["away_team"])
                        parsed_games[base_game_id]["markets"]["spreads"]["odds_data"][mapped_name] = {
                            "home_odds": home_outcome["price"],
                            "home_point": home_outcome.get("point"),
                            "away_odds": away_outcome["price"],
                            "away_point": away_outcome.get("point"),
                        }

                    # Totals
                    elif market_key == "totals" and len(outcomes) == 2:
                        over_outcome = next(o for o in outcomes if o["name"] == "Over")
                        under_outcome = next(o for o in outcomes if o["name"] == "Under")
                        parsed_games[base_game_id]["markets"]["totals"]["odds_data"][mapped_name] = {
                            "over_odds": over_outcome["price"],
                            "under_odds": under_outcome["price"],
                            "point": over_outcome.get("point"),
                        }

        return parsed_games

    def get_nfl_all_markets(self) -> Dict[str, Dict]:
        raw = self.get_odds("americanfootball_nfl", markets="h2h,spreads,totals")
        return self.parse_all_markets_odds(raw)

    def get_nba_all_markets(self) -> Dict[str, Dict]:
        raw = self.get_odds("basketball_nba", markets="h2h,spreads,totals")
        return self.parse_all_markets_odds(raw)
