"""Bounded read-only provider probes; pause other users of this key first.

Prints response summaries, never credentials or raw odds. Not a collector.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

import httpx

from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.normalization import Normalizer, values
from odds_api.infrastructure.provider import retry_after


async def main():
    settings = Settings()
    key = settings.unabated_api_key.get_secret_value()
    if not key:
        raise SystemExit("UNABATED_API_KEY is not configured")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    interval = max(6, settings.odds_min_interval, settings.rate_min_interval)
    next_due = 0.0
    async with httpx.AsyncClient(
        base_url=settings.unabated_api_base_url,
        headers={"X-Api-Key": key, "Accept": "application/json"},
        timeout=settings.request_timeout,
        follow_redirects=False,
    ) as client:

        async def probe(path, params=None):
            nonlocal next_due
            loop = asyncio.get_running_loop()
            await asyncio.sleep(max(0, next_due - loop.time()))
            record = {"at": datetime.now(UTC).isoformat(), "path": path}
            wait_seconds = interval
            if params:
                record["params"] = params
            try:
                response = await client.get(path, params=params)
                wait_seconds = max(
                    interval, retry_after(response.headers.get("Retry-After"), datetime.now(UTC))
                )
                record["http_status"] = response.status_code
                record["headers"] = {
                    name: response.headers[name]
                    for name in (
                        "date",
                        "retry-after",
                        "x-request-id",
                        "x-correlation-id",
                        "x-amzn-requestid",
                        "traceparent",
                        "cf-ray",
                    )
                    if name in response.headers
                }
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                    record["invalid_json"] = True
                if isinstance(body, dict):
                    record["success"] = body.get("success")
                    messages = body.get("messages", body.get("message"))
                    record["messages"] = json.loads(json.dumps(messages).replace(key, "[REDACTED]"))
                    data = body.get("data")
                    record["data_type"] = type(data).__name__
                    if isinstance(data, (dict, list)):
                        record["data_count"] = len(data)
                    if path in {"/league", "/market-type"} and isinstance(data, (dict, list)):
                        record["definitions"] = [
                            {"id": item.get("id"), "name": item.get("name")} for item in values(data)
                        ]
                    if path.endswith("/odds") and isinstance(data, dict):
                        groups = [
                            group
                            for league in values(data.get("odds"))
                            for period in values(league.get("periodTypes"))
                            for phase in ("pregame", "live")
                            for group in values(period.get(phase))
                        ]
                        record["event_count"] = len({g.get("eventId") for g in groups})
                        record["group_count"] = len(groups)
                        record["group_fields"] = sorted(groups[0]) if groups else []
                        record["team_fields"] = (
                            sorted(values(groups[0].get("eventTeams"))[0])
                            if (groups and values(groups[0].get("eventTeams")))
                            else []
                        )
                    if path == "/bettype" and isinstance(data, (dict, list)):
                        mapping = Normalizer(settings.unabated_bet_type_map).market_map(data)
                        record["moneyline_ids"] = [k for k, v in mapping.items() if v == "h2h"]
                    print(json.dumps(record), flush=True)
                    return body
                print(json.dumps(record), flush=True)
                return {}
            except httpx.HTTPError as error:
                record["transport_error"] = type(error).__name__
                print(json.dumps(record), flush=True)
                return {}
            finally:
                # Space from completion, including discovery; never retry in a burst.
                next_due = asyncio.get_running_loop().time() + wait_seconds

        await asyncio.sleep(interval)
        await probe("/league")
        await probe("/market-type")
        bets = await probe("/bettype")
        for route in ("nba", "NBA", "nfl", "mlb"):
            await probe("/event/" + route + "/upcoming")
        bet_map = Normalizer(settings.unabated_bet_type_map).market_map(bets.get("data") or [])
        moneylines = [("betTypeId", k) for k, value in bet_map.items() if value == "h2h"]
        if moneylines:
            await probe("/market/nba/straight/odds", moneylines)


if __name__ == "__main__":
    asyncio.run(main())
