import hmac
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader, APIKeyQuery
from sqlalchemy.exc import SQLAlchemyError

from odds_api.application.services import OddsQueryService, QueryError
from odds_api.http.schemas import (
    ErrorResponse,
    EventResponse,
    HealthResponse,
    OddsResponse,
    SportResponse,
    StatusResponse,
    ValidationErrorResponse,
)
from odds_api.infrastructure.clock import SystemClock
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.normalization import BET_NAMES, PERIOD_NAMES
from odds_api.infrastructure.repository import SqlRepository

header_key = APIKeyHeader(name="X-API-Key", auto_error=False)
query_key = APIKeyQuery(name="apiKey", auto_error=False)
ERRORS = {
    401: {"model": ErrorResponse, "description": "Missing or invalid product API key"},
    404: {"model": ErrorResponse, "description": "Unknown sport or event"},
    422: {
        "model": ValidationErrorResponse,
        "description": "Invalid format, time bounds, or unsupported filter",
    },
    503: {"model": ErrorResponse, "description": "Internal dependency unavailable"},
}


def create_app(settings=None, repository=None, clock=None):
    settings, clock = settings or Settings(), clock or SystemClock()

    @asynccontextmanager
    async def lifespan(app):
        if not settings.api_keys.get_secret_value().strip():
            raise RuntimeError("Set API_KEYS to one or more comma-separated product keys")
        app.state.repository = repository or SqlRepository(settings.database_url, settings.leagues)
        bases = set(BET_NAMES.values()) | set(settings.unabated_bet_type_map.values())
        periods = set(PERIOD_NAMES.values()) | set(settings.unabated_period_map.values())
        markets = {
            base + alt + suffix
            for base in bases
            for alt in ("", "_alternate")
            for suffix in ("", *("_" + p for p in periods if p != "full"))
        }
        app.state.query = OddsQueryService(
            app.state.repository,
            clock,
            settings.collected_ttl,
            settings.source_ttl,
            markets,
            settings.props_cache_ttl,
        )
        yield
        if repository is None:
            app.state.repository.close()

    app = FastAPI(
        title="In-House Odds API",
        version="0.1.0",
        description="Persisted Unabated moneylines and player props. Auth uses your product key. "
        "Source timestamps can be null. See /status for collection freshness.",
        lifespan=lifespan,
    )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_, error):
        return JSONResponse(status_code=503, content={"detail": "Database temporarily unavailable"})

    @app.exception_handler(QueryError)
    async def query_error(_, error):
        return JSONResponse(status_code=error.status, content={"detail": str(error)})

    async def authenticate(
        header: str | None = Security(header_key), query: str | None = Security(query_key)
    ):
        supplied = header or query or ""
        keys = [k.strip() for k in settings.api_keys.get_secret_value().split(",") if k.strip()]
        if not supplied or not any(hmac.compare_digest(supplied.encode(), k.encode()) for k in keys):
            raise HTTPException(401, "Missing or invalid product API key")

    def queries(request: Request):
        return request.app.state.query

    def make_filters(default_markets):
        def filters(
            request: Request,
            markets: Annotated[
                str,
                Query(
                    description="Comma-separated public market keys, or all_props for every supported player prop"
                ),
            ] = default_markets,
            bookmakers: Annotated[
                str | None, Query(description="Stable sportsbook keys, e.g. unabated_91")
            ] = None,
            oddsFormat: Annotated[
                Literal["american", "decimal"], Query(description="Output price format")
            ] = "decimal",
            commenceTimeFrom: Annotated[
                datetime | None, Query(description="Inclusive ISO 8601 time with UTC offset")
            ] = None,
            commenceTimeTo: Annotated[
                datetime | None, Query(description="Inclusive ISO 8601 time with UTC offset")
            ] = None,
            freshOnly: Annotated[
                bool, Query(description="Exclude cached props older than the collection freshness limit")
            ] = False,
        ):
            allowed = {
                "markets",
                "bookmakers",
                "oddsFormat",
                "commenceTimeFrom",
                "commenceTimeTo",
                "apiKey",
                "freshOnly",
            }
            if set(request.query_params) - allowed:
                raise QueryError("Unsupported query parameter")
            return {
                "markets": markets,
                "bookmakers": bookmakers,
                "odds_format": oddsFormat,
                "start": commenceTimeFrom,
                "end": commenceTimeTo,
                "fresh_only": freshOnly,
            }

        return filters

    filters = make_filters("h2h")
    props_filters = make_filters("all_props")

    def freshness(response: Response):
        response.headers["X-Odds-Observed-At"] = clock.now().isoformat()
        response.headers["X-Odds-Collected-TTL"] = str(settings.collected_ttl)
        response.headers["X-Odds-Source-TTL"] = str(settings.source_ttl)
        response.headers["X-Odds-Props-Cache-TTL"] = str(settings.props_cache_ttl)
        response.headers["Cache-Control"] = "no-store"

    @app.get(
        "/health/live", response_model=HealthResponse, tags=["Health"], summary="Check HTTP process liveness"
    )
    def live():
        return {"status": "ok"}

    @app.get(
        "/health/ready",
        response_model=HealthResponse,
        responses={503: ERRORS[503]},
        tags=["Health"],
        summary="Check database connectivity and migration revision",
    )
    def ready(request: Request):
        if not request.app.state.repository.ready():
            raise HTTPException(503, "Database unavailable or migration required")
        return {"status": "ready"}

    @app.get(
        "/status",
        response_model=StatusResponse,
        dependencies=[Depends(authenticate)],
        responses=ERRORS,
        tags=["Health"],
        summary="Inspect collection health and freshness",
    )
    def status(request: Request):
        return request.app.state.repository.status(clock.now(), settings.collected_ttl, settings.source_ttl)

    @app.get(
        "/v4/sports",
        response_model=list[SportResponse],
        dependencies=[Depends(authenticate)],
        responses=ERRORS,
        tags=["Odds"],
        summary="List configured leagues",
    )
    def sports(service=Depends(queries)):
        return service.sports()

    @app.get(
        "/v4/sports/{sport}/events",
        response_model=list[EventResponse],
        dependencies=[Depends(authenticate)],
        responses=ERRORS,
        tags=["Odds"],
        summary="List pregame and live events, including delayed and postponed events",
    )
    def events(
        sport: str,
        request: Request,
        commenceTimeFrom: Annotated[
            datetime | None, Query(description="Inclusive ISO 8601 lower bound")
        ] = None,
        commenceTimeTo: Annotated[
            datetime | None, Query(description="Inclusive ISO 8601 upper bound")
        ] = None,
        service=Depends(queries),
    ):
        if set(request.query_params) - {"commenceTimeFrom", "commenceTimeTo", "apiKey"}:
            raise QueryError("Unsupported query parameter")
        return service.events(sport, commenceTimeFrom, commenceTimeTo)

    @app.get(
        "/v4/sports/{sport}/odds",
        response_model=list[OddsResponse],
        response_model_exclude_unset=True,
        dependencies=[Depends(authenticate)],
        responses=ERRORS,
        tags=["Odds"],
        summary="Retrieve actionable moneylines across events",
    )
    def odds(sport: str, response: Response, options=Depends(filters), service=Depends(queries)):
        freshness(response)
        return service.moneylines(sport, **options)

    @app.get(
        "/v4/sports/{sport}/events/{event_id}/odds",
        response_model=OddsResponse,
        response_model_exclude_unset=True,
        dependencies=[Depends(authenticate)],
        responses=ERRORS,
        tags=["Odds"],
        summary="Retrieve event moneylines and player props",
        description="Player props can include bounded cached prices with freshness.status=stale and "
        "actionable=false. Use freshOnly=true to exclude cached prices; markets=all_props selects all supported props.",
    )
    def event_odds(
        sport: str, event_id: str, response: Response, options=Depends(filters), service=Depends(queries)
    ):
        freshness(response)
        payload = service.odds(sport, event_id=event_id, **options)
        if "freshness" in payload:
            response.headers["X-Odds-Data-Status"] = payload["freshness"]["status"]
        return payload

    @app.get(
        "/v4/sports/{sport}/events/{event_id}/props",
        response_model=OddsResponse,
        response_model_exclude_unset=True,
        dependencies=[Depends(authenticate)],
        responses=ERRORS,
        tags=["Odds"],
        summary="Retrieve all supported player props, alternates, and periods for an event",
        description="Returns stored props from every book. Cached prices are bounded and labeled stale, "
        "with actionable=false and original timestamps. Use freshOnly=true for actionable prices only.",
    )
    def event_props(
        sport: str,
        event_id: str,
        response: Response,
        options=Depends(props_filters),
        service=Depends(queries),
    ):
        freshness(response)
        payload = service.props(sport, event_id, **options)
        response.headers["X-Odds-Data-Status"] = payload["freshness"]["status"]
        return payload

    return app
