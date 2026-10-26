"""The five leagues and reference player-prop keys for pipeline verification."""

LEAGUE_SPORT_KEYS = {
    "NBA": "basketball_nba",
    "NFL": "americanfootball_nfl",
    "NHL": "icehockey_nhl",
    "MLB": "baseball_mlb",
    "NCAAF": "americanfootball_ncaaf",
}
LEAGUES = tuple(LEAGUE_SPORT_KEYS)

# Reference two-sided markets used by the regression fixtures. Collection uses
# the in-house all_props selector, so these lists do not restrict new markets.
# Provider reference: https://the-odds-api.com/sports-odds-data/betting-markets.html
FOOTBALL_PROP_MARKETS = (
    "player_pass_yds", "player_pass_tds", "player_pass_attempts",
    "player_pass_completions", "player_pass_interceptions",
    "player_pass_longest_completion", "player_rush_yds", "player_rush_attempts",
    "player_rush_tds", "player_rush_longest", "player_receptions",
    "player_reception_yds", "player_reception_tds", "player_reception_longest",
    "player_rush_reception_yds", "player_pass_rush_yds", "player_tackles_assists",
    "player_solo_tackles", "player_sacks", "player_kicking_points", "player_field_goals",
)
PROP_MARKETS_BY_LEAGUE = {
    "NBA": (
        "player_points", "player_rebounds", "player_assists", "player_threes",
        "player_blocks", "player_steals", "player_blocks_steals", "player_turnovers",
        "player_points_rebounds_assists", "player_points_rebounds",
        "player_points_assists", "player_rebounds_assists",
    ),
    "NFL": FOOTBALL_PROP_MARKETS,
    "NHL": (
        "player_points", "player_assists", "player_goals", "player_shots_on_goal",
        "player_blocked_shots", "player_power_play_points", "player_total_saves",
    ),
    "MLB": (
        "batter_hits", "batter_total_bases", "batter_home_runs", "batter_rbis",
        "batter_runs_scored", "batter_hits_runs_rbis", "batter_singles",
        "batter_doubles", "batter_triples", "batter_walks", "batter_strikeouts",
        "batter_stolen_bases", "pitcher_strikeouts", "pitcher_hits_allowed",
        "pitcher_walks", "pitcher_earned_runs", "pitcher_outs",
    ),
    "NCAAF": FOOTBALL_PROP_MARKETS,
}
PROP_MARKETS_BY_SPORT = {
    LEAGUE_SPORT_KEYS[league]: markets
    for league, markets in PROP_MARKETS_BY_LEAGUE.items()
}
