import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.sharpedge_model import SharpEdge
from app.db.crud import SharpEdgeDB

# Initialize database
db = SharpEdgeDB()

# Define sportsbook weights
weights = {
    "Pinnacle": 0.30,
    "Circa": 0.25,
    "BetOnline": 0.15,
    "BookMaker": 0.15,
    "FanDuel": 0.05,
    "DraftKings": 0.05,
    "Caesars": 0.05
}

exchange_weights = {
    "ProphetX": 0.10,
    "NoVig": 0.10
}

# Instantiate the model
model = SharpEdge(weights=weights, exchange_weights=exchange_weights, liquidity_threshold=1000)

# Test data
odds_data = {
    "Pinnacle": (1.91, 1.91),
    "Circa": (1.92, 1.90),
    "BetOnline": (1.91, 1.91),
    "BookMaker": (1.90, 1.92),
    "FanDuel": (1.88, 1.93),
    "DraftKings": (1.89, 1.92),
    "Caesars": (1.88, 1.94)
}

exchange_data = {
    "ProphetX": {"odds": (1.93, 1.93), "liquidity": 1200},
    "NoVig": {"odds": (1.91, 1.91), "liquidity": 800}
}

# Market details
market_id = "NFL_2025_Week1_Chiefs_vs_Bills_ML"
sport = "NFL"
market_type = "moneyline"

# Calculate fair odds
result = model.get_fair_odds_and_ev(odds_data, exchange_data, offered_odds=2.05)

# Save to database
print("💾 Saving data to database...")

# Save raw odds data
db.save_odds_data(market_id, odds_data, sport, market_type, "Kansas City Chiefs", "Buffalo Bills")

# Save fair odds calculation
db.save_fair_odds(
    market_id=market_id,
    fair_prob=result["fair_prob"],
    fair_odds_decimal=result["fair_odds_decimal"],
    fair_odds_american=result["fair_odds_american"],
    books_used=result["books_used"],
    exchanges_used=result["exchanges_used"],
    sport=sport,
    market_type=market_type
)

# Save EV bet if positive
if result["ev_percentage"] and result["ev_percentage"] > 0:
    db.save_ev_bet(
        market_id=market_id,
        book_name="TestBook",
        offered_odds=2.05,
        fair_odds=result["fair_odds_decimal"],
        fair_prob=result["fair_prob"],
        ev_percentage=result["ev_percentage"],
        sport=sport,
        market_type=market_type
    )

# Display results
print("\n📊 Results:")
print(f"Fair Probability: {result['fair_prob']:.4f}")
print(f"Fair Odds (Decimal): {result['fair_odds_decimal']:.2f}")
print(f"Fair Odds (American): {result['fair_odds_american']}")
print(f"Expected Value: {result['ev_percentage']:.2f}%")
print(f"Books Used: {result['books_used']}")
print(f"Exchanges Used: {result['exchanges_used']}")

# Query recent positive EV bets
print("\n🎯 Recent Positive EV Bets:")
positive_ev_bets = db.get_positive_ev_bets(min_ev=1.0)
for bet in positive_ev_bets[:5]:  # Show top 5
    print(f"  {bet['market_id']}: {bet['ev_percentage']:.2f}% EV at {bet['book_name']}")
