import json
from functools import cached_property

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_LEAGUES = {
    "nba_basketball": {"title": "NBA", "route": "nba"},
    "nfl_football": {"title": "NFL", "route": "nfl"},
    "mlb_baseball": {"title": "MLB", "route": "mlb"},
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./odds.db"
    api_keys: SecretStr = SecretStr("")
    unabated_api_key: SecretStr = SecretStr("")
    unabated_api_base_url: str = "https://data.unabated.com"
    unabated_partner_code: str = ""
    leagues_json: str = json.dumps(DEFAULT_LEAGUES)
    poll_interval: float = Field(default=30, gt=0)
    request_timeout: float = Field(default=15, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_backoff: float = Field(default=1, gt=0)
    rate_min_interval: float = Field(default=0.1, ge=0)
    odds_min_interval: float = Field(default=5, ge=0)
    metadata_ttl: float = Field(default=3600, gt=0)
    scope_metadata_ttl: float = Field(default=300, gt=0)
    collected_ttl: float = Field(default=90, gt=0)
    source_ttl: float = Field(default=3600, gt=0)
    props_cache_ttl: float = Field(default=3600, ge=0)
    snapshot_retention_days: int = Field(default=0, ge=0)
    shutdown_timeout: float = Field(default=20, gt=0)
    bet365_enabled: bool = True
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
        }
        result = {}
        for key, value in json.loads(self.leagues_json).items():
            key = aliases.get(key, key)
            if key in result:
                raise ValueError("Duplicate canonical league key in LEAGUES_JSON")
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
        return self
