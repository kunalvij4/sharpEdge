import json
from functools import cached_property
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_LEAGUES = {
    "nhl_hockey": {"title": "NHL", "route": "nhl"},
    "nba_basketball": {"title": "NBA", "route": "nba"},
    "nfl_football": {"title": "NFL", "route": "nfl"},
    "mlb_baseball": {"title": "MLB", "route": "mlb"},
    "ncaaf_football": {"title": "NCAAF", "route": "cfb"},
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    storage_backend: Literal["redis", "sql"] = "redis"
    redis_url: SecretStr = SecretStr("")
    redis_prefix: str = "sharpedge:odds:v1"
    unabated_enabled: bool = True
    unabated_odds_enabled: bool = True
    database_url: str = "sqlite:///./odds.db"
    api_keys: SecretStr = SecretStr("")
    unabated_api_key: SecretStr = SecretStr("")
    propline_api_key: SecretStr = SecretStr("")
    propline_enabled: bool = True
    propline_poll_interval: float = Field(default=480, ge=480)
    propline_request_timeout: float = Field(default=90, gt=0)
    propline_collected_ttl: float = Field(default=600, ge=300)
    propline_max_age: float = Field(default=900, ge=300)
    propline_output_dir: str = "artifacts/propline"
    unabated_api_base_url: str = "https://data.unabated.com"
    unabated_partner_code: str = ""
    leagues_json: str = json.dumps(DEFAULT_LEAGUES)
    poll_interval: float = Field(default=480, gt=0)
    collection_state_path: str = "artifacts/collection/schedule.json"
    request_timeout: float = Field(default=15, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_backoff: float = Field(default=1, gt=0)
    rate_min_interval: float = Field(default=0.1, ge=0)
    odds_min_interval: float = Field(default=5, ge=0)
    metadata_ttl: float = Field(default=3600, gt=0)
    scope_metadata_ttl: float = Field(default=300, gt=0)
    collected_ttl: float = Field(default=600, gt=0)
    source_ttl: float = Field(default=3600, gt=0)
    props_cache_ttl: float = Field(default=3600, ge=0)
    snapshot_retention_days: int = Field(default=0, ge=0)
    shutdown_timeout: float = Field(default=20, gt=0)
    bet365_enabled: bool = False
    bet365_region: str = Field(default="nj", pattern="^(nj|va)$")
    bet365_interval: float = Field(default=90, ge=60, le=120)
    bet365_max_age: float = Field(default=150, ge=60, le=300)
    bet365_wait: float = Field(default=8, ge=1, le=30)
    bet365_command_timeout: float = Field(default=100, ge=30, le=180)
    bet365_output_dir: str = "/app/artifacts/bet365"
    unabated_bet_type_map: dict[str, str] = {}
    unabated_period_map: dict[str, str] = {}

    @cached_property
    def leagues(self) -> dict:
        aliases = {
            "basketball_nba": "nba_basketball",
            "americanfootball_nfl": "nfl_football",
            "baseball_mlb": "mlb_baseball",
            "icehockey_nhl": "nhl_hockey",
            "hockey_nhl": "nhl_hockey",
            "football_ncaaf": "ncaaf_football",
            "americanfootball_ncaaf": "ncaaf_football",
        }
        result = {}
        for key, value in json.loads(self.leagues_json).items():
            key = aliases.get(key, key)
            if key in result:
                raise ValueError("Duplicate canonical league key in LEAGUES_JSON")
            if key == "ncaaf_football" and value["route"] == "ncaaf":
                value = {**value, "route": "cfb"}
            result[key] = value
        return result

    @model_validator(mode="after")
    def valid(self):
        import re

        if not self.leagues or any(
            not re.fullmatch(r"[a-z0-9_]+", k) or not re.fullmatch(r"[a-z0-9_-]+", v["route"])
            for k, v in self.leagues.items()
        ):
            raise ValueError("LEAGUES_JSON requires sport keys with provider route names")
        if not self.unabated_api_base_url.startswith("https://"):
            raise ValueError("UNABATED_API_BASE_URL must use HTTPS")
        if self.propline_enabled and self.propline_collected_ttl < self.propline_poll_interval:
            raise ValueError("PROPLINE_COLLECTED_TTL must cover PROPLINE_POLL_INTERVAL")
        return self
