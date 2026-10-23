import logging
from datetime import datetime
from decimal import Decimal

from odds_api.application.ports import Clock, Provider, Repository
from odds_api.domain.models import Availability, decimal_odds

log = logging.getLogger(__name__)


class QueryError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


class CollectionService:
    def __init__(self, provider: Provider, repository: Repository, clock: Clock):
        self.provider, self.repository, self.clock = provider, repository, clock

    async def collect(self, sport: str, kind: str) -> None:
        from uuid import uuid4

        run, started = uuid4().hex, self.clock.monotonic()
        outcome, count = "failed", 0
        diagnostics = {}
        try:
            board = await self.provider.fetch(sport, kind)
            self.repository.save(board)
            count = len(board.quotes)
            diagnostics["warnings"] = list(board.warnings[:20])
            outcome = ("empty" if not count else "success") if board.complete else "partial"
        except Exception as error:
            # Exception messages can contain upstream secrets. Log a safe classification only.
            outcome = getattr(error, "code", "collection_error")
            diagnostics = {
                "error_type": type(error).__name__,
                **{
                    field: getattr(error, field, None)
                    for field in (
                        "provider_path",
                        "provider_http_status",
                        "failure_reason",
                    )
                },
            }
            self.repository.failure(sport, kind, outcome)
        finally:
            log.info(
                "collection",
                extra={
                    "league": sport,
                    "market": kind,
                    "run": run,
                    "duration": self.clock.monotonic() - started,
                    "outcome": outcome,
                    "selections": count,
                    **diagnostics,
                },
            )


class OddsQueryService:
    def __init__(
        self,
        repository: Repository,
        clock: Clock,
        collected_ttl: float,
        source_ttl: float,
        supported_markets: set[str],
        props_cache_ttl: float = 3600,
        bet365_collected_ttl: float = 150,
    ):
        self.repository, self.clock = repository, clock
        self.collected_ttl, self.source_ttl = collected_ttl, source_ttl
        self.supported_markets = supported_markets
        self.props_cache_ttl = props_cache_ttl
        self.bet365_collected_ttl = bet365_collected_ttl

    def sports(self) -> list[dict]:
        return [
            {
                "key": league.key,
                "group": league.key.split("_")[0].title(),
                "title": league.title,
                "description": league.title,
                "active": True,
                "has_outrights": False,
            }
            for league in self.repository.leagues()
        ]

    def validate(
        self,
        sport: str,
        markets: str | None = None,
        bookmakers: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ):
        if sport not in {league.key for league in self.repository.leagues()}:
            raise QueryError("Unknown sport", 404)

        def parse(value):
            if value is None:
                return None
            result = set(value.split(","))
            if not result or any(not x or x != x.strip() for x in result):
                raise QueryError("Filters require comma-separated nonempty keys")
            return result

        market_set, book_set = parse(markets), parse(bookmakers)
        if market_set == {"all_props"}:
            market_set = {market for market in self.supported_markets if not market.startswith("h2h")}
        if market_set and market_set - self.supported_markets:
            raise QueryError("Unsupported market filter")
        if book_set and book_set - self.repository.bookmakers():
            raise QueryError("Unknown sportsbook filter")
        if any(t is not None and t.tzinfo is None for t in (start, end)):
            raise QueryError("Time bounds require a UTC offset")
        if start and end and start > end:
            raise QueryError("commenceTimeFrom must precede commenceTimeTo")
        return market_set, book_set

    def events(self, sport: str, start=None, end=None) -> list[dict]:
        self.validate(sport, start=start, end=end)
        return [
            self.event_payload(e)
            for e in self.repository.events(sport)
            if e["status"] not in {"final", "cancelled"}
            and (start is None or e["start"] >= start)
            and (end is None or e["start"] <= end)
        ]

    @staticmethod
    def event_payload(e: dict) -> dict:
        return {
            "id": e["id"],
            "sport_key": e["league_key"],
            "sport_title": e["sport_title"],
            "commence_time": e["start"],
            "home_team": e["home"],
            "away_team": e["away"],
        }

    def moneylines(self, sport: str, **options):
        requested = options.get("markets", "h2h").split(",")
        if any(not (m == "h2h" or m.startswith("h2h_")) for m in requested):
            raise QueryError("Player props require the event odds endpoint")
        return self.odds(sport, **options)

    def props(self, sport: str, event_id: str, *, markets="all_props", **options):
        market_set, _ = self.validate(sport, markets)
        if any(market.startswith("h2h") for market in market_set):
            raise QueryError("The props endpoint accepts only player prop markets")
        return self.odds(sport, event_id=event_id, markets=markets, **options)

    def odds(
        self,
        sport: str,
        *,
        event_id=None,
        markets="h2h",
        bookmakers=None,
        odds_format="decimal",
        start=None,
        end=None,
        fresh_only=False,
    ) -> list[dict] | dict:
        market_set, book_set = self.validate(sport, markets, bookmakers, start, end)
        prop_query = bool(market_set and any(not market.startswith("h2h") for market in market_set))
        if odds_format not in {"american", "decimal"}:
            raise QueryError("Invalid oddsFormat")
        events = {e["id"]: e for e in self.repository.events(sport)}
        if event_id is not None and event_id not in events:
            raise QueryError("Unknown event", 404)
        now, grouped = self.clock.now(), {}
        rows = self.repository.quotes(sport)
        # Enforce the intersection at read time as well: filters must never turn
        # a Bet365-only prop into a supported one, including during an outage.
        support = {
            (q.event_id, q.market, q.period, q.player_id, q.point, q.alternate, q.name)
            for row in rows
            if row["book_key"] != "bet365"
            and (q := row["quote"]).player_id is not None
            and q.state == Availability.AVAILABLE
            and (now - q.collected_at).total_seconds() <= max(self.collected_ttl, self.props_cache_ttl)
            and (
                q.source_updated_at is None or (now - q.source_updated_at).total_seconds() <= self.source_ttl
            )
            and (q.expires_at is None or q.expires_at > now)
        }
        for row in rows:
            q = row["quote"]
            event = events[q.event_id]
            if row["book_key"] == "bet365":
                if event["status"] != "pregame" or event["start"] <= now:
                    continue
                if (
                    q.player_id is not None
                    and (q.event_id, q.market, q.period, q.player_id, q.point, q.alternate, q.name)
                    not in support
                ):
                    continue
            if event_id is not None and q.event_id != event_id:
                continue
            if event["status"] in {"final", "cancelled", "unknown"}:
                continue
            if (start and event["start"] < start) or (end and event["start"] > end):
                continue
            if (market_set and q.market not in market_set) or (book_set and row["book_key"] not in book_set):
                continue
            availability = q.availability(
                now,
                self.bet365_collected_ttl if row["book_key"] == "bet365" else self.collected_ttl,
                self.source_ttl,
            )
            age = max(0, (now - q.collected_at).total_seconds())
            cached_prop = (
                not fresh_only
                and q.player_id is not None
                and q.state == Availability.AVAILABLE
                and availability == Availability.STALE
                and age <= self.props_cache_ttl
                and self.props_cache_ttl > 0
                and (
                    q.source_updated_at is None
                    or (now - q.source_updated_at).total_seconds() <= self.source_ttl
                )
                and (q.expires_at is None or now < q.expires_at)
            )
            if availability != Availability.AVAILABLE and not cached_prop:
                continue
            book = grouped.setdefault(q.event_id, {}).setdefault(
                row["book_key"],
                {"key": row["book_key"], "title": row["book_title"], "last_update": None, "markets": {}},
            )
            market = book["markets"].setdefault(
                q.market, {"key": q.market, "last_update": None, "outcomes": []}
            )
            # Null source times stay null. Collection time is available in /status.
            if q.source_updated_at:
                for obj in (book, market):
                    obj["last_update"] = max(filter(None, (obj["last_update"], q.source_updated_at)))
            outcome = {
                "name": q.name,
                "price": q.price
                if odds_format == "american"
                else float(decimal_odds(q.price).quantize(Decimal("0.0001"))),
            }
            if q.point is not None:
                outcome["point"] = float(q.point)
            if q.description:
                outcome["description"] = q.description
            if q.player_id is not None:
                outcome["freshness"] = {
                    "status": "stale" if cached_prop else "fresh",
                    "actionable": not cached_prop,
                    "collected_at": q.collected_at,
                    "source_updated_at": q.source_updated_at,
                    "expires_at": q.expires_at,
                    "age_seconds": round(age, 3),
                }
            if outcome not in market["outcomes"]:
                market["outcomes"].append(outcome)
        result = []
        for eid in sorted(grouped, key=lambda k: (events[k]["start"], k)):
            payload = self.event_payload(events[eid])
            payload["bookmakers"] = []
            for key in sorted(grouped[eid]):
                book = grouped[eid][key]
                book["markets"] = [book["markets"][k] for k in sorted(book["markets"])]
                for market in book["markets"]:
                    market["outcomes"].sort(
                        key=lambda o: (o.get("description", ""), o.get("point", 0), o["name"])
                    )
                payload["bookmakers"].append(book)
            if prop_query:
                payload["freshness"] = self.freshness(payload, now)
            result.append(payload)
        if event_id:
            if result:
                return result[0]
            payload = {**self.event_payload(events[event_id]), "bookmakers": []}
            if prop_query:
                payload["freshness"] = self.freshness(payload, now)
            return payload
        return result

    def freshness(self, payload, now):
        outcomes = [o for b in payload["bookmakers"] for m in b["markets"] for o in m["outcomes"]]
        stale = sum(o.get("freshness", {}).get("status") == "stale" for o in outcomes)
        fresh = len(outcomes) - stale
        return {
            "observed_at": now,
            "status": "mixed"
            if fresh and stale
            else "stale"
            if stale
            else "fresh"
            if fresh
            else "unavailable",
            "fresh_outcomes": fresh,
            "stale_outcomes": stale,
            "max_cache_age_seconds": self.props_cache_ttl,
        }
