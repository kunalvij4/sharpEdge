"""Compare full and points-filtered NBA boards; pause the collector before running."""

import asyncio
import json
import re
from collections import Counter

import httpx

from odds_api.infrastructure.clock import SystemClock
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.normalization import Normalizer, values
from odds_api.infrastructure.provider import retry_after


async def main():
    settings, clock = Settings(), SystemClock()
    key = settings.unabated_api_key.get_secret_value()
    next_due = clock.monotonic() + 6
    async with httpx.AsyncClient(
        base_url=settings.unabated_api_base_url,
        headers={"X-Api-Key": key, "Accept": "application/json"},
        timeout=settings.request_timeout,
        follow_redirects=False,
    ) as http:

        async def request(path, params=None):
            nonlocal next_due
            await clock.sleep(max(0, next_due - clock.monotonic()))
            response = await http.get(path, params=params)
            body = response.json()
            messages = json.dumps({k: body[k] for k in ("messages", "message") if k in body})
            for secret in (key, settings.api_keys.get_secret_value(), settings.database_url):
                if secret:
                    messages = messages.replace(secret, "[REDACTED]")
            messages = re.sub(r"https?://[^\s\"<>]+", "[URL]", messages)
            print(
                json.dumps(
                    {
                        "at": clock.now().isoformat(),
                        "path": path,
                        "params": params,
                        "http_status": response.status_code,
                        "success": body.get("success"),
                        "messages": messages[:1200],
                    }
                ),
                flush=True,
            )
            next_due = clock.monotonic() + max(
                6, retry_after(response.headers.get("Retry-After"), clock.now())
            )
            return body.get("data") if body.get("success") is True else None

        bets = await request("/bettype")
        mapping = Normalizer(settings.unabated_bet_type_map).market_map(bets)
        ids = [source_id for source_id, market in mapping.items() if market == "player_points"]
        print(json.dumps({"point_definitions": [b for b in values(bets) if str(b["id"]) in ids]}), flush=True)
        for source_id in [None, *ids]:
            data = await request("/market/nba/props/odds", [("betTypeId", source_id)] if source_id else None)
            if data is None:
                continue
            groups = [
                (period["periodTypeId"], group)
                for league in values(data.get("odds"))
                for period in values(league.get("periodTypes"))
                for phase in ("pregame", "live")
                for group in values(period.get(phase))
            ]
            print(
                json.dumps(
                    {
                        "filter_id": source_id,
                        "groups": len(groups),
                        "event_groups": len([g for _, g in groups if str(g.get("eventId")) == "134312"]),
                        "event_points_groups": dict(
                            Counter(
                                str(period)
                                for period, group in groups
                                if str(group.get("eventId")) == "134312"
                                and str(group.get("betTypeId")) in ids
                            )
                        ),
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
