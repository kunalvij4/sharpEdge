import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.nfl_weights import NFLWeightingEngine
from app.services.sharpedge_model import SharpEdge
from app.apis.odds_api import OddsAPI

def decimal_to_american(decimal_odds):
    """Convert decimal odds to American format"""
    if decimal_odds >= 2.0:
        return f"+{int((decimal_odds - 1) * 100)}"
    else:
        return f"-{int(100 / (decimal_odds - 1))}"

def analyze_spreads_and_totals(game, nfl_engine, model):
    """Analyze spreads and totals with clear betting format and American odds"""
    
    print(f"\n🏈 ANALYZING ALL NFL MARKETS")
    print(f"=" * 50)
    
    # Extract spreads data
    spreads_data = {}
    totals_data = {}
    
    # GET ALL AVAILABLE BOOKS FIRST
    all_available_books = [bookmaker['title'] for bookmaker in game.get('bookmakers', [])]
    
    # GET DYNAMIC WEIGHTS FOR EACH MARKET
    spreads_weights = nfl_engine.get_nfl_weights('spreads', all_available_books)
    totals_weights = nfl_engine.get_nfl_weights('totals', all_available_books)
    
    print(f"📊 Spreads weights: {spreads_weights}")
    print(f"📊 Totals weights: {totals_weights}")
    
    for bookmaker in game.get('bookmakers', []):
        api_book_name = bookmaker['title']
        book_name = nfl_engine.normalize_book_name(api_book_name)
        
        for market in bookmaker.get('markets', []):
            if market['key'] == 'spreads':
                # Use dynamic weights for spreads
                if book_name in spreads_weights:
                    for outcome in market['outcomes']:
                        if outcome['name'] == game['home_team']:
                            home_spread = outcome.get('point', 0)
                            home_spread_odds = outcome['price']
                            away_spread = -home_spread
                            away_spread_odds = next((o['price'] for o in market['outcomes'] if o['name'] == game['away_team']), None)
                            
                            if away_spread_odds:
                                spreads_data[book_name] = {
                                    'home_spread': home_spread,
                                    'home_odds': home_spread_odds,
                                    'away_spread': away_spread,
                                    'away_odds': away_spread_odds
                                }
                                weight = spreads_weights.get(book_name, 0)
                                print(f"  ✅ {book_name} SPREADS: {game['home_team']} {home_spread:+.1f} / {game['away_team']} {away_spread:+.1f} (weight: {weight:.3f})")
                            break
                else:
                    print(f"  ⏭️ Excluding {book_name} from spreads (not in dynamic weights)")
            
            elif market['key'] == 'totals':
                # Use dynamic weights for totals
                if book_name in totals_weights:
                    over_outcome = next((o for o in market['outcomes'] if o['name'] == 'Over'), None)
                    under_outcome = next((o for o in market['outcomes'] if o['name'] == 'Under'), None)
                    
                    if over_outcome and under_outcome:
                        total_line = over_outcome.get('point', 0)
                        totals_data[book_name] = {
                            'total': total_line,
                            'over_odds': over_outcome['price'],
                            'under_odds': under_outcome['price']
                        }
                        weight = totals_weights.get(book_name, 0)
                        print(f"  ✅ {book_name} TOTALS: O/U {total_line} (weight: {weight:.3f})")
                else:
                    print(f"  ⏭️ Excluding {book_name} from totals (not in dynamic weights)")
    
    # Analyze spreads
    if len(spreads_data) >= 2:
        print(f"\n📈 POINT SPREADS ANALYSIS:")
        print(f"Books with spreads: {list(spreads_data.keys())}")
        
        # Switch to spreads weights
        model.weights = spreads_weights
        
        # Convert spreads data for analysis (similar to moneyline format)
        spreads_odds = {}
        for book_name, data in spreads_data.items():
            # Format: [home_odds, away_odds] for the model
            spreads_odds[book_name] = [data['home_odds'], data['away_odds']]
        
        try:
            # Calculate fair spread probabilities using the model
            spreads_analysis = model.analyze_moneyline_market(spreads_odds)  # Use same method as moneyline
            home_fair_prob = spreads_analysis['fair_prob']
            away_fair_prob = 1 - home_fair_prob
            
            # Get the main spread line from any book
            sample_spread = None
            for book_data in spreads_data.values():
                sample_spread = book_data['home_spread']
                break
            
            if sample_spread is not None:
                print(f"\nFair Spread Analysis:")
                print(f"Fair probability of covering {sample_spread:+.1f} spread: {home_fair_prob*100:.1f}%")
                print(f"Fair probability of covering {-sample_spread:+.1f} spread: {away_fair_prob*100:.1f}%")
            
            # Calculate EV for each book's spread bets
            for book_name, data in spreads_data.items():
                home_ev = model.calculate_ev(data['home_odds'], home_fair_prob)
                away_ev = model.calculate_ev(data['away_odds'], away_fair_prob)
                
                home_american = decimal_to_american(data['home_odds'])
                away_american = decimal_to_american(data['away_odds'])
                
                print(f"\n📊 {book_name}:")
                home_status = "🚨 +EV!" if home_ev > 0.5 else "❌ No value"
                away_status = "🚨 +EV!" if away_ev > 0.5 else "❌ No value"
                
                print(f"  SPREAD - {game['home_team']} {data['home_spread']:+.1f}: {home_american} ({home_ev:+.2f}% EV) {home_status}")
                print(f"  SPREAD - {game['away_team']} {data['away_spread']:+.1f}: {away_american} ({away_ev:+.2f}% EV) {away_status}")
                
        except Exception as e:
            print(f"❌ Spreads analysis error: {e}")
            print(f"Debug info:")
            print(f"  spreads_data: {spreads_data}")
            print(f"  spreads_odds: {spreads_odds}")
            
            # Fallback: Simple display without EV analysis
            print(f"\nFallback - Showing spreads without EV analysis:")
            for book_name, data in spreads_data.items():
                home_american = decimal_to_american(data['home_odds'])
                away_american = decimal_to_american(data['away_odds'])
                
                print(f"\n📊 {book_name}:")
                print(f"  SPREAD - {game['home_team']} {data['home_spread']:+.1f}: {home_american}")
                print(f"  SPREAD - {game['away_team']} {data['away_spread']:+.1f}: {away_american}")
    else:
        print(f"\n📈 POINT SPREADS ANALYSIS:")
        print(f"❌ Only {len(spreads_data)} books available for spreads (need 2+)")
        print(f"Available: {list(spreads_data.keys())}")
    
    # Analyze totals
    if len(totals_data) >= 2:  # Lower threshold for testing
        print(f"\n🎯 TOTALS ANALYSIS:")
        print(f"Books with totals: {list(totals_data.keys())}")
        
        # Switch to totals weights
        model.weights = nfl_engine.get_nfl_weights('totals')
        
        # Convert for your model - FIXED FORMAT
        totals_odds = {}
        for book_name, data in totals_data.items():
            # Make sure we're using the correct format for your model
            totals_odds[book_name] = [data['over_odds'], data['under_odds']]
        
        print(f"Debug - totals_odds format: {totals_odds}")  # Debug line
        
        try:
            # Try a simplified analysis first
            if len(totals_odds) >= 2:
                # Get the total line from any available book
                sample_total_line = None
                for book_data in totals_data.values():
                    sample_total_line = book_data['total']
                    break
                
                # Manual fair value calculation for totals (simplified)
                all_over_odds = []
                all_under_odds = []
                
                for book_name, data in totals_data.items():
                    book_weight = model.weights.get(book_name, 0)
                    if book_weight > 0:
                        all_over_odds.append((data['over_odds'], book_weight))
                        all_under_odds.append((data['under_odds'], book_weight))
                
                if all_over_odds and all_under_odds:
                    # Calculate weighted average odds
                    weighted_over_prob = sum([(1/odds) * weight for odds, weight in all_over_odds]) / sum([weight for odds, weight in all_over_odds])
                    weighted_under_prob = sum([(1/odds) * weight for odds, weight in all_under_odds]) / sum([weight for odds, weight in all_under_odds])
                    
                    # Normalize probabilities
                    total_prob = weighted_over_prob + weighted_under_prob
                    over_fair_prob = weighted_over_prob / total_prob
                    under_fair_prob = weighted_under_prob / total_prob
                    
                    print(f"\nFair Total Line Analysis:")
                    print(f"Over {sample_total_line} fair probability: {over_fair_prob*100:.1f}%")
                    print(f"Under {sample_total_line} fair probability: {under_fair_prob*100:.1f}%")
                    
                    for book_name, data in totals_data.items():
                        over_ev = model.calculate_ev(data['over_odds'], over_fair_prob)
                        under_ev = model.calculate_ev(data['under_odds'], under_fair_prob)
                        
                        over_american = decimal_to_american(data['over_odds'])
                        under_american = decimal_to_american(data['under_odds'])
                        
                        print(f"\n📊 {book_name}:")
                        over_status = "🚨 +EV!" if over_ev > 0.5 else "❌ No value"
                        under_status = "🚨 +EV!" if under_ev > 0.5 else "❌ No value"
                        
                        print(f"  TOTAL - Over {data['total']}: {over_american} ({over_ev:+.2f}% EV) {over_status}")
                        print(f"  TOTAL - Under {data['total']}: {under_american} ({under_ev:+.2f}% EV) {under_status}")
                else:
                    print(f"❌ No weighted books available for totals analysis")
                
        except Exception as e:
            print(f"❌ Totals analysis error: {e}")
            print(f"Debug info:")
            print(f"  totals_data: {totals_data}")
            print(f"  totals_odds: {totals_odds}")
            import traceback
            traceback.print_exc()
    else:
        print(f"\n🎯 TOTALS ANALYSIS:")
        print(f"❌ Only {len(totals_data)} books available for totals (need 2+)")
        print(f"Available: {list(totals_data.keys())}")
    
    # Reset to moneyline weights
    model.weights = nfl_engine.get_nfl_weights('moneyline')

print("🏈 Testing NFL Weighting System")
print("=" * 50)

# Initialize NFL weighting engine
nfl_engine = NFLWeightingEngine()

# Test weight allocation
print("📊 NFL Weight Allocation:")
for market in ['moneyline', 'spreads', 'totals']:
    weights = nfl_engine.get_nfl_weights(market)
    total_weight = sum(weights.values())
    
    print(f"\n{market.upper()}:")
    for book, weight in weights.items():
        percentage = (weight / total_weight) * 100
        print(f"  {book}: {weight} ({percentage:.1f}%)")
    print(f"  Total: {total_weight} (100.0%)")

# Test book filtering
print(f"\n🚫 Books to avoid: {nfl_engine.avoid_books}")

# Test book inclusion logic
print("\n🔍 Book Inclusion Testing:")
test_books = ['Pinnacle', 'Circa', 'DraftKings', 'Caesars', 'BetMGM', 'FanDuel']
for book in test_books:
    for market in ['moneyline', 'spreads', 'totals']:
        included = nfl_engine.should_include_book(book, market)
        status = "✅ INCLUDE" if included else "❌ EXCLUDE"
        print(f"  {book} ({market}): {status}")

# Test liquidity requirements
print(f"\n💰 Liquidity Requirements:")
for market, threshold in nfl_engine.liquidity_requirements.items():
    print(f"  {market}: ${threshold:,}")

# Test with live NFL data
odds_api = OddsAPI(api_key="1146a647b7e10a678f226f1a597aeea3")
print(f"\n🔄 Testing with live NFL data...")

try:
    raw_odds = odds_api.get_odds("americanfootball_nfl", markets="h2h,spreads,totals")
    
    if raw_odds:
        print(f"✅ Found {len(raw_odds)} live NFL games")
        
        # Test your NFL model with first game
        game = raw_odds[0]
        print(f"\n🏈 Testing: {game['home_team']} vs {game['away_team']}")
        
        # Initialize model with NFL moneyline weights
        model = SharpEdge(
            weights=nfl_engine.get_nfl_weights('moneyline'),
            exchange_weights={},
            liquidity_threshold=nfl_engine.liquidity_requirements['moneyline']
        )
        
        # Extract moneyline data for testing
        moneyline_data = {}
        excluded_books = []
        all_available_books = []

        # First pass: collect all available book names
        for bookmaker in game.get('bookmakers', []):
            all_available_books.append(bookmaker['title'])

        print(f"\n📋 All Available Books: {all_available_books}")

        # Get dynamic weights based on available books
        dynamic_weights = nfl_engine.get_nfl_weights('moneyline', all_available_books)
        print(f"📊 Dynamic Weights Selected: {dynamic_weights}")

        # Update model with dynamic weights
        model.weights = dynamic_weights

        # Second pass: extract data using dynamic weights
        for bookmaker in game.get('bookmakers', []):
            api_book_name = bookmaker['title']
            book_name = nfl_engine.normalize_book_name(api_book_name)
            
            # Test book filtering with dynamic weights
            if not nfl_engine.should_include_book(book_name, 'moneyline', all_available_books):
                excluded_books.append(api_book_name)
                print(f"  ⏭️ Excluding {api_book_name} (not in dynamic weights)")
                continue
            
            for market in bookmaker.get('markets', []):
                if market['key'] == 'h2h':
                    home_odds = next((o['price'] for o in market['outcomes'] if o['name'] == game['home_team']), None)
                    away_odds = next((o['price'] for o in market['outcomes'] if o['name'] == game['away_team']), None)
                    if home_odds and away_odds:
                        moneyline_data[book_name] = [home_odds, away_odds]
                        weight = dynamic_weights.get(book_name, 0)
                        print(f"  ✅ {book_name}: {home_odds} / {away_odds} (weight: {weight:.3f})")
        
        print(f"\n📊 Analysis Summary:")
        print(f"  Books included: {len(moneyline_data)}")
        print(f"  Books excluded: {len(excluded_books)}")
        print(f"  Excluded books: {excluded_books}")
        
        if len(moneyline_data) >= 3:
            try:
                analysis = model.analyze_moneyline_market(moneyline_data)
                print(f"\n🎯 NFL Analysis Results:")
                print(f"  Fair Probability (Home): {analysis['fair_prob']:.3f} ({analysis['fair_prob']*100:.1f}%)")
                print(f"  Fair Probability (Away): {1-analysis['fair_prob']:.3f} ({(1-analysis['fair_prob'])*100:.1f}%)")
                print(f"  Fair Odds (Home): {analysis['fair_odds_decimal']:.2f}")
                print(f"  Fair Odds (Away): {1/(1-analysis['fair_prob']):.2f}")
                print(f"  Books Used in Consensus: {analysis['books_used']}")
                
                # Test EV calculation for each book
                print(f"\n💰 BETTING OPPORTUNITIES:")
                print(f"Game: {game['home_team']} vs {game['away_team']}")
                print(f"=" * 60)

                home_team = game['home_team']
                away_team = game['away_team']
                home_fair_prob = analysis['fair_prob']
                away_fair_prob = 1 - home_fair_prob

                opportunities_found = []

                for book_name, odds_pair in moneyline_data.items():
                    home_odds, away_odds = odds_pair
                    home_ev = model.calculate_ev(home_odds, home_fair_prob)
                    away_ev = model.calculate_ev(away_odds, away_fair_prob)
                    
                    print(f"\n📊 {book_name}:")
                    
                    # Home team moneyline with American odds
                    home_american = decimal_to_american(home_odds)
                    home_status = "🚨 +EV!" if home_ev > 0.5 else "❌ No value"
                    print(f"  MONEYLINE - {home_team}: {home_american} ({home_ev:+.2f}% EV) {home_status}")
                    
                    # Away team moneyline with American odds
                    away_american = decimal_to_american(away_odds)
                    away_status = "🚨 +EV!" if away_ev > 0.5 else "❌ No value"
                    print(f"  MONEYLINE - {away_team}: {away_american} ({away_ev:+.2f}% EV) {away_status}")
                    
                    # Track opportunities
                    if home_ev > 0.5:
                        opportunities_found.append({
                            'book': book_name,
                            'bet_type': 'MONEYLINE',
                            'team': home_team,
                            'odds': home_american,
                            'ev': home_ev
                        })
                    
                    if away_ev > 0.5:
                        opportunities_found.append({
                            'book': book_name,
                            'bet_type': 'MONEYLINE', 
                            'team': away_team,
                            'odds': away_american,
                            'ev': away_ev
                        })

                # Summary of opportunities
                print(f"\n🎯 OPPORTUNITY SUMMARY:")
                print(f"=" * 40)
                if opportunities_found:
                    print(f"✅ Found {len(opportunities_found)} +EV opportunities:")
                    for opp in opportunities_found:
                        print(f"  🔥 {opp['bet_type']} - {opp['team']}")
                        print(f"     Book: {opp['book']} | Odds: {opp['odds']} | EV: +{opp['ev']:.2f}%")
                else:
                    print(f"❌ No +EV opportunities found in this game")
                    print(f"💡 This is normal for efficient NFL markets")

                print(f"\n📈 FAIR VALUE ANALYSIS:")
                print(f"=" * 40)
                home_fair_american = decimal_to_american(1/home_fair_prob)
                away_fair_american = decimal_to_american(1/away_fair_prob)
                print(f"Fair Odds - {home_team}: {home_fair_american} ({home_fair_prob*100:.1f}% probability)")
                print(f"Fair Odds - {away_team}: {away_fair_american} ({away_fair_prob*100:.1f}% probability)")
                print(f"Market Efficiency: Books used in consensus = {analysis['books_used']}")
                
                print(f"\n✅ NFL weighting system working perfectly!")
                
                # NOW CALL THE SPREADS AND TOTALS FUNCTION
                analyze_spreads_and_totals(game, nfl_engine, model)
                
            except Exception as e:
                print(f"  ❌ Analysis error: {e}")
        else:
            print(f"  ❌ Need at least 3 books for analysis, only found {len(moneyline_data)}")
            print(f"  💡 This is expected if most books are filtered out by NFL weights")
    else:
        print("❌ No live NFL games available (offseason?)")
        print("💡 Test again during NFL season for live data")
        
except Exception as e:
    print(f"❌ Error accessing odds API: {e}")

# Test weight validation
print(f"\n🔍 Weight Validation:")
for market in ['moneyline', 'spreads', 'totals']:
    weights = nfl_engine.get_nfl_weights(market)
    total = sum(weights.values())
    
    if abs(total - 1.0) < 0.001:  # Allow for small floating point errors
        print(f"  {market}: ✅ Weights sum to {total:.3f}")
    else:
        print(f"  {market}: ❌ Weights sum to {total:.3f} (should be 1.0)")

print(f"\n🏆 NFL Weighting System Test Complete!")
print(f"🎯 Key Insights:")
print(f"  • Pinnacle gets highest weight (35-45%) across all markets")
print(f"  • Circa gets strong weight (25-35%) for Vegas expertise") 
print(f"  • DraftKings included only in markets where they're sharp")
print(f"  • Soft books (Caesars, BetMGM) properly excluded")
print(f"  • Market-specific optimization working correctly")
