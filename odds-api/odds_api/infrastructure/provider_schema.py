"""Only upstream transport schemas. Never persisted or returned publicly."""

from pydantic import BaseModel, ConfigDict


class Source(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    name: str
    isActive: bool = False
    statusId: int = 0
    propsStatusId: int = 0
    disabledMarketTypeIds: list[int] | None = None


class Line(BaseModel):
    model_config = ConfigDict(extra="ignore")
    marketSourceId: int
    marketLineId: int
    marketId: int | None = None
    price: int | None = None
    points: float | None = None
    statusId: int
    disabled: bool = False
    modifiedOn: str | None = None
    freshnessExpiresAt: str | None = None
    deepLink: str | None = None
    alternateLines: list[dict] | None = None
