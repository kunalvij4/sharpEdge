import os
import unittest
from unittest.mock import patch

from calculateEV.odds_store import load_market, load_sport


class OddsStoreTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, TABLE_NAME="history")
        env.start()
        self.addCleanup(env.stop)
        db = patch("calculateEV.odds_store.DynamoDBClient")
        self.db = db.start()
        self.addCleanup(db.stop)

    @patch.dict(os.environ, ODDS_API_KEY="test-key", ODDS_API_BASE_URL="https://odds.example.com")
    @patch("calculateEV.odds_store.fetch_and_attach_player_props")
    @patch("calculateEV.odds_store.OddsAPI")
    def test_nba_fetches_fresh_moneylines_and_props(self, api_class, attach_props):
        api = api_class.return_value
        games = {"game": {"markets": {"moneyline": {"odds_data": {}}, "props": {"player_points": {}}}}}
        api.get_games_with_props_events.return_value = games
        attach_props.return_value = games
        result = load_sport("NBA")
        api_class.assert_called_once_with(api_key="test-key", base_url="https://odds.example.com")
        api.get_games_with_props_events.assert_called_once_with("basketball_nba")
        attach_props.assert_called_once_with(api, games)
        self.assertEqual(load_market("NBA", "moneyline", result)["games"]["game"]["data"], {"odds_data": {}})
        self.assertEqual(load_market("NBA", "props", result)["games"]["game"]["data"], {"player_points": {}})
        api.get_games_with_props_events.assert_called_once()
        self.db.assert_called_once_with(table_name="history")
        saved = self.db.return_value.store_item.call_args.args[0]
        self.assertEqual(saved["game_id"], "game")
        self.assertEqual(saved["league"], "NBA")
        self.assertEqual(saved["markets"], games["game"]["markets"])
        self.assertIn("+00:00", saved["retrieved_at"])

    @patch.dict(os.environ, ODDS_API_KEY="test-key", ODDS_API_BASE_URL="https://odds.example.com")
    @patch("calculateEV.odds_store.fetch_and_attach_player_props")
    @patch("calculateEV.odds_store.OddsAPI")
    def test_all_leagues_fetch_props_and_record_history(self, api_class, attach_props):
        from calculateEV.odds_store import SPORT_KEYS
        for league, key in SPORT_KEYS.items():
            with self.subTest(league=league):
                api_class.reset_mock()
                attach_props.reset_mock()
                games = {"game": {"markets": {"props": {"test_stat": {}}}}}
                api_class.return_value.get_games_with_props_events.return_value = games
                attach_props.return_value = games
                self.assertEqual(load_sport(league), games)
                api_class.return_value.get_games_with_props_events.assert_called_once_with(key)
                attach_props.assert_called_once_with(api_class.return_value, games)
                self.assertEqual(self.db.return_value.store_item.call_args.args[0]["league"], league)

    @patch.dict(os.environ, ODDS_API_KEY="test-key", ODDS_API_BASE_URL="https://odds.example.com")
    @patch("calculateEV.odds_store.OddsAPI")
    def test_api_failure_propagates_without_using_stale_odds(self, api_class):
        api_class.return_value.get_games_with_props_events.side_effect = RuntimeError("API unavailable")
        with self.assertRaisesRegex(RuntimeError, "API unavailable"):
            load_sport("NBA")

    @patch.dict(os.environ, ODDS_API_KEY="test-key", ODDS_API_BASE_URL="https://odds.example.com")
    @patch("calculateEV.odds_store.OddsAPI")
    def test_each_fetch_preserves_lines_and_prices_as_a_new_snapshot(self, api_class):
        api_class.return_value.get_games_with_props_events.return_value = {
            "game": {"markets": {"totals": {"odds_data": {"book": {"point": 8.5, "over_odds": 1.9}}}}}
        }
        load_sport("MLB")
        load_sport("MLB")
        snapshots = [call.args[0] for call in self.db.return_value.store_item.call_args_list]
        self.assertEqual(len(snapshots), 2)
        self.assertNotEqual(snapshots[0]["retrieved_at"], snapshots[1]["retrieved_at"])
        self.assertEqual(snapshots[0]["markets"]["totals"]["odds_data"]["book"], {"point": 8.5, "over_odds": 1.9})
