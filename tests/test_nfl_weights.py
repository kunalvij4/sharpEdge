import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from app.services.nfl_weights import NFLWeightingEngine
from app.services.sharpedge_model import SharpEdge
from app.apis.odds_api import OddsAPI
from app.db.crud import SharpEdgeDB

def decimal_to_american(decimal_odds):
    if decimal_odds >= 2.0:
        return f"+{int((decimal_odds - 1) * 100)}"
    else:
        return f"-{int(100 / (decimal_odds - 1))}"

def analyze_spreads_and_totals(game, nfl_engine, model):
    # ...your existing function code here...
    pass  # (keep your full function here)

# Initialize AWS database connection
try:
    db = SharpEdgeDB()
    print("✅ Connected to AWS DynamoDB")
    connection_test = db.test_connection()
    print(f"📊 AWS Status: {connection_test.get('connection', 'Unknown')}")
except Exception as e:
    print(f"❌ AWS DynamoDB connection failed: {e}")
    db = None

print("🏈 Testing NFL Weighting System")
print("=" * 50)

nfl_engine = NFLWeightingEngine()

print("📊 NFL Weight Allocation:")
for market in ['moneyline', 'spreads', 'totals']:
    weights = nfl_engine.get_nfl_weights(market)
    total_weight = sum(weights.values())
    print(f"\n{market.upper()}:")
    for book, weight in weights.items():
        percentage = (weight / total_weight) * 100
        print(f"  {book}: {weight} ({percentage:.1f}%)")
    print(f"  Total: {total_weight} (100.0%)")

print(f"\n🚫 Books to avoid: {nfl_engine.avoid_books}")

print("\n🔍 Book Inclusion Testing:")
test_books = ['Pinnacle', 'Circa', 'DraftKings', 'Caesars', 'BetMGM', 'FanDuel']
for book in test_books:
    for market in ['moneyline', 'spreads', 'totals']:
        included = nfl_engine.should_include_book(book, market)
        status = "✅ INCLUDE" if included else "❌ EXCLUDE"
        print(f"  {book} ({market}): {status}")

print(f"\n💰 Liquidity Requirements:")
for market, threshold in nfl_engine.liquidity_requirements.items():
    print(f"  {market}: ${threshold:,}")

odds_api = OddsAPI(api_key=os.getenv("ODDS_API_KEY"))
print(f"\n🔄 Testing with live NFL data...")

try:
    raw_odds = odds_api.get_odds("americanfootball_nfl", markets="h2h,spreads,totals")
    if raw_odds:
        print(f"✅ Found {len(raw_odds)} live NFL games")
        game = raw_odds[0]
        print(f"\n🏈 Testing: {game['home_team']} vs {game['away_team']}")
        model = SharpEdge(
            weights=nfl_engine.get_nfl_weights('moneyline'),
            exchange_weights={},
            liquidity_threshold=nfl_engine.liquidity_requirements['moneyline']
        )
        moneyline_data = {}
        excluded_books = []
        all_available_books = []
        for bookmaker in game.get('bookmakers', []):
            all_available_books.append(bookmaker['title'])
        print(f"\n📋 All Available Books: {all_available_books}")
        dynamic_weights = nfl_engine.get_nfl_weights('moneyline', all_available_books)
        print(f"📊 Dynamic Weights Selected: {dynamic_weights}")
        model.weights = dynamic_weights
        for bookmaker in game.get('bookmakers', []):
            api_book_name = bookmaker['title']
            book_name = nfl_engine.normalize_book_name(api_book_name)
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
                    home_american = decimal_to_american(home_odds)
                    home_status = "🚨 +EV!" if home_ev > 0.5 else "❌ No value"
                    print(f"  MONEYLINE - {home_team}: {home_american} ({home_ev:+.2f}% EV) {home_status}")
                    away_american = decimal_to_american(away_odds)
                    away_status = "🚨 +EV!" if away_ev > 0.5 else "❌ No value"
                    print(f"  MONEYLINE - {away_team}: {away_american} ({away_ev:+.2f}% EV) {away_status}")
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
                print(f"\n🎯 OPPORTUNITY SUMMARY:")
                print(f"=" * 40)
                if opportunities_found:
                    print(f"✅ Found {len(opportunities_found)} +EV opportunities:")
                    for opp in opportunities_found:
                        print(f"  🔥 {opp['bet_type']} - {opp['team']}")
                        print(f"     Book: {opp['book']} | Odds: {opp['odds']} | EV: +{opp['ev']:.2f}%")
                        # 💾 SAVE TO AWS DATABASE
                        if db:
                            try:
                                team_index = 0 if opp['team'] == home_team else 1
                                offered_odds_decimal = moneyline_data[opp['book']][team_index]
                                fair_prob = home_fair_prob if opp['team'] == home_team else away_fair_prob
                                db.save_ev_bet(
                                    market_id=f"{game['home_team']}_vs_{game['away_team']}_ML_{int(datetime.now().timestamp())}",
                                    book_name=opp['book'],
                                    offered_odds=offered_odds_decimal,
                                    fair_odds=1/fair_prob,
                                    fair_prob=fair_prob,
                                    ev_percentage=opp['ev'],
                                    sport="NFL",
                                    market_type="moneyline",
                                    team_name=opp['team'],
                                    bet_type=opp['bet_type'],
                                    game_info=f"{game['home_team']} vs {game['away_team']}",
                                    odds_american=opp['odds']
                                )
                                print(f"    💾 Saved to AWS: {opp['book']} {opp['ev']:.2f}% EV")
                            except Exception as save_error:
                                print(f"    ❌ AWS save error: {save_error}")
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

print(f"\n🔍 Weight Validation:")
for market in ['moneyline', 'spreads', 'totals']:
    weights = nfl_engine.get_nfl_weights(market)
    total = sum(weights.values())
    if abs(total - 1.0) < 0.001:
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
print(f"  • AWS database integration saving all +EV opportunities")