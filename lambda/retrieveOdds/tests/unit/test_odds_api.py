from unittest.mock import Mock

from odds_api import OddsAPI


def test_get_odds_calls_in_house_endpoint_with_header_auth():
    api = OddsAPI(api_key="product-key", base_url="https://odds.example.com/")
    response = Mock()
    response.json.return_value = []
    api.session.get = Mock(return_value=response)

    assert api.get_odds("basketball_nba", markets="h2h") == []

    api.session.get.assert_called_once_with(
        "https://odds.example.com/v1/sports/nba_basketball/odds",
        params={"markets": "h2h", "oddsFormat": "decimal"},
        headers={"X-API-Key": "product-key"},
        timeout=20,
    )
    response.raise_for_status.assert_called_once_with()


def test_get_event_odds_uses_in_house_event_route():
    api = OddsAPI(api_key="product-key", base_url="http://localhost:8000")
    response = Mock()
    response.json.return_value = {"bookmakers": []}
    api.session.get = Mock(return_value=response)

    assert api.get_event_odds(
        "event-123", markets="player_points"
    ) == {"bookmakers": []}

    api.session.get.assert_called_once_with(
        "http://localhost:8000/v1/events/event-123/odds",
        params={"markets": "player_points", "oddsFormat": "decimal"},
        headers={"X-API-Key": "product-key"},
        timeout=20,
    )
    response.raise_for_status.assert_called_once_with()


def test_parse_in_house_odds_response():
    api = OddsAPI(api_key="product-key", base_url="https://odds.example.com")

    games = api.parse_all_markets_odds(
        [
            {
                "id": "event-123",
                "sport_title": "NBA",
                "home_team": "Home",
                "away_team": "Away",
                "commence_time": "2026-10-24T18:00:00Z",
                "bookmakers": [
                    {
                        "key": "unabated_1",
                        "title": "Sharp Book",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Home", "price": 1.9},
                                    {"name": "Away", "price": 2.0},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    )

    game = games["NBA_Home_vs_Away"]
    assert game["event_id"] == "event-123"
    assert game["markets"]["moneyline"]["odds_data"]["Sharp Book"] == {
        "home_odds": 1.9,
        "away_odds": 2.0,
    }
