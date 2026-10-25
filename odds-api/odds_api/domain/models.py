"""Provider-independent identities, validation and availability rules."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5


class Availability(StrEnum):
    AVAILABLE = "available"
    SUSPENDED = "suspended"
    REMOVED = "removed"
    STALE = "stale"


def identity(kind: str, *parts: object) -> str:
    import json

    return uuid5(NAMESPACE_URL, json.dumps(["odds-api", kind, *map(str, parts)])).hex


def utc(value: datetime) -> datetime:
    from datetime import UTC

    if value.tzinfo is None:
        raise ValueError("A timezone-aware timestamp is required")
    return value.astimezone(UTC)


def decimal_odds(american: int) -> Decimal:
    if not isinstance(american, int) or isinstance(american, bool) or abs(american) < 100:
        raise ValueError("American odds must be <= -100 or >= 100")
    return Decimal(1) + (Decimal(american) / 100 if american > 0 else Decimal(100) / -american)


def american_odds(value: Decimal) -> int:
    if not value.is_finite() or value <= 1:
        raise ValueError("Decimal odds must be finite and greater than one")
    result = (value - 1) * 100 if value >= 2 else -100 / (value - 1)
    return int(result.to_integral_value())


@dataclass(frozen=True)
class League:
    key: str
    title: str
    route: str
    source_id: str


@dataclass(frozen=True)
class Event:
    source_id: str
    league_key: str
    start: datetime
    home: str
    away: str
    status: str

    def __post_init__(self):
        object.__setattr__(self, "start", utc(self.start))
        if not self.source_id or not self.home or not self.away:
            raise ValueError("Event identity and team names are required")
        if self.status not in {"pregame", "live", "final", "delayed", "postponed", "cancelled", "unknown"}:
            raise ValueError("Invalid event state")

    @property
    def id(self) -> str:
        # Public league names may change without invalidating saved event IDs.
        namespace = {
            "nba_basketball": "basketball_nba",
            "nfl_football": "americanfootball_nfl",
            "mlb_baseball": "baseball_mlb",
        }.get(self.league_key, self.league_key)
        return identity("event", namespace, self.source_id)


@dataclass(frozen=True)
class Sportsbook:
    source_id: str
    title: str
    provider: str = "unabated"

    @property
    def id(self) -> str:
        return (
            identity("book", self.source_id)
            if self.provider == "unabated"
            else identity("book", self.provider, self.source_id)
        )

    @property
    def key(self) -> str:
        if self.provider == "bet365":
            return "bet365"
        return self.provider + "_" + self.source_id


@dataclass(frozen=True)
class Quote:
    event_id: str
    book_id: str
    market: str
    period: str
    player_id: str | None
    point: Decimal | None
    alternate: bool
    name: str
    description: str | None
    source_market_id: str
    source_selection_id: str
    price: int | None
    state: Availability
    collected_at: datetime
    source_updated_at: datetime | None = None
    expires_at: datetime | None = None
    deep_link: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "collected_at", utc(self.collected_at))
        for field in ("source_updated_at", "expires_at"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, utc(value))
        if self.price is not None:
            decimal_odds(self.price)
        if self.state == Availability.AVAILABLE and self.price is None:
            raise ValueError("Available selections require a price")
        if self.point is not None and not self.point.is_finite():
            raise ValueError("Line must be finite")
        if not self.name or not self.market or not self.period:
            raise ValueError("Selection context is required")

    @property
    def market_id(self) -> str:
        line = str(self.point.normalize()) if self.point is not None else ""
        return identity(
            "market",
            self.event_id,
            self.book_id,
            self.market,
            self.period,
            self.player_id or "",
            line,
            self.alternate,
        )

    @property
    def selection_id(self) -> str:
        # Provider line IDs can change when a selection is relisted.
        return identity("selection", self.market_id, self.name)

    def availability(self, now: datetime, collected_ttl: float, source_ttl: float) -> Availability:
        if self.state != Availability.AVAILABLE:
            return self.state
        now = utc(now)
        if now - utc(self.collected_at) > timedelta(seconds=collected_ttl):
            return Availability.STALE
        if self.source_updated_at and now - utc(self.source_updated_at) > timedelta(seconds=source_ttl):
            return Availability.STALE
        if self.expires_at and now >= utc(self.expires_at):
            return Availability.STALE
        return Availability.AVAILABLE


@dataclass(frozen=True)
class Board:
    league: League
    kind: str
    events: tuple[Event, ...]
    books: tuple[Sportsbook, ...]
    quotes: tuple[Quote, ...]
    collected_at: datetime
    complete: bool
    warnings: tuple[str, ...] = ()
    provider: str = "unabated"
    covered_markets: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "collected_at", utc(self.collected_at))
        if self.kind not in {"moneyline", "props"}:
            raise ValueError("Unsupported board kind")
        if self.provider not in {"unabated", "bet365", "propline"}:
            raise ValueError("Unsupported board provider")
        if self.provider == "bet365" and (
            not self.covered_markets or any(b.provider != "bet365" for b in self.books)
        ):
            raise ValueError("Bet365 boards require explicit market coverage and provider-owned books")
        if self.provider == "propline" and (
            not self.covered_markets or any(b.provider != "propline" for b in self.books)
        ):
            raise ValueError("PropLine boards require explicit market coverage and provider-owned books")
        if any(e.league_key != self.league.key for e in self.events):
            raise ValueError("Board contains another league")
        event_ids, book_ids = {e.id for e in self.events}, {b.id for b in self.books}
        if any(q.event_id not in event_ids or q.book_id not in book_ids for q in self.quotes):
            raise ValueError("Quote references missing event or book")
