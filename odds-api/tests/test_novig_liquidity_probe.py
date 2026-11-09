import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from scripts.probe_novig_liquidity import (
    book_sides,
    compare,
    market_identity,
    match_events,
    paged,
    quote_pairs,
)

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
MARKET = {
    "marketId": "market-1",
    "marketType": "ASSISTS",
    "description": "Trae Young 9.5 ASSISTS",
    "strike": "9.5",
    "status": "OPEN",
    "outcomes": [
        {"outcomeId": "over-id", "name": "Over 9.5"},
        {"outcomeId": "under-id", "name": "Under 9.5"},
    ],
}
BOOK = {
    "marketId": "market-1",
    "seq": 7,
    "orders": {
        "over-id": [{"price": "0.48", "qty": 10000}],
        "under-id": [{"price": "0.42", "qty": 238}, {"price": "0.42", "qty": 100}],
    },
}


class NovigProbeTests(unittest.TestCase):
    def test_complement_opposite_bids_and_convert_contracts_to_taker_stake(self):
        sides = book_sides(MARKET, BOOK)
        self.assertEqual(sides["over"]["probability"], Decimal("0.58"))
        self.assertEqual(sides["over"]["contracts"], 338)
        self.assertEqual(sides["over"]["stake_usd"], Decimal("1.9604"))
        self.assertEqual(sides["under"]["stake_usd"], Decimal("52.0000"))

    def test_missing_ladder_is_one_sided_not_a_zero_price(self):
        pair = {
            "over": ("over", Decimal("1.72414"), "Trae Young", NOW.isoformat()),
            "under": ("under", Decimal("1.92308"), "Trae Young", NOW.isoformat()),
        }
        status, result = compare(
            MARKET, {"marketId": "market-1", "orders": {}}, pair, NOW, 900, Decimal(".005")
        )
        self.assertEqual(status, "one_sided_book")
        self.assertEqual(result["sides"]["over"]["available_stake_usd"], "0")

    def test_price_and_timestamp_must_match(self):
        pair = {
            "over": ("over", Decimal("1.72414"), "Trae Young", NOW.isoformat()),
            "under": ("under", Decimal("1.92308"), "Trae Young", NOW.isoformat()),
        }
        status, row = compare(MARKET, BOOK, pair, NOW, 900, Decimal(".005"))
        self.assertEqual(status, "matched")
        self.assertEqual(row["observed_tier"], "under_100")
        pair["over"] = ("over", Decimal("2.0"), "Trae Young", NOW.isoformat())
        self.assertEqual(compare(MARKET, BOOK, pair, NOW, 900, Decimal(".005"))[0], "price_mismatch")
        pair["over"] = ("over", Decimal("1.72414"), "Trae Young", (NOW - timedelta(seconds=901)).isoformat())
        self.assertEqual(
            compare(MARKET, BOOK, pair, NOW, 900, Decimal(".005"))[0], "stale_or_missing_quote_timestamp"
        )

    def test_exact_identity_and_unsupported_markets(self):
        self.assertEqual(market_identity(MARKET), ("traeyoung", "player_assists", Decimal("9.5")))
        self.assertIsNone(market_identity({**MARKET, "description": "Trae Young 8.5 ASSISTS"}))
        self.assertIsNone(market_identity({**MARKET, "marketType": "TEAM_TOTAL"}))
        bad = {**MARKET, "outcomes": [MARKET["outcomes"][0], {"outcomeId": "under-id", "name": "Under 8.5"}]}
        self.assertIsNone(book_sides(bad, BOOK))

    def test_feed_rejects_duplicate_outcomes_and_unrelated_books(self):
        outcomes = [
            {"name": side, "description": "Trae Young", "point": 9.5, "price": 1.9}
            for side in ("Over", "Under")
        ]
        market = {"key": "player_assists", "last_update": NOW.isoformat(), "outcomes": outcomes}
        event = {"bookmakers": [{"title": "Novig", "markets": [market]}]}
        self.assertEqual(len(quote_pairs(event)), 1)
        market["outcomes"] = outcomes + [outcomes[0]]
        self.assertEqual(quote_pairs(event), {})
        event["bookmakers"][0]["title"] = "FanDuel"
        self.assertEqual(quote_pairs(event), {})

    def test_event_requires_exact_unique_teams_and_close_time(self):
        event = {
            "id": "ours",
            "away_team": "Washington Wizards",
            "home_team": "Atlanta Hawks",
            "commence_time": NOW.isoformat(),
        }
        novig = {
            "eventId": "theirs",
            "description": "Washington Wizards @ Atlanta Hawks",
            "startsTs": int(NOW.timestamp() * 1000),
        }
        self.assertEqual(match_events([event], [novig])["ours"], novig)
        self.assertEqual(match_events([event], [novig, novig]), {})
        self.assertEqual(match_events([event, {**event, "id": "duplicate"}], [novig]), {})
        self.assertEqual(match_events([event], [{**novig, "description": "Wizards @ Hawks"}]), {})
        self.assertEqual(match_events([event], [{**novig, "startsTs": novig["startsTs"] + 901000}]), {})

    def test_pagination_and_repeated_cursor_fail_explicitly(self):
        calls = []

        def get(path):
            calls.append(path)
            return {"items": [len(calls)], "next": "abc" if len(calls) == 1 else None}

        self.assertEqual(list(paged(get, "/events", {"league": "NBA"}, 2)), [1, 2])
        self.assertIn("after=abc", calls[1])
        with self.assertRaises(ValueError):
            list(paged(lambda _: {"items": [], "next": "same"}, "/events", {}, 4))


if __name__ == "__main__":
    unittest.main()
