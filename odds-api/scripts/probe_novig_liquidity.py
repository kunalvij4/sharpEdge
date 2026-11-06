"""Read-only comparison of Novig's public order books with our player prop quotes."""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


NOVIG_URL = "https://api.novig.com"
LEAGUES = {"NBA": "nba_basketball", "NCAAB": "ncaab_basketball"}
PROP_TYPES = {
    "POINTS": "player_points",
    "REBOUNDS": "player_rebounds",
    "ASSISTS": "player_assists",
    "THREES": "player_threes",
    "STEALS": "player_steals",
    "BLOCKS": "player_blocks",
    "TURNOVERS": "player_turnovers",
    "POINTS_REBOUNDS_ASSISTS": "player_points_rebounds_assists",
    "POINTS_REBOUNDS": "player_points_rebounds",
    "POINTS_ASSISTS": "player_points_assists",
    "REBOUNDS_ASSISTS": "player_rebounds_assists",
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_json(url, headers=None):
    request = Request(url, headers={"Accept": "application/json", **(headers or {})})
    with build_opener(NoRedirect).open(request, timeout=30) as response:
        return json.load(response)


def read_settings(path):
    values = {}
    if path:
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in {"ODDS_API_BASE_URL", "ODDS_API_KEY"}:
                values[key.strip()] = value.strip().strip("\"'")
    return {key: os.environ.get(key, values.get(key, "")) for key in ("ODDS_API_BASE_URL", "ODDS_API_KEY")}


def key(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def decimal(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def paged(get, path, params, max_pages):
    cursor = None
    seen = set()
    for _ in range(max_pages):
        query = dict(params, limit=500)
        if cursor:
            query["after"] = cursor
        data = get(path + "?" + urlencode(query))
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError(f"Invalid Novig catalog response: {path}")
        yield from data["items"]
        cursor = data.get("next")
        if not cursor:
            return
        if cursor in seen:
            raise ValueError("Novig catalog returned a repeated pagination cursor")
        seen.add(cursor)
    raise ValueError(f"Novig catalog exceeded the {max_pages}-page safety limit")


def match_events(our_events, novig_events):
    """Only accept a unique exact team-name pair with a close start time."""
    matches = {}
    for event in our_events:
        start = timestamp(event.get("commence_time"))
        if start is None:
            continue
        wanted = (key(event.get("away_team", "")), key(event.get("home_team", "")))
        if not all(wanted):
            continue
        candidates = []
        for other in novig_events:
            parts = other.get("description", "").split(" @ ")
            milliseconds = other.get("startsTs")
            if len(parts) != 2 or not isinstance(milliseconds, (int, float)):
                continue
            if tuple(key(part) for part in parts) == wanted and abs(start.timestamp() - milliseconds / 1000) <= 900:
                candidates.append(other)
        if len(candidates) == 1:
            matches[event["id"]] = candidates[0]
    counts = Counter(match["eventId"] for match in matches.values())
    return {event_id: match for event_id, match in matches.items() if counts[match["eventId"]] == 1}


def quote_pairs(event):
    """Return unique Novig player/market/line pairs and their original timestamp."""
    pairs = defaultdict(list)
    for book in event.get("bookmakers", []):
        if key(book.get("title", "")) != "novig" and key(book.get("key", "")) != "novig":
            continue
        for market in book.get("markets", []):
            if market.get("key") not in PROP_TYPES.values():
                continue
            for outcome in market.get("outcomes", []):
                side = outcome.get("name", "").lower()
                player = outcome.get("description")
                line = decimal(outcome.get("point"))
                odds = decimal(outcome.get("price"))
                if side not in {"over", "under"} or not player or line is None or odds is None or odds <= 1:
                    continue
                identity = (key(player), market["key"], line)
                pairs[identity].append((side, odds, player, market.get("last_update")))
    result = {}
    for identity, entries in pairs.items():
        if len(entries) == 2 and {entry[0] for entry in entries} == {"over", "under"}:
            result[identity] = {entry[0]: entry for entry in entries}
    return result


def market_identity(market):
    """Infer a player from Novig's display label; never use this for production joins."""
    kind = market.get("marketType")
    line = decimal(market.get("strike"))
    description = market.get("description", "")
    if kind not in PROP_TYPES or line is None or market.get("status") != "OPEN":
        return None
    match = re.fullmatch(r"(.+?)\s+([-+]?\d+(?:\.\d+)?)\s+" + re.escape(kind), description)
    if not match or decimal(match.group(2)) != line:
        return None
    return key(match.group(1)), PROP_TYPES[kind], line


def book_sides(market, book):
    outcomes = market.get("outcomes", [])
    sides = {}
    for outcome in outcomes:
        label = re.fullmatch(r"(Over|Under)\s+([-+]?\d+(?:\.\d+)?)", outcome.get("name", ""), re.IGNORECASE)
        if not label or decimal(label.group(2)) != decimal(market.get("strike")):
            return None
        side = label.group(1).lower()
        if side in sides or not outcome.get("outcomeId"):
            return None
        sides[side] = outcome["outcomeId"]
    if set(sides) != {"over", "under"} or len(outcomes) != 2 or len(set(sides.values())) != 2:
        return None
    orders = book.get("orders")
    if book.get("marketId") != market.get("marketId") or not isinstance(orders, dict):
        raise ValueError("Invalid Novig order-book response")
    result = {}
    for side, opposite in (("over", "under"), ("under", "over")):
        levels = orders.get(sides[opposite], [])
        if not isinstance(levels, list):
            raise ValueError("Invalid Novig order-book ladder")
        bids = []
        for order in levels:
            if not isinstance(order, dict):
                raise ValueError("Invalid Novig order-book order")
            price, qty = decimal(order.get("price")), order.get("qty")
            if price is None or not 0 < price < 1 or not isinstance(qty, int) or isinstance(qty, bool) or qty < 0:
                raise ValueError("Invalid Novig order price or quantity")
            bids.append((price, qty))
        if not bids:
            result[side] = None
            continue
        best = max(price for price, _ in bids)
        quantity = sum(qty for price, qty in bids if price == best)
        taker_price = Decimal(1) - best
        result[side] = {
            "probability": taker_price,
            "contracts": quantity,
            "stake_usd": taker_price * Decimal(quantity) / 100,
        }
    return result


def compare(market, book, pair, now, max_age, tolerance):
    sides = book_sides(market, book)
    if sides is None:
        return "unsupported_outcomes", None
    flags = []
    if any(sides[side] is None for side in ("over", "under")):
        flags.append("one_sided_book")
    ages = {}
    for side in ("over", "under"):
        quote_time = timestamp(pair[side][3])
        age = (now - quote_time).total_seconds() if quote_time is not None else None
        ages[side] = age
        if age is None or not 0 <= age <= max_age:
            if "stale_or_missing_quote_timestamp" not in flags:
                flags.append("stale_or_missing_quote_timestamp")
        if sides[side] is not None and abs(Decimal(1) / pair[side][1] - sides[side]["probability"]) > tolerance:
            if "price_mismatch" not in flags:
                flags.append("price_mismatch")
    stakes = [sides[side]["stake_usd"] if sides[side] is not None else Decimal(0) for side in sides]
    thinner = min(stakes)
    tier = "under_100" if thinner < 100 else "100_to_499" if thinner < 500 else "500_to_1999" if thinner < 2000 else "2000_plus"
    status = flags[0] if flags else "matched"
    return status, {
        "player": pair["over"][2], "market": market["marketType"], "line": str(market["strike"]),
        "novig_market_id": market["marketId"], "sequence": book.get("seq"),
        "status": status, "warnings": flags,
        "sides": {
            side: {
                "available_stake_usd": str(sides[side]["stake_usd"]) if sides[side] else "0",
                "contracts": sides[side]["contracts"] if sides[side] else 0,
                "novig_taker_probability": str(sides[side]["probability"]) if sides[side] else None,
                "feed_decimal_odds": str(pair[side][1]),
                "feed_market_updated_at": pair[side][3],
                "feed_market_age_seconds": ages[side],
            }
            for side in ("over", "under")
        },
        "thinner_side_usd": str(thinner), "observed_tier": tier,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", choices=LEAGUES, default="NBA")
    parser.add_argument("--env-file", help="Optional env file containing ODDS_API_BASE_URL and ODDS_API_KEY")
    parser.add_argument("--max-events", type=int, default=20)
    parser.add_argument("--max-books", type=int, default=50)
    parser.add_argument("--max-age-seconds", type=int, default=900)
    parser.add_argument("--request-delay", type=float, default=0.25)
    args = parser.parse_args(argv)
    if min(args.max_events, args.max_books, args.max_age_seconds) <= 0 or args.request_delay < 0:
        parser.error("limits and max age must be positive; request delay must be nonnegative")
    settings = read_settings(args.env_file)
    base, api_key = settings["ODDS_API_BASE_URL"].rstrip("/"), settings["ODDS_API_KEY"]
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("ODDS_API_BASE_URL must be an HTTPS URL without credentials, query, or fragment")
    if not api_key:
        parser.error("Set ODDS_API_KEY or provide --env-file")

    def novig(path):
        time.sleep(args.request_delay)
        return get_json(NOVIG_URL + path)

    def odds(path):
        return get_json(base + "/v1" + path, {"X-API-Key": api_key})

    started = datetime.now(timezone.utc)
    events = odds("/sports/" + LEAGUES[args.league] + "/events")
    if not isinstance(events, list):
        raise ValueError("Invalid odds API events response")
    upcoming = [event for event in events if timestamp(event.get("commence_time")) and timestamp(event["commence_time"]) > started]
    upcoming.sort(key=lambda event: timestamp(event["commence_time"]))
    upcoming = upcoming[:args.max_events]
    novig_events = list(paged(novig, "/v3/public/catalog/events", {"league": args.league, "status": "OPEN_PREGAME"}, 20))
    matched_events = match_events(upcoming, novig_events)
    counts = Counter(events_scanned=len(upcoming), events_matched=len(matched_events))
    observations = []
    for event in upcoming:
        other = matched_events.get(event["id"])
        if other is None:
            continue
        payload = odds("/events/" + event["id"] + "/odds?markets=all_props&oddsFormat=decimal&freshOnly=true")
        pairs = quote_pairs(payload)
        counts["feed_prop_pairs"] += len(pairs)
        if not pairs:
            continue
        markets = list(paged(novig, "/v3/public/catalog/markets", {"event": other["eventId"]}, 20))
        candidates = defaultdict(list)
        for market in markets:
            identity = market_identity(market)
            if identity in pairs:
                candidates[identity].append(market)
        counts["feed_pairs_without_catalog_match"] += len(set(pairs) - set(candidates))
        for identity, matches in candidates.items():
            if len(matches) != 1:
                counts["ambiguous_market"] += 1
                continue
            if counts["orderbooks_fetched"] >= args.max_books:
                counts["book_limit_reached"] += 1
                continue
            market = matches[0]
            book = novig("/v3/public/catalog/markets/" + market["marketId"] + "/book?depth=1")
            counts["orderbooks_fetched"] += 1
            observed = datetime.now(timezone.utc)
            status, row = compare(market, book, pairs[identity], observed, args.max_age_seconds, Decimal("0.005"))
            counts[status] += 1
            if row:
                row.update(event_id=event["id"], event=other["description"], observed_at=observed.isoformat())
                observations.append(row)
    report = {
        "started_at": started.isoformat(), "completed_at": datetime.now(timezone.utc).isoformat(),
        "league": args.league, "counts": dict(counts),
        "observed_tiers_all_snapshots": dict(Counter(row["observed_tier"] for row in observations)),
        "matched_tiers": dict(Counter(row["observed_tier"] for row in observations if row["status"] == "matched")),
        "observations": observations,
        "notice": "Experimental display-label matching; snapshots may be cached; not suitable for model input.",
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Novig liquidity probe failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
