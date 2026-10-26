from concurrent.futures import ThreadPoolExecutor, as_completed


def fetch_and_attach_player_props(odds_api, games: dict) -> dict:
    PLAYER_PROP_MARKETS = "all_props"

    def fetch_single_event(game_id, game):
        try:
            # ✅ USE REAL EVENT ID
            event_id = game.get("event_id")

            if not event_id:
                print(f"[SKIP] No event_id for {game_id}")
                return game_id, None

            event_odds = odds_api.get_event_odds(event_id, PLAYER_PROP_MARKETS)

            if not event_odds:
                return game_id, None

            structured = {}

            for bookmaker in event_odds.get("bookmakers", []):
                book_name = bookmaker.get("title")

                for market in bookmaker.get("markets", []):
                    stat = market.get("key")

                    for outcome in market.get("outcomes", []):
                        player = outcome.get("description") or outcome.get("name")
                        if not player:
                            continue

                        line = outcome.get("point")
                        price = outcome.get("price")
                        outcome_type = outcome.get("name", "").lower()

                        if line is None:
                            continue

                        structured.setdefault(stat, {})
                        structured[stat].setdefault(player, {})
                        line_key = str(line)  # 🔥 FIX

                        structured[stat][player].setdefault(line_key, {})
                        structured[stat][player][line_key].setdefault(book_name, {})

                        if "over" in outcome_type:
                            structured[stat][player][line_key][book_name]["over_odds"] = price
                        elif "under" in outcome_type:
                            structured[stat][player][line_key][book_name]["under_odds"] = price

            return game_id, structured

        except Exception as e:
            print(f"[ERROR] Props fetch failed for {game_id}: {e}")
            return game_id, None

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(fetch_single_event, gid, g) for gid, g in games.items()]

        for future in as_completed(futures):
            game_id, structured_props = future.result()

            if structured_props:
                games[game_id].setdefault("markets", {})
                games[game_id]["markets"]["props"] = structured_props

    return games

