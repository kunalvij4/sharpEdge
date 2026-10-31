"""Prepare event responses at collection time, retaining private merge metadata."""

from datetime import datetime
from decimal import Decimal

from odds_api.domain.models import Availability, decimal_odds
from odds_api.domain.sportsbooks import sportsbook_key

QUOTE_METADATA_FIELDS = (
    "period",
    "player_id",
    "point",
    "alternate",
    "source_market_id",
    "source_selection_id",
    "price",
    "state",
    "deep_link",
)
QUOTE_TIMES = ("collected_at", "source_updated_at", "expires_at")


def time_value(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def wire_time(value):
    value = time_value(value)
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def stored_event(document):
    return document["_storage"]["event"] if "_storage" in document else document["event"]


def stored_rows(document):
    if "quotes" in document:
        yield from document["quotes"].items()
        return
    for book in document["bookmakers"]:
        for market in book["markets"]:
            for outcome in market["outcomes"]:
                metadata = outcome["_storage"]
                quote = {key: metadata[key] for key in QUOTE_METADATA_FIELDS}
                times = outcome.get("freshness", metadata)
                quote.update({key: times[key] for key in QUOTE_TIMES})
                quote.update(
                    event_id=document["id"],
                    book_id=book["_storage"]["id"],
                    market=market["key"],
                    name=outcome["name"],
                    description=outcome.get("description", metadata.get("description")),
                )
                yield (
                    metadata["selection_id"],
                    {
                        "quote": quote,
                        "book_key": book["key"],
                        "book_title": book["title"],
                    },
                )


def quote_freshness(quote, now, collected_ttl, source_ttl):
    collected = time_value(quote["collected_at"])
    source = time_value(quote["source_updated_at"])
    expiry = time_value(quote["expires_at"])
    age = max(0, (now - collected).total_seconds())
    source_valid = (source is None or (now - source).total_seconds() <= source_ttl) and (
        expiry is None or expiry > now
    )
    fresh = (now - collected).total_seconds() <= collected_ttl and source_valid
    return age, source_valid, fresh


def prepare_document(event, rows, now, collected_ttl, source_ttl, propline_collected_ttl):
    """Store the public hierarchy once; private metadata preserves exact quote identities."""
    document = {
        "id": event["id"],
        "sport_key": event["league_key"],
        "sport_title": event["sport_title"],
        "commence_time": wire_time(event["start"]),
        "home_team": event["home"],
        "away_team": event["away"],
        "bookmakers": [],
        "_storage": {"version": 2, "event": event},
    }
    books = {}
    for selection_id, row in rows.items():
        quote = row["quote"]
        book = books.setdefault(
            row["book_key"],
            {
                "key": row["book_key"],
                "title": row["book_title"],
                "last_update": None,
                "markets": {},
                "_storage": {"id": quote["book_id"]},
            },
        )
        market = book["markets"].setdefault(
            quote["market"], {"key": quote["market"], "last_update": None, "outcomes": []}
        )
        source_time = time_value(quote["source_updated_at"])
        source = wire_time(source_time)
        if source is not None:
            for item in (book, market):
                item["last_update"] = max(filter(None, (item["last_update"], source_time)))
        outcome = {
            "name": quote["name"],
            "price": float(decimal_odds(quote["price"]).quantize(Decimal("0.0001")))
            if quote["price"] is not None
            else None,
        }
        if quote["point"] is not None:
            outcome["point"] = float(quote["point"])
        if quote["description"]:
            outcome["description"] = quote["description"]
        if quote["player_id"] is not None:
            ttl = propline_collected_ttl if row["book_key"].startswith("propline_") else collected_ttl
            age, _, fresh = quote_freshness(quote, now, ttl, source_ttl)
            outcome["freshness"] = {
                "status": "fresh" if fresh else "stale",
                "actionable": fresh and quote["state"] == Availability.AVAILABLE,
                "collected_at": wire_time(quote["collected_at"]),
                "source_updated_at": source,
                "expires_at": wire_time(quote["expires_at"]),
                "age_seconds": round(age, 3),
            }
        # Keep only fields absent from (or rounded in) the public outcome. The
        # canonical quote can be restored without storing a second full copy.
        metadata = {key: quote[key] for key in QUOTE_METADATA_FIELDS}
        metadata["selection_id"] = selection_id
        if "freshness" not in outcome:
            metadata.update({key: quote[key] for key in QUOTE_TIMES})
        if quote["description"] is not None and "description" not in outcome:
            metadata["description"] = quote["description"]
        outcome["_storage"] = metadata
        market["outcomes"].append(outcome)
    for key in sorted(books):
        book = books[key]
        book["last_update"] = wire_time(book["last_update"])
        book["markets"] = [book["markets"][key] for key in sorted(book["markets"])]
        for market in book["markets"]:
            market["last_update"] = wire_time(market["last_update"])
            market["outcomes"].sort(key=lambda o: (o.get("description", ""), o.get("point", 0), o["name"]))
        document["bookmakers"].append(book)
    return document


def project_response(
    document,
    *,
    now,
    markets,
    bookmakers,
    odds_format,
    start,
    end,
    fresh_only,
    collected_ttl,
    source_ttl,
    props_cache_ttl,
    propline_collected_ttl,
):
    """Filter prepared JSON without rebuilding domain quotes or grouping prices."""
    payload = {key: value for key, value in document.items() if key not in {"_storage", "bookmakers"}}
    payload["bookmakers"] = []
    event = stored_event(document)
    commence = time_value(event["start"])
    if (
        event["status"] in {"final", "cancelled", "unknown"}
        or (start and commence < start)
        or (end and commence > end)
    ):
        return payload
    # Storage stays provider-scoped. Merge only the public hierarchy so a later
    # collection cannot reinterpret another feed's quote as its own.
    public_books = {}
    for stored_book in document["bookmakers"]:
        public_key = sportsbook_key(stored_book["key"], stored_book["title"])
        if bookmakers and public_key not in bookmakers:
            continue
        book = {"key": public_key, "title": stored_book["title"], "last_update": None, "markets": []}
        ttl = propline_collected_ttl if stored_book["key"].startswith("propline_") else collected_ttl
        for stored_market in stored_book["markets"]:
            if markets and stored_market["key"] not in markets:
                continue
            market = {"key": stored_market["key"], "last_update": None, "outcomes": []}
            seen = set()
            for stored_outcome in stored_market["outcomes"]:
                quote = stored_outcome["_storage"]
                if quote["state"] != Availability.AVAILABLE:
                    continue
                times = stored_outcome.get("freshness", quote)
                age, source_valid, fresh = quote_freshness(times, now, ttl, source_ttl)
                cached = (
                    not fresh_only
                    and quote["player_id"] is not None
                    and source_valid
                    and props_cache_ttl > 0
                    and age <= props_cache_ttl
                )
                if not fresh and not cached:
                    continue
                outcome = {key: value for key, value in stored_outcome.items() if key != "_storage"}
                if odds_format == "american":
                    outcome["price"] = quote["price"]
                if "freshness" in outcome:
                    outcome["freshness"] = {
                        **outcome["freshness"],
                        "status": "fresh" if fresh else "stale",
                        "actionable": fresh,
                        "age_seconds": round(age, 3),
                    }
                signature = (
                    outcome["name"],
                    outcome["price"],
                    outcome.get("point"),
                    outcome.get("description"),
                    tuple(outcome.get("freshness", {}).items()),
                )
                if signature not in seen:
                    seen.add(signature)
                    market["outcomes"].append(outcome)
                source = time_value(times["source_updated_at"])
                if source is not None:
                    for item in (book, market):
                        item["last_update"] = max(filter(None, (item["last_update"], source)))
            if market["outcomes"]:
                market["last_update"] = wire_time(market["last_update"])
                book["markets"].append(market)
        if book["markets"]:
            book["last_update"] = wire_time(book["last_update"])
            existing = public_books.setdefault(public_key, book)
            if existing is not book:
                updates = [time_value(b["last_update"]) for b in (existing, book) if b["last_update"]]
                existing["last_update"] = wire_time(max(updates)) if updates else None
                by_market = {m["key"]: m for m in existing["markets"]}
                for market in book["markets"]:
                    prior = by_market.get(market["key"])
                    if prior is None:
                        existing["markets"].append(market)
                        continue
                    updates = [time_value(m["last_update"]) for m in (prior, market) if m["last_update"]]
                    prior["last_update"] = wire_time(max(updates)) if updates else None
                    for outcome in market["outcomes"]:
                        if outcome not in prior["outcomes"]:
                            prior["outcomes"].append(outcome)
    payload["bookmakers"] = [public_books[key] for key in sorted(public_books)]
    for book in payload["bookmakers"]:
        book["markets"].sort(key=lambda m: m["key"])
        for market in book["markets"]:
            market["outcomes"].sort(key=lambda o: (o.get("description", ""), o.get("point", 0), o["name"]))
    return payload
