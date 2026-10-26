import importlib
import unittest
from unittest.mock import Mock


class PlayerPropsFetchTests(unittest.TestCase):
    def test_all_leagues_preserve_multiple_lines_and_prices(self):
        collect = importlib.import_module("odds_pipeline.collect")
        leagues = importlib.import_module("odds_pipeline.leagues")
        markets = {"NBA": "player_points", "NFL": "player_pass_yds", "NHL": "player_shots_on_goal", "MLB": "pitcher_strikeouts", "NCAAF": "player_rush_yds"}
        for league, market in markets.items():
            with self.subTest(league=league):
                api = Mock()
                api.get_event_odds.return_value = {"bookmakers": [{"title": "FanDuel", "markets": [{"key": market, "outcomes": [
                    {"description": "Player", "name": side, "point": line, "price": price}
                    for line in (5.5, 6.5) for side, price in (("Over", 1.9), ("Under", 2.0))
                ]}]}]}
                sport_key = leagues.LEAGUE_SPORT_KEYS[league]
                result = collect.fetch_and_attach_player_props(api, sport_key, {"game": {"event_id": "event"}})
                api.get_event_odds.assert_called_once_with(sport_key, "event", markets="all_props")
                lines = result["game"]["markets"]["props"][market]["Player"]
                self.assertEqual(set(lines), {"5.5", "6.5"})
                self.assertEqual(lines["5.5"]["FanDuel"], {"over_odds": 1.9, "under_odds": 2.0})

    def test_props_only_events_are_included_for_every_league(self):
        OddsAPI = importlib.import_module("odds_pipeline.provider").OddsAPI
        leagues = importlib.import_module("odds_pipeline.leagues")
        for league, key in leagues.LEAGUE_SPORT_KEYS.items():
            with self.subTest(league=league):
                api = OddsAPI("test-key", "https://odds.example.com")
                event = {"id": "event", "sport_title": league, "home_team": "Home", "away_team": "Away", "commence_time": "2026-10-26T20:00:00Z"}
                response = Mock()
                response.json.return_value = [event]
                api.session.get = Mock(return_value=response)
                games = api.parse_all_markets_odds(api.get_events(key))
                self.assertEqual(next(iter(games.values()))["event_id"], "event")
                api.session.get.assert_called_once_with(
                    f"https://odds.example.com/v1/sports/{api.sport_keys[key]}/events",
                    params={},
                    headers={"X-API-Key": "test-key"}, timeout=20,
                )

    def test_all_props_keeps_new_market_keys_and_excludes_cached_prices(self):
        collect = importlib.import_module("odds_pipeline.collect")
        api = Mock()
        api.get_event_odds.return_value = {"bookmakers": [{"title": "Novig", "markets": [{
            "key": "player_points_q1", "outcomes": [
                {"description": "Player", "name": "Over", "point": 5.5, "price": 2.2},
                {"description": "Player", "name": "Under", "point": 5.5, "price": 1.9},
                {"description": "Cached", "name": "Over", "point": 6.5, "price": 2.2, "actionable": False},
                {"description": "Stale", "name": "Under", "point": 7.5, "price": 2.2, "freshness": {"status": "stale"}},
            ],
        }]}]}
        result = collect.fetch_and_attach_player_props(api, "basketball_nba", {"event": {"event_id": "event"}})
        players = result["event"]["markets"]["props"]["player_points_q1"]
        self.assertEqual(set(players), {"Player"})
        self.assertEqual(players["Player"]["5.5"]["NoVig"], {"over_odds": 2.2, "under_odds": 1.9})
