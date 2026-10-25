"""PropLine bulk retrieval. This module does not write to the canonical odds store.

Contract reviewed against https://prop-line.com/docs and /llms-full.txt, 2026-10-24.
One request includes every listed event and book for the sport, including props.
"""

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator

from odds_api.infrastructure.provider import retry_after

SPORT_KEYS = {
    "nhl_hockey": "hockey_nhl",
    "mlb_baseball": "baseball_mlb",
    "nfl_football": "football_nfl",
    "nba_basketball": "basketball_nba",
    "ncaaf_football": "football_ncaaf",
}
GAME_MARKETS = ("h2h", "spreads")
PROP_MARKETS = {
    "nhl_hockey": (
        "player_goals",
        "player_first_goal",
        "player_goals_2plus",
        "player_goals_3plus",
        "player_shots_on_goal",
        "total_shots_on_goal",
        "player_points_1plus",
        "player_points_2plus",
        "player_points_3plus",
        "goalie_saves",
        "player_blocked_shots",
        "player_power_play_points",
        "player_points",
        "player_assists",
        "player_hits",
    ),
    "mlb_baseball": (
        "pitcher_strikeouts",
        "pitcher_earned_runs",
        "pitcher_hits_allowed",
        "pitcher_outs",
        "pitcher_walks",
        "batter_hits",
        "batter_total_bases",
        "batter_walks",
        "batter_home_runs",
        "batter_stolen_bases",
        "batter_singles",
        "batter_rbis",
        "batter_doubles",
        "batter_runs",
        "batter_hits_runs_rbis",
        "batter_strikeouts",
        "batter_1plus_hits",
        "batter_2plus_hits",
        "batter_3plus_hits",
        "batter_4plus_hits",
        "batter_2plus_home_runs",
        "batter_1plus_rbis",
        "batter_2plus_rbis",
        "batter_3plus_rbis",
    ),
    "nfl_football": (
        "player_pass_yds",
        "player_pass_tds",
        "player_pass_interceptions",
        "player_pass_completions",
        "player_pass_attempts",
        "player_longest_completion",
        "player_rush_yds",
        "player_rush_tds",
        "player_rush_attempts",
        "player_rush_longest",
        "player_reception_yds",
        "player_receptions",
        "player_reception_tds",
        "player_reception_longest",
        "player_pass_rush_yds",
        "player_rush_reception_yds",
        "player_anytime_td",
        "player_1st_td",
        "player_2plus_td",
        "player_3plus_td",
        "player_sacks",
        "player_field_goals_made",
        "player_extra_points_made",
        "player_kicking_points",
        "player_fumbles_lost",
        "player_solo_tackles",
        "player_tackles_assists",
        "player_assists",
        "player_defensive_interceptions",
        "player_last_td",
    ),
    "nba_basketball": (
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_threes",
        "player_steals",
        "player_blocks",
        "player_turnovers",
        "player_points_assists",
        "player_points_rebounds",
        "player_points_rebounds_assists",
        "player_rebounds_assists",
        "player_blocks_steals",
        "player_double_double",
        "player_triple_double",
        "player_first_basket",
        "player_first_field_goal",
        "team_first_basket_scorer",
        "team_first_field_goal_scorer",
    ),
}
PROP_MARKETS["ncaaf_football"] = PROP_MARKETS["nfl_football"]
QUOTA_HEADERS = (
    "x-daily-limit",
    "x-daily-used",
    "x-daily-remaining",
    "x-daily-reset",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    "ratelimit-policy",
    "retry-after",
    "x-propline-missing-markets",
    "x-propline-hint",
)
# Retain these books in raw captures, but identify them separately for integration.
DFS_BOOKS = {"prizepicks", "underdog", "sleeper", "dabble", "parlayplay", "pick6", "draftkings_pick6"}


class ProplineError(RuntimeError):
    """Only safe classifications enter exception messages; never bodies or credentials."""

    def __init__(self, code, *, status=None, headers=None, retry_seconds=0):
        super().__init__(code)
        self.code, self.status = code, status
        self.headers = headers or {}
        self.retry_seconds = retry_seconds


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    @field_validator("*", mode="after")
    @classmethod
    def aware_times(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            raise ValueError("Timestamp must include timezone")
        return value


class Outcome(ResponseModel):
    name: str = Field(min_length=1)
    price: StrictInt
    point: float | None = Field(default=None, allow_inf_nan=False)
    description: str | None = None
    player_id: str | None = None
    last_seen_at: datetime | None = None
    book_updated_at: datetime | None = None
    last_change_at: datetime | None = None

    @field_validator("price")
    @classmethod
    def american(cls, value):
        if abs(value) < 100:
            raise ValueError("Invalid American odds")
        return value


class Market(ResponseModel):
    key: str = Field(min_length=1)
    period: str | None = None
    last_update: datetime | None = None
    suspended_at: datetime | None = None
    outcomes: list[Outcome]


class Bookmaker(ResponseModel):
    key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    pregame_only: bool = False
    markets: list[Market]


class Event(ResponseModel):
    id: str = Field(min_length=1)
    sport_key: str
    home_team: str = Field(min_length=1)
    away_team: str = Field(min_length=1)
    commence_time: datetime
    live: bool = False
    completed: bool = False
    bookmakers: list[Bookmaker]


@dataclass(frozen=True)
class BulkOdds:
    league: str
    events: tuple[Event, ...]
    raw: list[dict]
    headers: dict
    collected_at: datetime
    duration_seconds: float
    response_bytes: int


class ProplineClient:
    def __init__(self, settings, clock, http=None):
        self.clock = clock
        self.cooldown_until = 0.0
        self.remaining = None
        self.quota_reset_at = None
        self.requests = 0
        self.http = http or httpx.AsyncClient(
            base_url="https://api.prop-line.com",
            headers={"X-API-Key": settings.propline_api_key.get_secret_value(), "Accept": "application/json"},
            timeout=httpx.Timeout(settings.propline_request_timeout),
            follow_redirects=False,
        )

    async def fetch_bulk(self, league):
        if league not in SPORT_KEYS:
            raise ProplineError("unsupported_sport")
        if self.clock.monotonic() < self.cooldown_until:
            raise ProplineError(
                "provider_cooldown", retry_seconds=self.cooldown_until - self.clock.monotonic()
            )
        if self.quota_reset_at is not None and self.clock.now().timestamp() >= self.quota_reset_at:
            self.remaining, self.quota_reset_at = None, None
        if self.remaining == 0:
            raise ProplineError("daily_quota_exhausted")
        params = {
            "markets": ",".join((*GAME_MARKETS, *PROP_MARKETS[league])),
            "period": "all",
            "includeBookIds": "true",
            "includeLinks": "true",
        }
        # No per-event discovery, per-book fanout, or automatic retries.
        # Omitting bookmakers includes all books; omitting max_age preserves diagnostic coverage.
        started = self.clock.monotonic()
        self.requests += 1
        try:
            response = await self.http.get(f"/v1/sports/{SPORT_KEYS[league]}/odds", params=params)
        except httpx.HTTPError:
            raise ProplineError("transport_error") from None
        headers = {name: response.headers[name] for name in QUOTA_HEADERS if name in response.headers}
        try:
            self.remaining = int(headers.get("x-daily-remaining", headers.get("ratelimit-remaining")))
        except (TypeError, ValueError):
            pass
        try:
            self.quota_reset_at = int(headers["x-daily-reset"])
        except (KeyError, ValueError):
            pass
        status = response.status_code
        if status != 200:
            delay = retry_after(response.headers.get("Retry-After"), self.clock.now())
            if status in {429, 503}:
                self.cooldown_until = self.clock.monotonic() + max(delay, 1)
            raise ProplineError(
                {401: "authentication_failed", 403: "coverage_denied", 429: "rate_limited"}.get(
                    status, "unexpected_http_status"
                ),
                status=status,
                headers=headers,
                retry_seconds=delay,
            )
        try:
            raw = response.json()
            if not isinstance(raw, list):
                raise ValueError("Expected bulk array")
            events = tuple(Event.model_validate(item) for item in raw)
            if len({e.id for e in events}) != len(events):
                raise ValueError("Duplicate events")
            aliases = {SPORT_KEYS[league]}
            if league == "nfl_football":
                aliases.add("americanfootball_nfl")
            if any(e.sport_key not in aliases for e in events):
                raise ValueError("Unexpected sport")
            for event in events:
                if len({book.key for book in event.bookmakers}) != len(event.bookmakers):
                    raise ValueError("Duplicate bookmakers")
                for book in event.bookmakers:
                    for market in book.markets:
                        if market.key == "spreads" and any(o.point is None for o in market.outcomes):
                            raise ValueError("Spread missing line")
        except (ValidationError, ValueError, TypeError):
            raise ProplineError("invalid_bulk_response", status=status, headers=headers) from None
        return BulkOdds(
            league,
            events,
            raw,
            headers,
            self.clock.now(),
            self.clock.monotonic() - started,
            len(response.content),
        )

    async def close(self):
        await self.http.aclose()


def summarize(result, *, freshness_seconds=300):
    """Report coverage without flattening away periods, alt lines or prop shapes."""
    counts, by_book, by_market, games, samples = Counter(), {}, Counter(), [], {}
    for event in result.events:
        game_counts = Counter()
        for book in event.bookmakers:
            book_counts = by_book.setdefault(book.key, Counter())
            for market in book.markets:
                category = {"h2h": "moneyline", "spreads": "spread"}.get(market.key, "prop")
                by_market[market.key] += len(market.outcomes)
                counts["markets"] += 1
                for outcome in market.outcomes:
                    for target in (counts, book_counts, game_counts):
                        target[category + "_outcomes"] += 1
                        target["outcomes"] += 1
                    if book.key in DFS_BOOKS:
                        counts["dfs_outcomes"] += 1
                    if category == "prop" and outcome.player_id is None:
                        counts["props_without_player_id"] += 1
                    if category == "prop":
                        shape = "over_under" if outcome.point is not None else "milestone_or_yes_only"
                        counts["prop_shape:" + shape] += 1
                    unavailable = False
                    if market.suspended_at or book.pregame_only:
                        counts["suspended_or_pregame_only_outcomes"] += 1
                        unavailable = True
                    if market.last_update is None:
                        counts["outcomes_without_market_timestamp"] += 1
                        unavailable = True
                    elif (
                        not -5
                        <= (result.collected_at - market.last_update).total_seconds()
                        <= freshness_seconds
                    ):
                        counts["stale_outcomes"] += 1
                        unavailable = True
                    if (
                        outcome.last_seen_at
                        and market.last_update
                        and outcome.last_seen_at < market.last_update
                    ):
                        counts["withdrawn_outcomes"] += 1
                        unavailable = True
                    if not unavailable and book.key not in DFS_BOOKS:
                        counts["fresh_non_dfs_" + category + "_outcomes"] += 1
                    if (
                        category not in samples
                        and market.period is None
                        and not unavailable
                        and book.key not in DFS_BOOKS
                    ):
                        samples[category] = {
                            "event_id": event.id,
                            "bookmaker": book.key,
                            "market": market.key,
                            "period": market.period,
                            "name": outcome.name,
                            "description": outcome.description,
                            "point": outcome.point,
                            "price": outcome.price,
                        }
        games.append(
            {
                "id": event.id,
                "home_team": event.home_team,
                "away_team": event.away_team,
                "commence_time": event.commence_time.isoformat(),
                "live": event.live,
                "bookmakers": len(event.bookmakers),
                "counts": dict(game_counts),
            }
        )
    verified = all(counts["fresh_non_dfs_" + kind + "_outcomes"] for kind in ("moneyline", "spread", "prop"))
    return {
        "league": result.league,
        "sport_key": SPORT_KEYS[result.league],
        "schema_valid": True,
        "retrieval_verified": bool(verified),
        "events": len(result.events),
        "live_events": sum(e.live for e in result.events),
        "bookmakers": len(by_book),
        "counts": dict(counts),
        "by_bookmaker": {key: dict(value) for key, value in sorted(by_book.items())},
        "by_market": dict(sorted(by_market.items())),
        "games": games,
        "samples": samples,
        "headers": result.headers,
        "collected_at": result.collected_at.isoformat(),
        "duration_seconds": round(result.duration_seconds, 3),
        "response_bytes": result.response_bytes,
        "freshness_seconds": freshness_seconds,
    }


def request_budget(interval=480, sports=5):
    return {
        "interval_seconds": interval,
        "requests_per_cycle": sports,
        "requests_per_utc_day": math.ceil(86400 / interval) * sports,
        "automatic_retries": 0,
    }
