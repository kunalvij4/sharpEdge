"""Read-only, filtered props probes. Pause other collectors using the key first."""

import asyncio
import json

from odds_api.infrastructure.clock import SystemClock
from odds_api.infrastructure.config import Settings
from odds_api.infrastructure.normalization import values
from odds_api.infrastructure.provider import ProviderError, UnabatedClient
from odds_api.infrastructure.rate_limit import RateLimiter


async def main():
    settings, clock = Settings(), SystemClock()
    client = UnabatedClient(settings, clock, RateLimiter(clock, 6, 6))
    try:
        await clock.sleep(6)
        bets, _ = await client.request("/bettype")
        mapping = client.normalizer.market_map(bets)
        for route, key in (
            ("nba", "player_points"),
            ("nfl", "player_pass_yds"),
            ("mlb", "pitcher_strikeouts"),
        ):
            ids = [source_id for source_id, target in mapping.items() if target == key]
            record = {"at": clock.now().isoformat(), "league": route, "market": key, "bet_type_ids": ids}
            if not ids:
                record["outcome"] = "mapping_unavailable"
            else:
                try:
                    data, complete = await client.request(
                        "/market/" + route + "/props/odds", [("betTypeId", source_id) for source_id in ids]
                    )
                    groups = [
                        group
                        for league in values(data.get("odds"))
                        for period in values(league.get("periodTypes"))
                        for phase in ("pregame", "live")
                        for group in values(period.get(phase))
                    ]
                    record.update(
                        outcome="success",
                        complete=complete,
                        groups=len(groups),
                        events=len({group.get("eventId") for group in groups}),
                    )
                except ProviderError as error:
                    record.update(
                        outcome=error.code, path=error.provider_path, http_status=error.provider_http_status
                    )
            print(json.dumps(record), flush=True)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
