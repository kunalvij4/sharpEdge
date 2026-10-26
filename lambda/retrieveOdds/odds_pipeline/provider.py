"""In-house Odds API access and event-ID-based parsing of game markets."""

import requests


BOOK_NAMES = {
    "Caesars Sportsbook": "Caesars", "BetOnline.ag": "BetOnline", "MyBookie.ag": "MyBookie",
    "Novig": "NoVig", "Prophet Exchange": "ProphetX",
}


class OddsAPI:
    sport_keys = {
        "basketball_nba": "nba_basketball",
        "americanfootball_nfl": "nfl_football",
        "icehockey_nhl": "nhl_hockey",
        "baseball_mlb": "mlb_baseball",
        "americanfootball_ncaaf": "ncaaf_football",
    }

    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = f"{base_url.rstrip('/')}/v1"
        self.session = requests.Session()

    def get_odds(self, sport, markets="h2h", bookmakers=None, odds_format="decimal"):
        sport = self.sport_keys.get(sport, sport)
        return self._get(f"/sports/{sport}/odds", markets, bookmakers, odds_format)

    def get_events(self, sport):
        sport = self.sport_keys.get(sport, sport)
        return self._get(f"/sports/{sport}/events")

    def get_event_odds(self, sport, event_id, markets, bookmakers=None, odds_format="decimal"):
        return self._get(f"/events/{event_id}/odds", markets, bookmakers, odds_format, fresh_only=True)

    def _get(self, path, markets=None, bookmakers=None, odds_format="decimal", fresh_only=False):
        params = {}
        if markets is not None:
            params.update({"markets": markets, "oddsFormat": odds_format})
        if bookmakers:
            params["bookmakers"] = bookmakers
        if fresh_only:
            params["freshOnly"] = "true"
        response = self.session.get(
            f"{self.base_url}{path}", params=params,
            headers={"X-API-Key": self.api_key}, timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def parse_all_markets_odds(self, raw_odds):
        games = {}
        for raw in raw_odds:
            event_id = raw["id"]
            game = games.setdefault(event_id, {
                "event_id": event_id, "sport": raw["sport_title"],
                "home_team": raw["home_team"], "away_team": raw["away_team"],
                "commence_time": raw["commence_time"],
                "markets": {category: {"odds_data": {}} for category in ("moneyline", "spreads", "totals")},
            })
            for bookmaker in raw.get("bookmakers", []):
                title = bookmaker.get("title")
                if not title:
                    continue
                book = BOOK_NAMES.get(title, title)
                for market in bookmaker.get("markets", []):
                    kind = market.get("key")
                    if kind not in {"h2h", "spreads", "totals"}:
                        continue
                    outcomes = {outcome.get("name"): outcome for outcome in market.get("outcomes", [])}
                    category = "moneyline" if kind == "h2h" else kind
                    prices = {}
                    if kind in {"h2h", "spreads"}:
                        # A three-way market with a draw is not a two-way bet.
                        if set(outcomes) - {game["home_team"], game["away_team"]}:
                            continue
                        for side in ("home", "away"):
                            outcome = outcomes.get(game[f"{side}_team"])
                            if outcome is not None:
                                prices[f"{side}_odds"] = outcome.get("price")
                                if kind == "spreads":
                                    prices[f"{side}_point"] = outcome.get("point")
                    else:
                        for side in ("over", "under"):
                            outcome = outcomes.get(side.title())
                            if outcome is not None:
                                prices[f"{side}_odds"] = outcome.get("price")
                                prices[f"{side}_point"] = outcome.get("point")
                    if prices:
                        game["markets"][category]["odds_data"][book] = prices
        return games
