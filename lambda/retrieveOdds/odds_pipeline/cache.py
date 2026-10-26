"""Store the latest opportunity snapshots in Redis alongside the S3 copies."""

from functools import lru_cache
from datetime import datetime, timezone
import json
import logging
import os

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from .leagues import LEAGUES
from .markets import CATEGORIES

logger = logging.getLogger(__name__)
CACHE_MARKETS = {"EV": CATEGORIES, "arbitrage": CATEGORIES}


@lru_cache(maxsize=1)
def _get_client(url):
    # Reuse the connection pool across warm Lambda invocations. rediss:// enables
    # TLS with certificate and hostname verification by default.
    return Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=2,
        health_check_interval=30,
        retry=Retry(NoBackoff(), 0),
    )


def cache_snapshot(table, sport, market, opportunities, retrieved_at=None):
    """Replace one league/market snapshot without interrupting the pipeline."""
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        logger.warning("Redis cache disabled: REDIS_URL is not configured")
        return False

    try:
        league = sport.strip().upper()
        field = f"{league}/{market}"
        if league not in LEAGUES:
            raise ValueError("Unsupported league")
        if market not in CACHE_MARKETS[table]:
            raise ValueError("Unsupported cache market")
        if any(bet.get("sport", league) != league for bet in opportunities):
            raise ValueError("Opportunity belongs to another league")
        if any(not bet.get("event_id") for bet in opportunities):
            raise ValueError("Opportunity is missing event_id")
        snapshot = {
            "schema_version": 1,
            "league": league,
            "market": market,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(opportunities),
            "opportunities": opportunities,
        }
        if retrieved_at is not None:
            snapshot["retrieved_at"] = retrieved_at
        # HSET atomically replaces the entire snapshot, including empty results,
        # without touching other sports or markets in the same hash.
        _get_client(url).hset(
            table, field, json.dumps(snapshot, separators=(",", ":"), allow_nan=False)
        )
    except Exception as error:
        # Connection errors can include credentials. Log only the exception type.
        logger.warning(
            "Redis write failed for %s[%s/%s] (%s)",
            table,
            sport,
            market,
            type(error).__name__,
        )
        return False

    logger.info("Redis snapshot saved: %s[%s]", table, field)
    return True
