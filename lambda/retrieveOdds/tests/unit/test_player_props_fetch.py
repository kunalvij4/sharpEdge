import unittest
from unittest.mock import Mock

from retrieveOdds.odds_api import OddsAPI
from retrieveOdds.player_props import fetch_and_attach_player_props


class PlayerPropsFetchTests(unittest.TestCase):
    def test_all_leagues_preserve_multiple_lines_and_prices(self):
        markets = {"NBA": "player_points", "NFL": "player_pass_yds", "NHL": "player_shots_on_goal", "MLB": "pitcher_strikeouts", "NCAAF": "player_rush_yds"}
        for league, market in markets.items():
            with self.subTest(league=league):
                api = Mock()
                api.get_event_odds.return_value = {"bookmakers": [{"title": "FanDuel", "markets": [{"key": market, "outcomes": [
                    {"description": "Player", "name": side, "point": line, "price": price}
                    for line in (5.5, 6.5) for side, price in (("Over", 1.9), ("Under", 2.0))
                ]}]}]}
                result = fetch_and_attach_player_props(api, {"game": {"event_id": "event"}})
                api.get_event_odds.assert_called_once_with("event", "all_props")
                lines = result["game"]["markets"]["props"][market]["Player"]
                self.assertEqual(set(lines), {"5.5", "6.5"})
                self.assertEqual(lines["5.5"]["FanDuel"], {"over_odds": 1.9, "under_odds": 2.0})

    def test_props_only_events_are_included_for_every_league(self):
        for league, key in OddsAPI.league_keys.items():
            with self.subTest(league=league):
                api = OddsAPI("test-key", "https://odds.example.com")
                event = {"id": "event", "sport_title": league, "home_team": "Home", "away_team": "Away", "commence_time": "2026-10-26T20:00:00Z"}
                response = Mock()
                response.json.return_value = [event]
                api.session.get = Mock(return_value=response)
                api.get_odds = Mock(return_value=[])
                games = api.get_games_with_props_events(key)
                self.assertEqual(next(iter(games.values()))["event_id"], "event")
                api.session.get.assert_called_once_with(
                    f"https://odds.example.com/v1/sports/{api.sport_keys[key]}/events",
                    headers={"X-API-Key": "test-key"}, timeout=20,
                )
                api.get_odds.assert_called_once_with(key)
