import asyncio
import re
from collections import Counter
from email.utils import parsedate_to_datetime

import httpx

from odds_api.domain.models import League
from odds_api.infrastructure.normalization import Normalizer, values

# Discovery returns display names, while REST paths use route tokens.
# Numeric IDs must still come from the account's discovery response.
MARKET_TYPE_NAMES = {
    "straight": {"straight"},
    "props": {"props", "player props"},
}


class ProviderError(RuntimeError):
    def __init__(self, code, *, http_status=None, reason=None):
        super().__init__(code)
        self.code = code
        self.provider_path = None
        self.provider_http_status = http_status
        self.failure_reason = reason


def retry_after(value, now):
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - now).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0


class UnabatedClient:
    def __init__(self, settings, clock, limiter, http=None):
        self.settings, self.clock, self.limiter = settings, clock, limiter
        self.http = http or httpx.AsyncClient(
            base_url=settings.unabated_api_base_url,
            headers={"X-Api-Key": settings.unabated_api_key.get_secret_value(), "Accept": "application/json"},
            timeout=httpx.Timeout(settings.request_timeout),
            follow_redirects=False,
        )
        self.normalizer = Normalizer(
            settings.unabated_bet_type_map, settings.unabated_period_map, settings.unabated_partner_code
        )
        self.cache, self.metadata_lock, self.metrics = {}, asyncio.Lock(), Counter()
        self.allowed_paths = {"/league", "/bettype", "/market-type"}
        for config in settings.leagues.values():
            route = config["route"]
            self.allowed_paths.update({"/period-type/" + route, "/team/" + route, "/player/" + route})
            self.allowed_paths.update(
                "/market/" + route + "/" + market + "/" + operation
                for market in ("straight", "props")
                for operation in ("odds", "sources")
            )

    async def request(self, path, params=None):
        if path not in self.allowed_paths:
            raise ProviderError("unsupported_provider_endpoint")
        try:
            return await self._request(path, params)
        except ProviderError as error:
            # Only relative endpoint paths enter logs; never URLs, query strings or bodies.
            error.provider_path = path if re.fullmatch(r"/[a-zA-Z0-9/_-]+", path) else None
            raise

    async def _request(self, path, params=None):
        for attempt in range(self.settings.max_attempts):
            delay = self.settings.retry_backoff * 2**attempt
            code = "provider_transport"
            status = None
            try:
                async with self.limiter.request(odds=path.endswith("/odds")):
                    self.metrics["requests"] += 1
                    self.metrics["requests:" + path] += 1
                    response = await self.http.get(path, params=params)
                status = response.status_code
                if status == 401:
                    raise ProviderError(
                        "authentication_failed_check_UNABATED_API_KEY_and_base_url", http_status=status
                    )
                if status in {403, 404, 400}:
                    raise ProviderError(
                        "coverage_denied" if status == 403 else "unsupported_request", http_status=status
                    )
                if status == 429 or status >= 500:
                    code = "rate_limited" if status == 429 else "provider_unavailable"
                    self.metrics["rate_limits" if status == 429 else "server_errors"] += 1
                    delay = max(delay, retry_after(response.headers.get("Retry-After"), self.clock.now()))
                    self.limiter.defer(delay)
                elif status >= 300:
                    raise ProviderError("unexpected_http_status", http_status=status)
                else:
                    body = response.json()
                    if not isinstance(body, dict) or body.get("success") is not True:
                        self.metrics["operation_failures"] += 1
                        raise ProviderError(
                            "provider_operation_failed",
                            http_status=status,
                            reason="upstream_unsuccessful_response",
                        )
                    if body.get("data") is None:
                        raise ProviderError("missing_provider_data", http_status=status)
                    pagination = body.get("pagination")
                    if pagination and (
                        pagination.get("nextCursor")
                        or pagination.get("hasNextPage")
                        or pagination.get("totalPages", 1) > 1
                    ):
                        raise ProviderError("incomplete_pagination", http_status=status)
                    return body["data"], not bool(body.get("messages"))
            except (httpx.TransportError, ValueError):
                code = "provider_transport_or_invalid_json"
            if attempt + 1 == self.settings.max_attempts:
                raise ProviderError(code, http_status=status)
            self.metrics["retries"] += 1
            await self.clock.sleep(delay)
        raise AssertionError("unreachable")

    async def metadata(self, path, ttl):
        async with self.metadata_lock:
            cached = self.cache.get(path)
            if cached and self.clock.monotonic() - cached[0] < ttl:
                return cached[1]
            data, complete = await self.request(path)
            if not complete:
                error = ProviderError("incomplete_discovery", http_status=200)
                error.provider_path = path
                raise error
            self.cache[path] = (self.clock.monotonic(), data)
            return data

    async def fetch(self, league_key, kind):
        config = self.settings.leagues[league_key]
        route = config["route"]
        leagues = await self.metadata("/league", self.settings.metadata_ttl)
        found = [league for league in values(leagues) if league["name"].casefold() == route.casefold()]
        if len(found) != 1:
            raise ProviderError("league_not_discovered_check_LEAGUES_JSON")
        league = League(league_key, config["title"], route, str(found[0]["id"]))
        bets = await self.metadata("/bettype", self.settings.metadata_ttl)
        periods = await self.metadata("/period-type/" + route, self.settings.metadata_ttl)
        market_types = await self.metadata("/market-type", self.settings.metadata_ttl)
        market_type = "straight" if kind == "moneyline" else "props"
        prefix = "/market/" + route + "/" + market_type
        # Filter moneylines using the current discovery ID, never a hardcoded numeric ID.
        mapping = self.normalizer.market_map(bets)
        params = (
            [("betTypeId", key) for key, value in mapping.items() if value == "h2h"]
            if kind == "moneyline"
            else None
        )
        if kind == "moneyline" and not params:
            raise ProviderError("moneyline_mapping_unavailable")
        data, complete = await self.request(prefix + "/odds", params)
        # Only identities required by this authorized board are fetched. No event
        # enrichment or cross-market source fallback is needed to read its prices.
        sources = await self.metadata(prefix + "/sources", self.settings.scope_metadata_ttl)
        teams = await self.metadata("/team/" + route, self.settings.scope_metadata_ttl)
        people = {}
        if kind == "props":
            people = await self.metadata("/player/" + route, self.settings.scope_metadata_ttl)
        normalizer = Normalizer(
            self.settings.unabated_bet_type_map,
            self.settings.unabated_period_map,
            self.settings.unabated_partner_code,
        )
        type_ids = {
            str(m["id"])
            for m in values(market_types)
            if (m.get("name") or "").strip().casefold() in MARKET_TYPE_NAMES[market_type]
        }
        if len(type_ids) != 1:
            raise ProviderError("market_type_not_discovered")
        normalizer.disabled_sources = {
            str(s["id"])
            for s in values(sources)
            if type_ids & {str(i) for i in (s.get("disabledMarketTypeIds") or [])}
        }
        try:
            board = normalizer.parse(
                league,
                kind,
                data,
                sources,
                bets,
                periods,
                [],
                people,
                teams,
                self.clock.now(),
                complete,
            )
        except (ValueError, KeyError, TypeError) as error:
            # Known local validation messages are safe; never log Pydantic inputs or provider bodies.
            known_reasons = {
                "Missing event start",
                "Event identity and team names are required",
                "Missing player discovery context",
                "Unexpected league in scoped response",
                "Unknown source; refresh discovery before replacing board",
                "Over/under prop is missing points",
                "Conflicting duplicate selections",
                "American odds must be <= -100 or >= 100",
                "Missing odds board; cannot confirm empty scope",
            }
            reason = str(error) if str(error) in known_reasons else type(error).__name__
            failure = ProviderError("provider_normalization_failed", http_status=200, reason=reason)
            failure.provider_path = prefix + "/odds"
            raise failure from None
        return board

    async def close(self):
        await self.http.aclose()
