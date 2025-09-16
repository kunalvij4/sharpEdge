import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.sharpedge_model import SharpEdge

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

# Offered odds for the bet
offered_odds = 2.05

# Calculate fair odds and EV
result = model.get_fair_odds_and_ev(odds_data, exchange_data, offered_odds=offered_odds)

# Extract fair probability and calculate Kelly Criterion
fair_prob = result["fair_prob"]  # Probability of winning (p)
if not (0.0 < fair_prob < 1.0):
    raise ValueError("Fair probability must be between 0 and 1.")

q = 1 - fair_prob  # Probability of losing
b = offered_odds - 1  # Net odds (profit divided by stake)

# Kelly Criterion formula: f = (bp - q) / b
kelly_percentage = (b * fair_prob - q) / b

# Convert to percentage
kelly_percentage *= 100

# Display results
print("\n📊 Results:")
print(f"Fair Probability: {fair_prob:.4f}")
print(f"Fair Odds (Decimal): {result['fair_odds_decimal']:.2f}")
print(f"Fair Odds (American): {result['fair_odds_american']}")
print(f"Expected Value: {result['ev_analysis']['ev_percentage']:.2f}%")
print(f"Books Used: {result['books_used']}")
print(f"Exchanges Used: {result['exchanges_used']}")

# Display Kelly Criterion percentage
print(f"\n💰 Kelly Criterion Percentage: {kelly_percentage:.2f}% of bankroll")

