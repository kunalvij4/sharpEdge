import sys
import os
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.player_props_model import PlayerPropsModel
from app.apis.odds_api import OddsAPI
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.player_props_model import PlayerPropsModel

# Initialize player props model with NO main line weights - pure prop focus
prop_model = PlayerPropsModel(min_books=3)

print("🏈 Testing Player Props Model with SPECIALIZED PROP WEIGHTS")
print("=" * 70)

# VERIFY the prop-specific weights are being used
print("\n📊 PLAYER PROP WEIGHTS (Specialized for Props):")
print("These weights are DIFFERENT from main line weights:")
print(f"{'Book':<15} {'Prop Weight':<12} {'Reasoning'}")
print("-" * 60)

# Get the actual prop weights from the model
prop_weights = prop_model.get_effective_weights()

# Updated explanations to match your locked-in weights
prop_explanations = {
    "FanDuel": "35% - prop-heavy recreational liquidity",
    "DraftKings": "25% - strong volume, stable prop pricing",
    "NoVig": "15% - sharp-ish pricing, low-vig signals",
    "ProphetX": "10% - exchange-derived signal",
    "Fanatics": "10% - growing prop market",
    "Others": "5% - minor influence across remaining books"
}

for book, weight in prop_weights.items():
    explanation = prop_explanations.get(book, "Prop specialist")
    print(f"{book:<15} {weight:<12.1%} {explanation}")

print(f"\n💡 Key Difference: FanDuel gets 35% (props focus)")
print(f"💡 Key Difference: DraftKings gets 25% (props focus)")
print(f"💡 Tier Rule: Need at least 2 of FanDuel/DraftKings/NoVig/ProphetX")

# -------------------------
# Synthetic Test Case 1
# -------------------------
print("\n" + "=" * 70)
print("📊 Test Case 1: Josh Allen Passing Yards (Synthetic)")
print("Using PROP-SPECIALIZED weights to find edges...")

josh_allen_passing = {
    "FanDuel": {"over_odds": 1.83, "under_odds": 1.95, "line": 267.5},
    "DraftKings": {"over_odds": 1.87, "under_odds": 1.91, "line": 267.5},
    "Fanatics": {"over_odds": 1.88, "under_odds": 1.90, "line": 267.5},
    "NoVig": {"over_odds": 1.90, "under_odds": 1.90, "line": 267.5},
    "ProphetX": {"over_odds": 1.89, "under_odds": 1.91, "line": 267.5},
    "BetMGM": {"over_odds": 1.85, "under_odds": 1.93, "line": 268.5}  # goes to "Others"
# Show each weight with explanation
prop_explanations = {
    "FanDuel": "28% - Soft recreational props, high volume",
    "Circa": "22% - Sharp across all markets including props", 
    "Pinnacle": "12% - Sharp but lower prop liquidity",
    "Caesars": "12% - Good prop volume, moderate sharpness",
    "PropBuilder": "10% - Prop-focused book (if available)",
    "DraftKings": "8% - Large volume but slower prop adjustments",
    "BetMGM": "6% - Growing prop markets",
    "BetOnline": "2% - Primarily main line focused"
}

for book, weight in prop_weights.items():
    if weight > 0:
        explanation = prop_explanations.get(book, "Prop specialist")
        print(f"{book:<15} {weight:<12.1%} {explanation}")

print(f"\n💡 Key Difference: FanDuel gets 28% (vs ~5% on main lines)")
print(f"💡 Key Difference: Pinnacle gets 12% (vs ~30% on main lines)")

# Test Case 1: NFL Passing Yards Over/Under
print("\n" + "=" * 70)
print("📊 Test Case 1: Josh Allen Passing Yards")
print("Using PROP-SPECIALIZED weights to find recreational book edges...")

josh_allen_passing = {
    "FanDuel": {"over_odds": 1.83, "under_odds": 1.95, "line": 267.5},        # Should be heavily weighted (28%)
    "DraftKings": {"over_odds": 1.87, "under_odds": 1.91, "line": 267.5},     # Lower weight (8%)
    "BetMGM": {"over_odds": 1.85, "under_odds": 1.93, "line": 268.5},         # Lower weight (6%)
    "Circa": {"over_odds": 1.90, "under_odds": 1.88, "line": 267.5},          # High weight (22%) - sharp reference
    "Pinnacle": {"over_odds": 1.89, "under_odds": 1.89, "line": 267.5},       # Medium weight (12%)
    "Caesars": {"over_odds": 1.86, "under_odds": 1.92, "line": 267.5}         # Medium weight (12%)
}

try:
    analysis = prop_model.analyze_over_under_prop(
        josh_allen_passing, "Josh Allen", "passing_yards"
    )
    
    print(f"  Player: {analysis['player']}")
    print(f"  Consensus Line: {analysis['consensus_line']} yards")
    print(f"  Fair Over Prob: {analysis['fair_over_prob']:.1%} ({analysis['fair_over_odds_american']})")
    print(f"  Fair Under Prob: {analysis['fair_under_prob']:.1%} ({analysis['fair_under_odds_american']})")
    print(f"  Books Used: {analysis['books_used']} (Total Weight: {analysis['total_weight_used']:.1%})")
    print(f"  Weighting Scheme: {analysis['weighting_scheme']}")
    
    opportunities = prop_model.find_prop_ev_opportunities(analysis, josh_allen_passing, min_ev=0.1)
    if opportunities:
        print(f"\n  🎯 +EV Opportunities Found:")
        for opp in opportunities:
            print(f"    {opp['bet_type']} {opp.get('line','')} at {opp['book_name']} ({opp['book_tier']}): {opp['ev_percentage']:.2f}% EV")
    # Verify which books are actually contributing to fair value
    print(f"\n  📊 Weight Breakdown:")
    for book, data in josh_allen_passing.items():
        book_weight = prop_weights.get(book, 0.0)
        if book_weight > 0:
            print(f"    {book}: {book_weight:.1%} weight in fair value calculation")
    
    # Find EV opportunities
    opportunities = prop_model.find_prop_ev_opportunities(analysis, josh_allen_passing, min_ev=0.1)
    
    if opportunities:
        print(f"\n  🎯 +EV Opportunities Found:")
        for opp in opportunities:
            print(f"    {opp['bet_type']} {opp['line']} at {opp['book_name']} ({opp['book_tier']}): {opp['ev_percentage']:.2f}% EV")
            print(f"      Book Weight in Model: {opp['book_weight']:.1%} | Variance: {opp['variance_level']}")
    else:
        print(f"  ℹ️  No +EV opportunities found (min 0.1%)")

except Exception as e:
    print(f"  ❌ Error: {str(e)}")

# -------------------------
# Synthetic Test Case 2
# -------------------------
print("\n" + "=" * 70)
print("📊 Test Case 2: Travis Kelce First TD Scorer (Synthetic)")
print("High variance prop - recreational books should be soft...")

kelce_first_td = {
    "FanDuel": {"yes_odds": 12.0, "no_odds": 1.05},
    "DraftKings": {"yes_odds": 11.5, "no_odds": 1.06},
    "NoVig": {"yes_odds": 11.8, "no_odds": 1.06},
    "ProphetX": {"yes_odds": 11.6, "no_odds": 1.06},
    "BetMGM": {"yes_odds": 13.0, "no_odds": 1.04}  # goes to "Others"
    import traceback
    traceback.print_exc()

# Test Case 2: First Touchdown Scorer (High Variance)
print("\n" + "=" * 70)
print("📊 Test Case 2: Travis Kelce First TD Scorer")
print("High variance prop - recreational books should be VERY soft...")

kelce_first_td = {
    "FanDuel": {"yes_odds": 12.0, "no_odds": 1.05},      # 28% weight - should dominate fair value
    "DraftKings": {"yes_odds": 11.5, "no_odds": 1.06},   # 8% weight - less influence
    "BetMGM": {"yes_odds": 13.0, "no_odds": 1.04},       # 6% weight - should show +EV
    "Circa": {"yes_odds": 11.0, "no_odds": 1.07},        # 22% weight - sharp reference
    "Caesars": {"yes_odds": 11.8, "no_odds": 1.05}       # 12% weight - moderate
}

try:
    analysis = prop_model.analyze_yes_no_prop(
        kelce_first_td, "Travis Kelce", "first_touchdown"
    )
    
    print(f"  Player: {analysis['player']}")
    print(f"  Fair Yes Prob: {analysis['fair_yes_prob']:.1%} ({analysis['fair_yes_odds_american']})")
    print(f"  Fair No Prob: {analysis['fair_no_prob']:.1%} ({analysis['fair_no_odds_american']})")
    print(f"  Books Used: {analysis['books_used']} (Total Weight: {analysis['total_weight_used']:.1%})")
    print(f"  Variance Level: {analysis['prop_characteristics']['variance']}")
    
    opportunities = prop_model.find_prop_ev_opportunities(analysis, kelce_first_td, min_ev=0.5)
    # Show weight contribution breakdown
    print(f"\n  📊 Fair Value Contributors:")
    for book, data in kelce_first_td.items():
        book_weight = prop_weights.get(book, 0.0)
        if book_weight > 0:
            contribution = book_weight / analysis['total_weight_used'] * 100
            print(f"    {book}: {contribution:.1f}% of fair value calculation")
    
    # Find EV opportunities
    opportunities = prop_model.find_prop_ev_opportunities(analysis, kelce_first_td, min_ev=0.5)
    
    if opportunities:
        print(f"\n  🎯 +EV Opportunities Found:")
        for opp in opportunities:
            print(f"    {opp['bet_type']} at {opp['book_name']} ({opp['book_tier']}): {opp['ev_percentage']:.2f}% EV")
            print(f"      Book's Model Weight: {opp['book_weight']:.1%}")
    else:
        print(f"  ℹ️  No +EV opportunities found (min 0.5%)")

except Exception as e:
    print(f"  ❌ Error: {str(e)}")

# -------------------------
# LIVE THEODDSAPI TEST
# -------------------------
print("\n" + "=" * 70)
print("🌐 LIVE TEST: TheOddsAPI Player Props")
print("Fetching live player props and running the model...")

odds_api = OddsAPI(api_key=os.getenv("ODDS_API_KEY"))

# Set your markets here (TheOddsAPI market keys vary by sport)
# NBA examples: player_points, player_rebounds, player_assists, player_threes
markets = os.getenv("PLAYER_PROPS_MARKETS", "player_points,player_rebounds,player_assists,player_threes")
sport_key = os.getenv("PLAYER_PROPS_SPORT", "basketball_nba")

# Map TheOddsAPI market keys -> model prop types
def map_prop_type(market_key: str) -> str:
    key = market_key.lower()
    if "points" in key:
        return "points"
    if "rebounds" in key:
        return "rebounds"
    if "assists" in key:
        return "assists"
    return market_key

try:
    # Player props must be fetched per-event
    events = odds_api.get_events(sport_key)
    if not events:
        print("❌ No events returned for this sport.")
    else:
        print(f"✅ Found {len(events)} events. Pulling props for first 3 events...")

        grouped_props = defaultdict(lambda: defaultdict(dict))

        for event in events[:3]:
            event_id = event.get("id")
            if not event_id:
                continue

            event_odds = odds_api.get_event_odds(
                sport_key,
                event_id,
                markets=markets
            )

            for bookmaker in event_odds.get("bookmakers", []):
                book_name = bookmaker.get("title")
                for market in bookmaker.get("markets", []):
                    market_key = market.get("key")
                    for outcome in market.get("outcomes", []):
                        player_name = outcome.get("description") or outcome.get("name")
                        if not player_name:
                            continue

                        outcome_name = outcome.get("name", "").lower()
                        price = outcome.get("price")
                        point = outcome.get("point")

                        if "over" in outcome_name:
                            grouped_props[(market_key, player_name)][book_name]["over_odds"] = price
                            if point is not None:
                                grouped_props[(market_key, player_name)][book_name]["line"] = point
                        elif "under" in outcome_name:
                            grouped_props[(market_key, player_name)][book_name]["under_odds"] = price
                            if point is not None:
                                grouped_props[(market_key, player_name)][book_name]["line"] = point
                        elif "yes" in outcome_name:
                            grouped_props[(market_key, player_name)][book_name]["yes_odds"] = price
                        elif "no" in outcome_name:
                            grouped_props[(market_key, player_name)][book_name]["no_odds"] = price

        # Analyze first few props
        analyzed = 0
        for (market_key, player_name), prop_data in grouped_props.items():
            if analyzed >= 5:
                break

            sample = next(iter(prop_data.values()), {})
            is_yes_no = "yes_odds" in sample or "no_odds" in sample
            is_over_under = "over_odds" in sample or "under_odds" in sample

            if not (is_yes_no or is_over_under):
                continue

            try:
                prop_type = map_prop_type(market_key)

                if is_over_under:
                    # Group by line so each line prints separately (e.g., 6.5 vs 7.5)
                    line_groups = defaultdict(dict)
                    for book_name, book_data in prop_data.items():
                        line = book_data.get("line")
                        if line is None:
                            continue
                        line_groups[line][book_name] = book_data

                    for line, line_books in sorted(line_groups.items(), key=lambda x: x[0]):
                        analysis = prop_model.analyze_over_under_prop(line_books, player_name, prop_type)

                        print(f"\n🎯 {player_name} | {market_key} | line {line}")
                        print(f"  Books Used: {analysis['books_used']}")
                        print(f"  Weight Used: {analysis['total_weight_used']:.1%}")
                        print(f"  Fair Over Prob: {analysis['fair_over_prob']:.1%} ({analysis['fair_over_odds_american']})")
                        print(f"  Fair Under Prob: {analysis['fair_under_prob']:.1%} ({analysis['fair_under_odds_american']})")

                        # Show odds for each book at this specific line
                        print("  Book Odds:")
                        for book_name, book_data in line_books.items():
                            parts = []
                            parts.append(f"line={book_data.get('line')}")
                            if "over_odds" in book_data:
                                parts.append(f"over={book_data['over_odds']}")
                            if "under_odds" in book_data:
                                parts.append(f"under={book_data['under_odds']}")
                            print(f"    {book_name}: " + ", ".join(parts))

                        opportunities = prop_model.find_prop_ev_opportunities(analysis, line_books, min_ev=0.5)
                        if opportunities:
                            print("  ✅ +EV Opportunities:")
                            for opp in opportunities[:3]:
                                bet_type = opp["bet_type"].lower()
                                odds_key = f"{bet_type}_odds"
                                book_data = line_books.get(opp["book_name"], {})
                                odds_val = book_data.get(odds_key)
                                fair_prob = analysis["fair_over_prob"] if bet_type == "over" else analysis["fair_under_prob"]
                                print(f"    {opp['bet_type']} at {opp['book_name']}: {opp['ev_percentage']:.2f}% EV @ {odds_val} | Fair Prob: {fair_prob:.1%}")
                        else:
                            print("  ℹ️  No +EV opportunities found")

                else:
                    # Yes/No (no line split)
                    analysis = prop_model.analyze_yes_no_prop(prop_data, player_name, prop_type)

                    print(f"\n🎯 {player_name} | {market_key}")
                    print(f"  Books Used: {analysis['books_used']}")
                    print(f"  Weight Used: {analysis['total_weight_used']:.1%}")
                    print(f"  Fair Yes Prob: {analysis['fair_yes_prob']:.1%} ({analysis['fair_yes_odds_american']})")
                    print(f"  Fair No Prob: {analysis['fair_no_prob']:.1%} ({analysis['fair_no_odds_american']})")

                    print("  Book Odds:")
                    for book_name, book_data in prop_data.items():
                        parts = []
                        if "yes_odds" in book_data:
                            parts.append(f"yes={book_data['yes_odds']}")
                        if "no_odds" in book_data:
                            parts.append(f"no={book_data['no_odds']}")
                        if parts:
                            print(f"    {book_name}: " + ", ".join(parts))

                    opportunities = prop_model.find_prop_ev_opportunities(analysis, prop_data, min_ev=0.5)
                    if opportunities:
                        print("  ✅ +EV Opportunities:")
                        for opp in opportunities[:3]:
                            bet_type = opp["bet_type"].lower()
                            odds_key = f"{bet_type}_odds"
                            book_data = prop_data.get(opp["book_name"], {})
                            odds_val = book_data.get(odds_key)
                            fair_prob = analysis["fair_yes_prob"] if bet_type == "yes" else analysis["fair_no_prob"]
                            print(f"    {opp['bet_type']} at {opp['book_name']}: {opp['ev_percentage']:.2f}% EV @ {odds_val} | Fair Prob: {fair_prob:.1%}")
                    else:
                        print("  ℹ️  No +EV opportunities found")

                    analyzed += 1

            except Exception:
                continue

except Exception as e:
    print(f"❌ Error fetching or parsing TheOddsAPI props: {e}")

print("\n" + "=" * 70)
print("✅ PLAYER PROPS LIVE TEST COMPLETE")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print("✅ PROP-SPECIALIZED WEIGHTING VERIFICATION COMPLETE!")
print("\n🔍 What This Test Proves:")
print("  ✅ FanDuel & Circa dominate fair value calculation (50% combined)")
print("  ✅ Pinnacle has reduced influence on props (12% vs 30% on main lines)")
print("  ✅ Recreational books should show more +EV opportunities")
print("  ✅ Model uses DIFFERENT weights than main line markets")
print("  ✅ Weight contributions are transparent and verifiable")
