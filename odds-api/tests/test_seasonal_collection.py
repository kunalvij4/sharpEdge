import json

from odds_api.infrastructure.config import DEFAULT_LEAGUES, Settings


def test_full_legacy_catalog_starts_ncaab_and_pauses_mlb_without_removing_routes():
    old_catalog = {key: value for key, value in DEFAULT_LEAGUES.items() if key != "ncaab_basketball"}
    settings = Settings(_env_file=None, leagues_json=json.dumps(old_catalog))
    assert "mlb_baseball" in settings.leagues
    assert "mlb_baseball" not in settings.collection_leagues
    assert settings.collection_leagues["ncaab_basketball"] == {"title": "NCAAB", "route": "cbb"}


def test_collection_pause_can_be_lifted_without_changing_the_api_catalog():
    settings = Settings(_env_file=None, collection_excluded_leagues=set())
    assert settings.collection_leagues == settings.leagues
    assert "mlb_baseball" in settings.collection_leagues


def test_single_league_deployments_remain_scoped_and_ncaab_alias_uses_cbb():
    settings = Settings(_env_file=None, leagues_json='{"basketball_ncaab":{"title":"NCAAB","route":"ncaab"}}')
    assert settings.leagues == {"ncaab_basketball": {"title": "NCAAB", "route": "cbb"}}
    assert settings.collection_leagues == settings.leagues
