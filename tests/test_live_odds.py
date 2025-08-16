import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.sharpedge_model import SharpEdge
from app.db.crud import SharpEdgeDB
from app.apis.odds_api import OddsAPI

# Initialize database and API
db = SharpEdgeDB()
odds_api = OddsAPI(api_key="1146a647b7e10a678f226f1a597aeea3")

# Define sportsbook weights
weights = {
    "Pinnacle": 0.30,
    "Circa": 0.25,
    "BetOnline": 0.15,
    "BookMaker": 0.15,
    "FanDuel": 0.05,
    "DraftKings": 0.05,
    "Caesars": 0.05,
    "BetMGM": 0.05  # Added since API provides this
}

exchange_weights = {
    "ProphetX": 0.10,
    "NoVig": 0.10
}

# Instantiate the model
model = SharpEdge(weights=weights, exchange_weights=exchange_weights, liquidity_threshold=1000)

print("🔄 Fetching live NFL odds...")

try:
    # Get live NFL games
    nfl_games = odds_api.get_nfl_games()
    
    if not nfl_games:
        print("❌ No NFL games found. Trying NBA...")
        nfl_games = odds_api.get_nba_games()
    
    if not nfl_games:
        print("❌ No games available in either NFL or NBA")
        exit()
    
    print(f"✅ Found {len(nfl_games)} games with live odds")
    
    # Process each game
    for game_id, game_data in list(nfl_games.items())[:3]:  # Process first 3 games
        print(f"\n🏈 Analyzing: {game_data['home_team']} vs {game_data['away_team']}")
        print(f"📅 Game Time: {game_data['commence_time']}")
        
        odds_data = game_data['odds_data']
        
        if len(odds_data) < 2:  # Need at least 2 books for comparison
            print("⚠️  Not enough books available for this game")
            continue
        
        print(f"📊 Books available: {list(odds_data.keys())}")
        
        # Calculate fair odds using live data
        result = model.get_fair_odds_and_ev(odds_data)
        
        # Save to database
        print("💾 Saving live data to database...")
        
        # Save raw odds data
        db.save_odds_data(
            market_id=game_id,
            odds_data=odds_data,
            sport=game_data['sport'],
            market_type=game_data['market_type'],
            team_home=game_data['home_team'],
            team_away=game_data['away_team']
        )
        
        # Save fair odds calculation
        db.save_fair_odds(
            market_id=game_id,
            fair_prob=result["fair_prob"],
            fair_odds_decimal=result["fair_odds_decimal"],
            fair_odds_american=result["fair_odds_american"],
            books_used=result["books_used"],
            exchanges_used=result["exchanges_used"],
            sport=game_data['sport'],
            market_type=game_data['market_type']
        )
        
        # Check each book for +EV opportunities
        fair_odds_decimal = result["fair_odds_decimal"]
        for book_name, (home_odds, away_odds) in odds_data.items():
            # Check home team bet
            ev_home = model.calculate_ev(home_odds, result["fair_prob"])
            if ev_home > 0:
                db.save_ev_bet(
                    market_id=f"{game_id}_HOME",
                    book_name=book_name,
                    offered_odds=home_odds,
                    fair_odds=fair_odds_decimal,
                    fair_prob=result["fair_prob"],
                    ev_percentage=ev_home,
                    sport=game_data['sport'],
                    market_type=game_data['market_type']
                )
                print(f"🎯 +EV FOUND: {game_data['home_team']} at {book_name}: {ev_home:.2f}% EV")
            
            # Check away team bet  
            away_prob = 1 - result["fair_prob"]
            fair_away_odds = 1 / away_prob
            ev_away = model.calculate_ev(away_odds, away_prob)
            if ev_away > 0:
                db.save_ev_bet(
                    market_id=f"{game_id}_AWAY",
                    book_name=book_name,
                    offered_odds=away_odds,
                    fair_odds=fair_away_odds,
                    fair_prob=away_prob,
                    ev_percentage=ev_away,
                    sport=game_data['sport'],
                    market_type=game_data['market_type']
                )
                print(f"🎯 +EV FOUND: {game_data['away_team']} at {book_name}: {ev_away:.2f}% EV")
        
        # Display results for this game
        print(f"\n📊 Fair Odds Analysis:")
        print(f"  {game_data['home_team']}: {result['fair_prob']:.1%} ({result['fair_odds_american']})")
        print(f"  {game_data['away_team']}: {1-result['fair_prob']:.1%}")
        print(f"  Books Used: {result['books_used']}")

    # Show summary of all +EV opportunities found
    print(f"\n🎯 Summary - Positive EV Opportunities Found:")
    positive_ev_bets = db.get_positive_ev_bets(min_ev=0.5)
    for bet in positive_ev_bets[:10]:
        print(f"  📈 {bet['ev_percentage']:.2f}% EV - {bet['market_id']} at {bet['book_name']}")

except Exception as e:
    print(f"❌ Error: {str(e)}")
    print("This might be due to API limits or no active games")
