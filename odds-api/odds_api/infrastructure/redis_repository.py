"""Redis event documents, atomically refreshed and expired at kickoff."""

import base64
import json
import zlib
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import batched

from redis import Redis, WatchError

from odds_api.domain.models import Availability, League, Quote
from odds_api.infrastructure.clock import SystemClock
from odds_api.infrastructure.repository import SqlRepository

DOCUMENT_PREFIX = "zlib:1:"
SHRINK_DOCUMENT = """#!lua flags=allow-oom
local current = redis.call('GET', KEYS[1])
if not current or current ~= ARGV[1] then return 0 end
if #ARGV[2] >= #current or string.sub(ARGV[2], 1, 7) ~= 'zlib:1:' then return -1 end
redis.call('SET', KEYS[1], ARGV[2], 'KEEPTTL')
return 1
"""


def encode(value):
    return json.dumps(value, default=str, separators=(",", ":"))


def compress_document(raw):
    packed = DOCUMENT_PREFIX + base64.b64encode(zlib.compress(raw.encode(), level=1)).decode("ascii")
    return packed if len(packed) < len(raw.encode()) else raw


def decode_document(value):
    if value.startswith(DOCUMENT_PREFIX):
        value = zlib.decompress(base64.b64decode(value[len(DOCUMENT_PREFIX) :]))
    return json.loads(value)


def decode_quote(data):
    data = dict(data)
    for key in ("collected_at", "source_updated_at", "expires_at"):
        data[key] = datetime.fromisoformat(data[key]) if data[key] else None
    data["point"] = Decimal(data["point"]) if data["point"] is not None else None
    data["state"] = Availability(data["state"])
    return Quote(**data)


class RedisRepository:
    _valid_replacement = SqlRepository._valid_replacement

    def __init__(
        self,
        url,
        league_config,
        retention=0,
        clock=None,
        *,
        collected_ttl=600,
        source_ttl=3600,
        propline_collected_ttl=600,
        prefix="sharpedge:odds:v1",
        client=None,
    ):
        self.client = (
            client
            if client is not None
            else Redis.from_url(
                url,
                decode_responses=True,
                socket_timeout=10,
                socket_connect_timeout=10,
            )
        )
        self.clock = clock or SystemClock()
        self.configured = league_config
        self.prefix = prefix
        self.collected_ttl, self.source_ttl = collected_ttl, source_ttl
        self.propline_collected_ttl = propline_collected_ttl

    def key(self, suffix):
        return self.prefix + ":" + suffix

    def leagues(self):
        return [
            League(key, cfg["title"], cfg["route"], cfg.get("source_id", ""))
            for key, cfg in sorted(self.configured.items())
        ]

    def save(self, board):
        if board.provider == "bet365":
            raise ValueError("Redis collection supports Propline and Unabated only")
        books = {book.id: book for book in board.books}
        grouped = {}
        for quote in board.quotes:
            grouped.setdefault(quote.event_id, []).append(quote)
        for batch in batched(board.events, 16):
            keys = [self.key("event:" + event.id) for event in batch]
            # One bounded transaction avoids three network round trips per event.
            # Watching every key preserves concurrent updates to either provider.
            while True:
                with self.client.pipeline() as pipe:
                    try:
                        pipe.watch(*keys)
                        previous_values = pipe.mget(keys)
                        now = self.clock.now()
                        documents = []
                        for event, old in zip(batch, previous_values):
                            if event.start <= now:
                                documents.append(None)
                                continue
                            document = decode_document(old) if old else {"quotes": {}}
                            document["event"] = {
                                **asdict(event),
                                "id": event.id,
                                "sport_title": board.league.title,
                            }
                            for quote in grouped.get(event.id, []):
                                selection_id = quote.selection_id
                                previous = document["quotes"].get(selection_id)
                                if previous and not self._valid_replacement(
                                    quote, asdict(decode_quote(previous["quote"])), now, board.provider
                                ):
                                    continue
                                book = books[quote.book_id]
                                document["quotes"][selection_id] = {
                                    "quote": asdict(quote),
                                    "book_key": book.key,
                                    "book_title": book.title,
                                }
                            documents.append(compress_document(encode(document)))
                        pipe.multi()
                        for key, event, document in zip(keys, batch, documents):
                            if document is None:
                                pipe.delete(key)
                                continue
                            pipe.set(key, document)
                            pipe.pexpireat(key, int(event.start.timestamp() * 1000))
                            pipe.zadd(
                                self.key("events:" + board.league.key), {event.id: event.start.timestamp()}
                            )
                        pipe.execute()
                        break
                    except WatchError:
                        continue

    def _documents(self, sport, event_id=None):
        if sport not in self.configured:
            return []
        ids = (
            [event_id]
            if event_id
            else self.client.zrangebyscore(
                self.key("events:" + sport), "(" + str(self.clock.now().timestamp()), "+inf"
            )
        )
        if not ids:
            return []
        # Batch event reads to avoid one network round-trip per event.
        with self.client.pipeline(transaction=False) as pipe:
            for eid in ids:
                pipe.get(self.key("event:" + eid))
            values = pipe.execute()
        return [
            doc
            for value in values
            if value and (doc := decode_document(value))["event"]["league_key"] == sport
        ]

    @staticmethod
    def _event(document):
        event = document["event"]
        return {**event, "start": datetime.fromisoformat(event["start"])}

    def events(self, sport):
        return sorted(
            (self._event(doc) for doc in self._documents(sport)),
            key=lambda event: (event["start"], event["id"]),
        )

    def event(self, event_id):
        value = self.client.get(self.key("event:" + event_id))
        if not value:
            return None
        event = self._event(decode_document(value))
        return event if event["league_key"] in self.configured and event["start"] > self.clock.now() else None

    def quotes(self, sport, event_id=None, now=None):
        return [
            {**row, "quote": decode_quote(row["quote"])}
            for doc in self._documents(sport, event_id)
            if self._event(doc)["start"] > (now or self.clock.now())
            for row in doc["quotes"].values()
        ]

    def bookmakers(self):
        return {row["book_key"] for sport in self.configured for row in self.quotes(sport)}

    def prune_started(self):
        return sum(
            self.client.zremrangebyscore(self.key("events:" + sport), "-inf", self.clock.now().timestamp())
            for sport in self.configured
        )

    def heartbeat(self, now, metrics):
        self.client.set(self.key("collector"), encode({"heartbeat": now, "metrics": dict(metrics)}))

    def compact_event_documents(self):
        counts = {"compressed_events": 0, "bytes_before": 0, "bytes_after": 0}
        for keys in batched(self.client.scan_iter(match=self.key("event:*"), count=100), 16):
            for key, value in zip(keys, self.client.mget(keys)):
                if not value or value.startswith(DOCUMENT_PREFIX):
                    continue
                # Validate legacy documents before preserving their exact JSON bytes.
                decode_document(value)
                packed = compress_document(value)
                if packed == value:
                    continue
                # The script can recover an already-full Redis, but only by shrinking
                # an unchanged value. It preserves TTL and never deletes a quote/key.
                result = self.client.eval(SHRINK_DOCUMENT, 1, key, value, packed)
                if result == 1:
                    counts["compressed_events"] += 1
                    counts["bytes_before"] += len(value.encode())
                    counts["bytes_after"] += len(packed)
        return counts

    def status(self, now, collected_ttl, source_ttl, propline_collected_ttl=600):
        collector = json.loads(self.client.get(self.key("collector")) or "{}")
        heartbeat = datetime.fromisoformat(collector["heartbeat"]) if collector else None
        rows = [row for sport in self.configured for row in self.quotes(sport)]
        return {
            "service": "ok",
            "collector_healthy": bool(heartbeat and now - heartbeat < timedelta(seconds=10)),
            "collector_heartbeat": heartbeat,
            "provider_metrics": collector.get("metrics", {}),
            "scopes": [],
            "counts": {
                "events": sum(len(self.events(s)) for s in self.configured),
                "markets": len({r["quote"].market_id for r in rows}),
                "selections": len(rows),
            },
            "stale_quotes": sum(
                r["quote"].availability(
                    now,
                    propline_collected_ttl if r["book_key"].startswith("propline_") else collected_ttl,
                    source_ttl,
                )
                == Availability.STALE
                for r in rows
            ),
            "observed_at": now,
        }

    def failure(self, league, kind, outcome):
        self.client.hset(self.key("failures"), league + ":" + kind, outcome)

    def ready(self):
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    def close(self):
        self.client.close()
