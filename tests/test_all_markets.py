import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.sharpedge_model import SharpEdge
from app.db.crud import SharpEdgeDB
from app.apis.odds_api import OddsAPI

# Access the ODDS_API_KEY from the environment
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

if ODDS_API_KEY is None:
    raise ValueError("ODDS_API_KEY is not set in the .env file")

# Initialize components
db = SharpEdgeDB()
odds_api = OddsAPI(api_key=ODDS_API_KEY)

# Define sportsbook weights
weights = {
    "Pinnacle": 0.30,
    "Circa": 0.25,
    "BetOnline": 0.15,
    "BookMaker": 0.15,
    "FanDuel": 0.05,
    "DraftKings": 0.05,
    "Caesars": 0.05,
    "BetMGM": 0.05
}

exchange_weights = {
    "ProphetX": 0.10,
    "NoVig": 0.10
}

model = SharpEdge(weights=weights, exchange_weights=exchange_weights, liquidity_threshold=1000)

print("🔄 Fetching live odds for ALL markets (moneyline, spreads, totals)...")

try:
    # Get all markets for NFL games
    all_games = odds_api.get_nfl_all_markets()
    
    if not all_games:
        print("❌ No NFL games found. Trying NBA...")
        all_games = odds_api.get_nba_all_markets()
    
    if not all_games:
        print("❌ No games available")
        exit()
    
    print(f"✅ Found {len(all_games)} games with multiple markets")
    
    total_opportunities = 0
    
    # Process each game across all markets
    for game_id, game_data in list(all_games.items())[:2]:  # Process first 2 games
        print(f"\n🏈 Analyzing: {game_data['home_team']} vs {game_data['away_team']}")
        
        markets = game_data['markets']
        
        # 1. MONEYLINE MARKET
        moneyline_data = markets.get('moneyline', {}).get('odds_data', {})
        if len(moneyline_data) >= 2:
            print(f"\n💰 MONEYLINE Analysis:")
            result = model.analyze_moneyline_market(moneyline_data)
            print(f"  Fair: {game_data['home_team']} {result['fair_prob']:.1%} ({result['fair_odds_american']})")
            print(f"  Books used: {result['books_used']}")
            
            # Save moneyline odds data to database
            ml_market_id = f"{game_id}_ML"
            db.save_odds_data(
                market_id=ml_market_id,
                odds_data=moneyline_data,
                sport=game_data['sport'],
                market_type="moneyline",
                team_home=game_data['home_team'],
                team_away=game_data['away_team']
            )
            
            # Save fair odds calculation
            db.save_fair_odds(
                market_id=ml_market_id,
                fair_prob=result["fair_prob"],
                fair_odds_decimal=result["fair_odds_decimal"],
                fair_odds_american=result["fair_odds_american"],
                books_used=result["books_used"],
                exchanges_used=result["exchanges_used"],
                sport=game_data['sport'],
                market_type="moneyline"
            )
            
            # Check for +EV opportunities
            for book_name, (home_odds, away_odds) in moneyline_data.items():
                ev_home = model.calculate_ev(home_odds, result["fair_prob"])
                if ev_home > 0:
                    print(f"  🎯 +EV: {game_data['home_team']} at {book_name} = {ev_home:.2f}% EV")
                    db.save_ev_bet(
                        market_id=f"{ml_market_id}_HOME",
                        book_name=book_name,
                        offered_odds=home_odds,
                        fair_odds=result["fair_odds_decimal"],
                        fair_prob=result["fair_prob"],
                        ev_percentage=ev_home,
                        sport=game_data['sport'],
                        market_type="moneyline"
                    )
                    total_opportunities += 1
                
                ev_away = model.calculate_ev(away_odds, 1 - result["fair_prob"])
                if ev_away > 0:
                    print(f"  🎯 +EV: {game_data['away_team']} at {book_name} = {ev_away:.2f}% EV")
                    db.save_ev_bet(
                        market_id=f"{ml_market_id}_AWAY",
                        book_name=book_name,
                        offered_odds=away_odds,
                        fair_odds=1/(1-result["fair_prob"]),
                        fair_prob=1-result["fair_prob"],
                        ev_percentage=ev_away,
                        sport=game_data['sport'],
                        market_type="moneyline"
                    )
                    total_opportunities += 1
        
        # 2. SPREAD MARKET
        spreads_data = markets.get('spreads', {}).get('odds_data', {})
        if len(spreads_data) >= 2:
            print(f"\n📊 SPREAD Analysis:")
            
            # Get the spread line (should be consistent across books)
            sample_book = next(iter(spreads_data.values()))
            spread_line = sample_book['home_point']
            
            print(f"  Line: {game_data['home_team']} {spread_line:+}")
            
            result = model.analyze_spread_market(spreads_data)
            print(f"  Fair: {game_data['home_team']} {spread_line:+} = {result['fair_prob']:.1%} ({result['fair_odds_american']})")
            print(f"  Books used: {result['books_used']}")
            
            # Save spread fair odds
            spread_market_id = f"{game_id}_SPREAD_{spread_line}"
            db.save_fair_odds(
                market_id=spread_market_id,
                fair_prob=result["fair_prob"],
                fair_odds_decimal=result["fair_odds_decimal"],
                fair_odds_american=result["fair_odds_american"],
                books_used=result["books_used"],
                exchanges_used=result["exchanges_used"],
                sport=game_data['sport'],
                market_type="spread"
            )
            
            # Check for +EV opportunities
            for book_name, spread_info in spreads_data.items():
                ev_home = model.calculate_ev(spread_info['home_odds'], result["fair_prob"])
                if ev_home > 0:
                    print(f"  🎯 +EV: {game_data['home_team']} {spread_line:+} at {book_name} = {ev_home:.2f}% EV")
                    db.save_ev_bet(
                        market_id=f"{spread_market_id}_HOME",
                        book_name=book_name,
                        offered_odds=spread_info['home_odds'],
                        fair_odds=result["fair_odds_decimal"],
                        fair_prob=result["fair_prob"],
                        ev_percentage=ev_home,
                        sport=game_data['sport'],
                        market_type="spread"
                    )
                    total_opportunities += 1
                
                ev_away = model.calculate_ev(spread_info['away_odds'], 1 - result["fair_prob"])
                if ev_away > 0:
                    print(f"  🎯 +EV: {game_data['away_team']} {-spread_line:+} at {book_name} = {ev_away:.2f}% EV")
                    db.save_ev_bet(
                        market_id=f"{spread_market_id}_AWAY",
                        book_name=book_name,
                        offered_odds=spread_info['away_odds'],
                        fair_odds=1/(1-result["fair_prob"]),
                        fair_prob=1-result["fair_prob"],
                        ev_percentage=ev_away,
                        sport=game_data['sport'],
                        market_type="spread"
                    )
                    total_opportunities += 1
        
        # 3. TOTALS MARKET
        totals_data = markets.get('totals', {}).get('odds_data', {})
        if len(totals_data) >= 2:
            print(f"\n🎯 TOTALS Analysis:")
            
            # Get the totals line
            sample_book = next(iter(totals_data.values()))
            total_line = sample_book['point']
            
            print(f"  Line: O/U {total_line}")
            
            result = model.analyze_totals_market(totals_data)
            print(f"  Fair: Over {total_line} = {result['fair_prob']:.1%} ({result['fair_odds_american']})")
            print(f"  Books used: {result['books_used']}")
            
            # Save totals fair odds
            totals_market_id = f"{game_id}_TOTAL_{total_line}"
            db.save_fair_odds(
                market_id=totals_market_id,
                fair_prob=result["fair_prob"],
                fair_odds_decimal=result["fair_odds_decimal"],
                fair_odds_american=result["fair_odds_american"],
                books_used=result["books_used"],
                exchanges_used=result["exchanges_used"],
                sport=game_data['sport'],
                market_type="total"
            )
            
            # Check for +EV opportunities
            for book_name, totals_info in totals_data.items():
                ev_over = model.calculate_ev(totals_info['over_odds'], result["fair_prob"])
                if ev_over > 0:
                    print(f"  🎯 +EV: Over {total_line} at {book_name} = {ev_over:.2f}% EV")
                    db.save_ev_bet(
                        market_id=f"{totals_market_id}_OVER",
                        book_name=book_name,
                        offered_odds=totals_info['over_odds'],
                        fair_odds=result["fair_odds_decimal"],
                        fair_prob=result["fair_prob"],
                        ev_percentage=ev_over,
                        sport=game_data['sport'],
                        market_type="total"
                    )
                    total_opportunities += 1
                
                ev_under = model.calculate_ev(totals_info['under_odds'], 1 - result["fair_prob"])
                if ev_under > 0:
                    print(f"  🎯 +EV: Under {total_line} at {book_name} = {ev_under:.2f}% EV")
                    db.save_ev_bet(
                        market_id=f"{totals_market_id}_UNDER",
                        book_name=book_name,
                        offered_odds=totals_info['under_odds'],
                        fair_odds=1/(1-result["fair_prob"]),
                        fair_prob=1-result["fair_prob"],
                        ev_percentage=ev_under,
                        sport=game_data['sport'],
                        market_type="total"
                    )
                    total_opportunities += 1
        
        print(f"  ─" * 50)
    
    print(f"\n🎯 SUMMARY: Found {total_opportunities} total +EV opportunities across all markets!")
    print(f"📊 Markets analyzed: Moneylines, Spreads, Totals")
    
    # Show database summary
    print(f"\n💾 DATABASE STATUS:")
    connection_info = db.db.test_connection()
    for table, count in connection_info['row_counts'].items():
        print(f"  {table}: {count} records")
    
    # Show recent +EV opportunities from database
    print(f"\n🔍 Recent +EV Opportunities from Database:")
    recent_ev = db.get_positive_ev_bets(min_ev=0.01, limit=10)
    for bet in recent_ev[:8]:
        print(f"  📈 {bet['ev_percentage']:.2f}% EV - {bet['market_id']} at {bet['book_name']}")

except Exception as e:
    print(f"❌ Error: {str(e)}")
    import traceback
    traceback.print_exc()
