from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Unknown sport"}})
    detail: str


class ValidationErrorResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Unsupported market filter"}})
    detail: str | list[dict]


class HealthResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"status": "ok"}})
    status: Literal["ok", "ready"]


class SportResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "key": "basketball_nba",
                "group": "Basketball",
                "title": "NBA",
                "description": "NBA",
                "active": True,
                "has_outrights": False,
            }
        }
    )
    key: str
    group: str
    title: str
    description: str
    active: bool
    has_outrights: bool


class EventResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "example-event-id",
                "sport_key": "basketball_nba",
                "sport_title": "NBA",
                "commence_time": "2026-10-19T00:00:00Z",
                "home_team": "Home Team",
                "away_team": "Away Team",
            }
        }
    )
    id: str
    sport_key: str
    sport_title: str
    commence_time: datetime
    home_team: str
    away_team: str


class QuoteFreshness(BaseModel):
    status: Literal["fresh", "stale"]
    actionable: bool
    collected_at: datetime
    source_updated_at: datetime | None
    expires_at: datetime | None
    age_seconds: float


class ResponseFreshness(BaseModel):
    observed_at: datetime
    status: Literal["fresh", "stale", "mixed", "unavailable"]
    fresh_outcomes: int
    stale_outcomes: int
    max_cache_age_seconds: float


class OutcomeResponse(BaseModel):
    name: str
    price: int | float
    point: float | None = None
    description: str | None = None
    freshness: QuoteFreshness | None = None


class MarketResponse(BaseModel):
    key: str
    last_update: datetime | None
    outcomes: list[OutcomeResponse]


class BookmakerResponse(BaseModel):
    key: str
    title: str
    last_update: datetime | None
    markets: list[MarketResponse]


class OddsResponse(EventResponse):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                **EventResponse.model_config["json_schema_extra"]["example"],
                "bookmakers": [
                    {
                        "key": "unabated_901",
                        "title": "Example Book",
                        "last_update": None,
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": None,
                                "outcomes": [
                                    {"name": "Home Team", "price": 1.91},
                                    {"name": "Away Team", "price": 2.1},
                                ],
                            }
                        ],
                    }
                ],
            }
        }
    )
    bookmakers: list[BookmakerResponse]
    freshness: ResponseFreshness | None = None


class ScopeStatus(BaseModel):
    league: str
    kind: str
    last_success: datetime | None
    last_attempt: datetime | None
    outcome: str
    failures: int
    missed_deadlines: int
    scheduling_lag: float
    selection_count: int
    warnings: list[str]


class StatusResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "service": "ok",
                "collector_healthy": False,
                "collector_heartbeat": None,
                "provider_metrics": {},
                "scopes": [],
                "counts": {"events": 0, "markets": 0, "selections": 0},
                "stale_quotes": 0,
                "observed_at": "2026-10-19T00:00:00Z",
            }
        }
    )
    service: str
    collector_healthy: bool
    collector_heartbeat: datetime | None
    provider_metrics: dict[str, int]
    scopes: list[ScopeStatus]
    counts: dict[str, int]
    stale_quotes: int
    observed_at: datetime
    bet365: dict = Field(default_factory=dict)
