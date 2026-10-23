from datetime import UTC, datetime, timedelta

from sqlalchemy import MetaData, create_engine, delete, event, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from odds_api.domain.models import Availability, League, Quote


def aware(value):
    # SQLite loses TZ offsets; this repository writes UTC only.
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class SqlRepository:
    def __init__(self, url, league_config, retention=0):
        kwargs = (
            {"connect_args": {"check_same_thread": False, "timeout": 30}}
            if url.startswith("sqlite")
            else {"connect_args": {"options": "-c max_parallel_workers_per_gather=0"}}
        )
        self.engine = create_engine(url, pool_pre_ping=True, **kwargs)
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def sqlite_setup(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")

        self.metadata = MetaData()
        self.metadata.reflect(self.engine)
        self.t = self.metadata.tables
        required = {
            "leagues",
            "events",
            "books",
            "markets",
            "selections",
            "odds",
            "scopes",
            "snapshots",
            "collector",
        }
        if not required.issubset(self.t):
            self.engine.dispose()
            raise RuntimeError("Database schema missing: run alembic upgrade head")
        self.retention = retention
        with self.engine.begin() as conn:
            for key, cfg in league_config.items():
                self.upsert(conn, "leagues", {"key": key, "title": cfg["title"], "route": cfg["route"]})
                for kind in ("moneyline", "props"):
                    stmt = self.insert(self.t["scopes"]).values(league=key, kind=kind, warnings=[])
                    conn.execute(stmt.on_conflict_do_nothing())
        self.configured = set(league_config)

    def insert(self, table):
        return (sqlite_insert if self.engine.dialect.name == "sqlite" else pg_insert)(table)

    def upsert(self, conn, name, data):
        self.upsert_many(conn, name, [data])

    def upsert_many(self, conn, name, rows):
        if not rows:
            return
        table = self.t[name]
        keys = [c.name for c in table.primary_key]
        for offset in range(0, len(rows), 500):
            batch = rows[offset : offset + 500]
            stmt = self.insert(table).values(batch)
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=keys, set_={key: stmt.excluded[key] for key in batch[0] if key not in keys}
                )
            )

    def save(self, board):
        t, league = self.t, board.league
        with self.engine.begin() as conn:
            # Serialize both scopes of one league so event lifecycle updates cannot race.
            if self.engine.dialect.name == "postgresql":
                conn.execute(select(t["leagues"]).where(t["leagues"].c.key == league.key).with_for_update())
            if board.provider == "unabated":
                self.upsert(conn, "leagues", vars(league))
            self.upsert_many(
                conn,
                "events",
                [
                    {
                        "id": e.id,
                        "source_id": e.source_id,
                        "league_key": e.league_key,
                        "start": e.start,
                        "home": e.home,
                        "away": e.away,
                        "status": e.status,
                    }
                    for e in board.events
                    if board.provider == "unabated"
                ],
            )
            self.upsert_many(
                conn,
                "books",
                [
                    {"id": book.id, "source_id": book.source_id, "key": book.key, "title": book.title}
                    for book in board.books
                ],
            )
            scope = (
                select(t["selections"].c.id)
                .select_from(
                    t["selections"]
                    .join(t["markets"])
                    .join(t["events"])
                    .join(t["books"], t["markets"].c.book_id == t["books"].c.id)
                )
                .where(t["events"].c.league_key == league.key, t["markets"].c.kind == board.kind)
            )
            scope = scope.where(
                t["books"].c.key == "bet365" if board.provider == "bet365" else t["books"].c.key != "bet365"
            )
            if board.provider == "bet365":
                scope = scope.where(t["markets"].c.type.in_(board.covered_markets))
            if board.complete:
                conn.execute(
                    update(t["odds"]).where(t["odds"].c.selection_id.in_(scope)).values(state="removed")
                )
            markets, selections, prices = {}, {}, {}
            # The league lock makes the intersection check atomic with other refreshes.
            supported = (
                self._supported_bet365(
                    conn, league.key, {self.prop_identity(q) for q in board.quotes if q.player_id}
                )
                if board.provider == "bet365"
                else None
            )
            canonical_events = None
            if board.provider == "bet365":
                canonical_events = set(
                    conn.execute(
                        select(t["events"].c.id).where(
                            t["events"].c.league_key == league.key,
                            t["events"].c.status == "pregame",
                            t["events"].c.start > board.collected_at,
                        )
                    ).scalars()
                )
            for q in board.quotes:
                if canonical_events is not None and q.event_id not in canonical_events:
                    continue
                if (
                    supported is not None
                    and self.prop_identity(q) not in supported
                    and q.player_id is not None
                ):
                    continue
                markets[q.market_id] = {
                    "id": q.market_id,
                    "event_id": q.event_id,
                    "book_id": q.book_id,
                    "kind": board.kind,
                    "type": q.market,
                    "period": q.period,
                    "player_id": q.player_id,
                    "point": q.point,
                    "alternate": q.alternate,
                    "source_id": q.source_market_id,
                }
                selections[q.selection_id] = {
                    "id": q.selection_id,
                    "market_id": q.market_id,
                    "name": q.name,
                    "description": q.description,
                    "source_id": q.source_selection_id,
                    "source_market_id": q.source_market_id,
                }
                prices[q.selection_id] = {
                    "selection_id": q.selection_id,
                    "price": q.price,
                    "state": q.state.value,
                    "collected_at": q.collected_at,
                    "source_updated_at": q.source_updated_at,
                    "expires_at": q.expires_at,
                    "deep_link": q.deep_link,
                }
            self.upsert_many(conn, "markets", list(markets.values()))
            self.upsert_many(conn, "selections", list(selections.values()))
            self.upsert_many(conn, "odds", list(prices.values()))
            changes = {
                "last_attempt": board.collected_at,
                "outcome": "partial" if not board.complete else ("success" if board.quotes else "empty"),
                "selection_count": len(board.quotes),
                "warnings": list(board.warnings),
            }
            if board.complete:
                changes["last_success"] = board.collected_at
            if board.provider == "unabated":
                conn.execute(
                    update(t["scopes"])
                    .where(t["scopes"].c.league == league.key, t["scopes"].c.kind == board.kind)
                    .values(**changes)
                )
            self._remove_unsupported_bet365(conn, league.key)
            if self.retention:
                # Domain snapshots; no credentials or upstream envelopes.
                payload = [
                    {
                        "id": q.selection_id,
                        "price": q.price,
                        "state": q.state.value,
                        "point": str(q.point) if q.point is not None else None,
                        "source_updated_at": q.source_updated_at.isoformat() if q.source_updated_at else None,
                    }
                    for q in board.quotes
                ]
                conn.execute(
                    t["snapshots"]
                    .insert()
                    .values(
                        league=league.key, kind=board.kind, collected_at=board.collected_at, payload=payload
                    )
                )
                conn.execute(
                    delete(t["snapshots"]).where(
                        t["snapshots"].c.collected_at < board.collected_at - timedelta(days=self.retention)
                    )
                )

    @staticmethod
    def prop_identity(q):
        return (q.event_id, q.market, q.period, q.player_id, q.point, q.alternate, q.name)

    def _supported_bet365(self, conn, league, candidates):
        if not candidates:
            return set()
        m, s, o, e, b = (self.t[k] for k in ("markets", "selections", "odds", "events", "books"))
        rows = conn.execute(
            select(m.c.event_id, m.c.type, m.c.period, m.c.player_id, m.c.point, m.c.alternate, s.c.name)
            .select_from(m.join(s).join(o).join(e, m.c.event_id == e.c.id).join(b, m.c.book_id == b.c.id))
            .where(
                e.c.league_key == league,
                b.c.key != "bet365",
                o.c.state == "available",
                m.c.player_id.is_not(None),
                m.c.event_id.in_({q[0] for q in candidates}),
                m.c.type.in_({q[1] for q in candidates}),
                m.c.player_id.in_({q[3] for q in candidates}),
                m.c.point.in_({q[4] for q in candidates}),
            )
        )
        return {tuple(row) for row in rows}

    def _remove_unsupported_bet365(self, conn, league):
        m, s, o, e, b = (self.t[k] for k in ("markets", "selections", "odds", "events", "books"))
        rows = conn.execute(
            select(
                s.c.id, m.c.event_id, m.c.type, m.c.period, m.c.player_id, m.c.point, m.c.alternate, s.c.name
            )
            .select_from(m.join(s).join(o).join(e, m.c.event_id == e.c.id).join(b, m.c.book_id == b.c.id))
            .where(
                e.c.league_key == league,
                b.c.key == "bet365",
                m.c.player_id.is_not(None),
                o.c.state != "removed",
            )
        ).all()
        if not rows:
            return
        supported = self._supported_bet365(conn, league, {tuple(row[1:]) for row in rows})
        unsupported = [row[0] for row in rows if tuple(row[1:]) not in supported]
        for offset in range(0, len(unsupported), 500):
            conn.execute(
                update(o)
                .where(o.c.selection_id.in_(unsupported[offset : offset + 500]))
                .values(state="removed")
            )

    def failure(self, league, kind, outcome):
        t = self.t["scopes"]
        with self.engine.begin() as conn:
            conn.execute(
                update(t)
                .where(t.c.league == league, t.c.kind == kind)
                .values(last_attempt=datetime.now(UTC), outcome=outcome, failures=t.c.failures + 1)
            )

    def missed(self, league, kind, count, lag):
        t = self.t["scopes"]
        with self.engine.begin() as conn:
            conn.execute(
                update(t)
                .where(t.c.league == league, t.c.kind == kind)
                .values(missed_deadlines=t.c.missed_deadlines + count, scheduling_lag=lag)
            )

    def leagues(self):
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(self.t["leagues"])
                .where(self.t["leagues"].c.key.in_(self.configured))
                .order_by(self.t["leagues"].c.key)
            ).mappings()
            return [League(**dict(r)) for r in rows]

    def events(self, sport):
        e, league = self.t["events"], self.t["leagues"]
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(e, league.c.title.label("sport_title"))
                .join(league)
                .where(e.c.league_key == sport)
                .order_by(e.c.start, e.c.id)
            ).mappings()
            return [{**dict(r), "start": aware(r["start"])} for r in rows]

    def quotes(self, sport):
        m, s, o, e, b = (self.t[k] for k in ("markets", "selections", "odds", "events", "books"))
        stmt = (
            select(
                m,
                s.c.name,
                s.c.description,
                s.c.source_id.label("selection_source_id"),
                s.c.source_market_id.label("selection_market_source_id"),
                o.c.price,
                o.c.state,
                o.c.collected_at,
                o.c.source_updated_at,
                o.c.expires_at,
                o.c.deep_link,
                b.c.key.label("book_key"),
                b.c.title.label("book_title"),
            )
            .select_from(m.join(s).join(o).join(e, m.c.event_id == e.c.id).join(b, m.c.book_id == b.c.id))
            .where(e.c.league_key == sport)
        )
        with self.engine.connect() as conn:
            return self._quote_rows(conn.execute(stmt).mappings())

    @staticmethod
    def _quote_rows(rows):
        result = []
        for r in rows:
            q = Quote(
                r["event_id"],
                r["book_id"],
                r["type"],
                r["period"],
                r["player_id"],
                r["point"],
                r["alternate"],
                r["name"],
                r["description"],
                r["selection_market_source_id"],
                r["selection_source_id"],
                r["price"],
                Availability(r["state"]),
                aware(r["collected_at"]),
                aware(r["source_updated_at"]),
                aware(r["expires_at"]),
                r["deep_link"],
            )
            result.append({"quote": q, "book_key": r["book_key"], "book_title": r["book_title"]})
        return result

    def bookmakers(self):
        with self.engine.connect() as conn:
            return set(conn.execute(select(self.t["books"].c.key)).scalars())

    def heartbeat(self, now, metrics):
        with self.engine.begin() as conn:
            self.upsert(conn, "collector", {"id": 1, "heartbeat": now, "metrics": dict(metrics)})

    def status(self, now, collected_ttl, source_ttl):
        with self.engine.connect() as conn:
            scopes = [
                {
                    **dict(r),
                    "last_success": aware(r["last_success"]),
                    "last_attempt": aware(r["last_attempt"]),
                }
                for r in conn.execute(
                    select(self.t["scopes"]).where(self.t["scopes"].c.league.in_(self.configured))
                ).mappings()
            ]
            counts = {
                name: conn.execute(select(func.count()).select_from(self.t[name])).scalar_one()
                for name in ("events", "markets", "selections")
            }
            collector = conn.execute(select(self.t["collector"])).mappings().first()
        stale = sum(
            row["quote"].availability(now, collected_ttl, source_ttl) == Availability.STALE
            for sport in self.configured
            for row in self.quotes(sport)
        )
        heartbeat = aware(collector["heartbeat"]) if collector else None
        healthy = bool(heartbeat and now - heartbeat < timedelta(seconds=10))
        return {
            "service": "ok",
            "collector_healthy": healthy,
            "collector_heartbeat": heartbeat,
            "provider_metrics": collector["metrics"] if collector else {},
            "scopes": scopes,
            "counts": counts,
            "stale_quotes": stale,
            "observed_at": now,
        }

    def ready(self):
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                return version == "0001"
        except Exception:
            return False

    def close(self):
        self.engine.dispose()
