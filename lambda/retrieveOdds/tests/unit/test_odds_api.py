import importlib
from unittest.mock import Mock

import pytest


@pytest.fixture
def api_class():
    return importlib.import_module("odds_pipeline.provider").OddsAPI


@pytest.mark.parametrize("sport, public_key", [
    ("basketball_nba", "nba_basketball"),
    ("americanfootball_nfl", "nfl_football"),
    ("icehockey_nhl", "nhl_hockey"),
    ("baseball_mlb", "mlb_baseball"),
    ("americanfootball_ncaaf", "ncaaf_football"),
])
def test_get_odds_calls_in_house_endpoint_with_header_auth(api_class, sport, public_key):
    api = api_class(api_key="product-key", base_url="https://odds.example.com/")
    response = Mock()
    response.json.return_value = []
    api.session.get = Mock(return_value=response)

    assert api.get_odds(sport, markets="h2h,spreads") == []

    api.session.get.assert_called_once_with(
        f"https://odds.example.com/v1/sports/{public_key}/odds",
        params={"markets": "h2h,spreads", "oddsFormat": "decimal"},
        headers={"X-API-Key": "product-key"},
        timeout=20,
    )
    response.raise_for_status.assert_called_once_with()


def test_get_event_odds_uses_in_house_event_route(api_class):
    api = api_class(api_key="product-key", base_url="http://localhost:8000")
    response = Mock()
    response.json.return_value = {"bookmakers": []}
    api.session.get = Mock(return_value=response)

    assert api.get_event_odds(
        "basketball_nba", "event-123", markets="all_props"
    ) == {"bookmakers": []}

    api.session.get.assert_called_once_with(
        "http://localhost:8000/v1/events/event-123/odds",
        params={"markets": "all_props", "oddsFormat": "decimal", "freshOnly": "true"},
        headers={"X-API-Key": "product-key"},
        timeout=20,
    )
    response.raise_for_status.assert_called_once_with()


def test_parse_in_house_odds_response(api_class):
    api = api_class(api_key="product-key", base_url="https://odds.example.com")

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

    game = games["event-123"]
    assert game["event_id"] == "event-123"
    assert game["markets"]["moneyline"]["odds_data"]["Sharp Book"] == {
        "home_odds": 1.9,
        "away_odds": 2.0,
    }
