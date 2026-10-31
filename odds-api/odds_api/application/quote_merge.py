"""Choose updates per public sportsbook selection, preserving absent peers."""

import re
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal

from odds_api.domain.models import Availability
from odds_api.domain.sportsbooks import sportsbook_key


def time_value(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def name_key(value):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", value).casefold())


def selection_key(row):
    q = row["quote"]
    point = Decimal(str(q["point"])).normalize() if q["point"] is not None else None
    return (
        q["event_id"],
        sportsbook_key(row["book_key"], row["book_title"]),
        q["market"],
        q["period"],
        name_key(q["description"]) if q["description"] else q["player_id"],
        point,
        q["alternate"],
        name_key(q["name"]),
    )


def fresh(quote, now, ttl, source_ttl):
    collected, source, expiry = (
        time_value(quote[k]) for k in ("collected_at", "source_updated_at", "expires_at")
    )
    return (
        (now - collected).total_seconds() <= ttl
        and collected <= now + timedelta(seconds=5)
        and (source is None or -5 <= (now - source).total_seconds() <= source_ttl)
        and (expiry is None or expiry > now)
    )


def select_public_quotes(rows, now, collected_ttl, source_ttl, propline_collected_ttl):
    """Keep one valid last-known price per selection; only fresh observations replace it.

    Provider storage IDs remain distinct. Public identity uses the sportsbook and
    the player's name so a PropLine player ID need not match an Unabated ID.
    """
    selected = {}
    for row in sorted(rows, key=lambda r: (time_value(r["quote"]["collected_at"]), r["book_key"])):
        quote = row["quote"]
        if quote["state"] != Availability.AVAILABLE or quote["price"] is None:
            continue
        key = selection_key(row)
        previous = selected.get(key)
        if previous is not None:
            prior = previous["quote"]
            ttl = propline_collected_ttl if row["book_key"].startswith("propline_") else collected_ttl
            source, old_source = (
                time_value(quote["source_updated_at"]),
                time_value(prior["source_updated_at"]),
            )
            collected = time_value(quote["collected_at"])
            # Eligibility is measured when downloaded. A winning quote stays
            # the winner after aging; it must never revert to an older price.
            if collected > now + timedelta(seconds=5) or not fresh(quote, collected, ttl, source_ttl):
                continue
            if old_source is not None and (source is None or source < old_source):
                continue
            if time_value(quote["collected_at"]) == time_value(prior["collected_at"]):
                if source is None or (old_source is not None and source <= old_source):
                    continue
        selected[key] = row
    return list(selected.values())
