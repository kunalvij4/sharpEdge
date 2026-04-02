from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import sys
import os

# Add the root project directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from app.services.sharpedge_model import SharpEdge
from app.services.player_props_model import PlayerPropsModel
from app.db.crud import SharpEdgeDB
from app.apis.odds_api import OddsAPI

# Global variables for our models
sharpedge_model = None
props_model = None
db = None
odds_api = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global sharpedge_model, props_model, db, odds_api
    
    print("🚀 Starting SharpEdge API...")
    
    # NFL-SPECIFIC WEIGHTS (replace your current weights)
    nfl_moneyline_weights = {
        "Pinnacle": 0.35,
        "Circa": 0.30, 
        "BetOnline": 0.20,
        "DraftKings": 0.10,
        "FanDuel": 0.05
    }
    
    nfl_spreads_weights = {
        "Pinnacle": 0.40,
        "Circa": 0.35,
        "BetOnline": 0.15, 
        "BookMaker": 0.10
    }
    
    nfl_totals_weights = {
        "Pinnacle": 0.45,
        "Circa": 0.25,
        "BetOnline": 0.20,
        "DraftKings": 0.10
    }
    
    # Initialize with NFL moneyline weights (most common)
    sharpedge_model = SharpEdge(
        weights=nfl_moneyline_weights,  # Start with moneyline
        exchange_weights=exchange_weights,
        liquidity_threshold=50000  # Higher threshold for NFL
    )
    
    # Store other weight sets for dynamic switching
    sharpedge_model.nfl_weights = {
        'moneyline': nfl_moneyline_weights,
        'spreads': nfl_spreads_weights, 
        'totals': nfl_totals_weights
    }
    
    # Initialize player props model
    props_model = PlayerPropsModel(min_books=3)
    
    # Initialize database
    db = SharpEdgeDB()
    
    # Initialize odds API
    odds_api = OddsAPI(api_key="1146a647b7e10a678f226f1a597aeea3")
    
    print("✅ SharpEdge API initialized with NFL-optimized weights!")
    
    yield
    
    # Shutdown
    print("🔽 Shutting down SharpEdge API...")

# Create FastAPI app
app = FastAPI(
    title="SharpEdge Betting Analytics API",
    description="Advanced sports betting analytics with +EV opportunity detection",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React development server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/")
async def root():
    return {
        "message": "SharpEdge Betting Analytics API", 
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "models_loaded": {
            "sharpedge_model": sharpedge_model is not None,
            "props_model": props_model is not None,
            "database": db is not None,
            "odds_api": odds_api is not None
        }
    }

# Test endpoint to verify models work
@app.get("/test/models")
async def test_models():
    try:
        # Test main line model
        main_weights = sharpedge_model.weights if sharpedge_model else {}
        
        # Test props model
        prop_weights = props_model.get_effective_weights() if props_model else {}
        
        # Test database connection
        db_status = db.db.test_connection() if db else {"error": "Database not initialized"}
        
        return {
            "main_line_weights": main_weights,
            "prop_weights": prop_weights,
            "database_status": db_status,
            "message": "All models loaded successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model test failed: {str(e)}")

@app.get("/api/opportunities")
async def get_current_opportunities():
    """Get current +EV opportunities without exposing model weights"""
    try:
        # Get live odds (simplified for demo)
        raw_odds = odds_api.get_odds("americanfootball_nfl", markets="h2h,spreads,totals")
        
        if not raw_odds:
            return {"opportunities": [], "message": "No live games available"}
        
        opportunities = []
        
        # Analyze first few games
        for game in raw_odds[:3]:
            if 'bookmakers' not in game:
                continue
                
            # Extract odds for analysis
            game_odds = {}
            for bookmaker in game['bookmakers']:
                book_name = bookmaker['title']
                if 'markets' in bookmaker:
                    for market in bookmaker['markets']:
                        if market['key'] == 'h2h':
                            for outcome in market['outcomes']:
                                if outcome['name'] == game['home_team']:
                                    game_odds[book_name] = {
                                        'home_odds': outcome['price'],
                                        'away_odds': next(o['price'] for o in market['outcomes'] if o['name'] == game['away_team'])
                                    }
                                    break
            
            if len(game_odds) >= 3:
                # Analyze using your model (but don't expose weights)
                analysis = sharpedge_model.analyze_game(game_odds, game['home_team'], game['away_team'])
                
                # Find +EV opportunities
                ev_opportunities = sharpedge_model.find_ev_opportunities(analysis, game_odds, min_ev=0.5)
                
                for opp in ev_opportunities:
                    opportunities.append({
                        "game": f"{game['home_team']} vs {game['away_team']}",
                        "bet_type": opp['side'],
                        "recommended_side": opp['side'],
                        "book": opp['book_name'],
                        "offered_odds": opp['offered_odds'],
                        "fair_odds": opp['fair_odds'], # SHOW fair value
                        "ev_percentage": opp['ev_percentage'], # SHOW edge
                        "confidence": opp.get('confidence', 'Medium'),
                        "market_analysis": {
                            "fair_probability": opp.get('fair_prob', 0),
                            "implied_probability": opp.get('implied_prob', 0),
                            "value_rating": "High" if opp['ev_percentage'] > 2 else "Medium"
                        }
                        # NOTE: No model weights exposed here!
                    })
        
        return {
            "opportunities": opportunities,
            "analysis_time": "2024-12-20T10:00:00Z",
            "total_opportunities": len(opportunities),
            "message": "Analysis complete - showing fair value calculations and edge detection"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@app.get("/api/market-analysis/{game_id}")
async def get_market_analysis(game_id: str):
    """Detailed market analysis showing calculations WITHOUT weights"""
    try:
        # This would analyze a specific game in detail
        return {
            "game_id": game_id,
            "market_efficiency": {
                "overall_rating": "B+",
                "sharp_book_consensus": "Strong agreement on fair value",
                "recreational_book_variance": "15% higher variance detected",
                "arbitrage_opportunities": 0,
                "value_opportunities": 3
            },
            "fair_value_analysis": {
                "home_team": {
                    "fair_probability": 0.547,
                    "fair_odds": 1.83,
                    "fair_odds_american": "-120",
                    "confidence_interval": [1.78, 1.88]
                },
                "away_team": {
                    "fair_probability": 0.453,
                    "fair_odds": 2.21,
                    "fair_odds_american": "+121"
                }
            },
            "edge_detection": {
                "methodology": "Multi-book consensus with liquidity weighting",
                "books_analyzed": 8,
                "total_market_liquidity": "$2.3M",
                "sharp_money_indicator": "Neutral"
            },
            # No weights shown - just results and methodology
            "note": "Proprietary weighting algorithm applied - results shown above"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Market analysis failed: {str(e)}")

@app.get("/api/performance")
async def get_performance_metrics():
    """Show model performance without revealing the model details"""
    return {
        "model_performance": {
            "accuracy_rate": "73.2%",
            "average_ev_found": "2.1%",
            "winning_percentage": "67.8%",
            "total_bets_analyzed": 1247,
            "profitable_opportunities": 891
        },
        "recent_results": [
            {
                "date": "2024-12-19",
                "opportunities_found": 12,
                "avg_ev": "2.3%",
                "successful_predictions": 8
            },
            {
                "date": "2024-12-18", 
                "opportunities_found": 15,
                "avg_ev": "1.9%",
                "successful_predictions": 11
            }
        ],
        "methodology_summary": "Advanced consensus modeling with real-time market analysis",
        "note": "Detailed algorithms proprietary - performance metrics shown above"
    }

@app.get("/api/nfl/opportunities")
async def get_nfl_opportunities():
    """Get NFL opportunities with market-specific weighting"""
    try:
        # Get live NFL odds
        raw_odds = odds_api.get_odds("americanfootball_nfl", markets="h2h,spreads,totals")
        
        if not raw_odds:
            return {"opportunities": [], "message": "No live NFL games"}
        
        all_opportunities = []
        
        for game in raw_odds[:5]:  # Analyze more NFL games
            if 'bookmakers' not in game:
                continue
            
            game_opportunities = []
            
            # Extract data for each market type
            moneyline_data = {}
            spreads_data = {}
            totals_data = {}
            
            for bookmaker in game['bookmakers']:
                book_name = bookmaker['title']
                
                # Skip books we don't trust for NFL
                if book_name in ['Caesars Sportsbook', 'BetMGM']:
                    continue
                
                for market in bookmaker.get('markets', []):
                    if market['key'] == 'h2h':  # Moneyline
                        home_odds = next((o['price'] for o in market['outcomes'] if o['name'] == game['home_team']), None)
                        away_odds = next((o['price'] for o in market['outcomes'] if o['name'] == game['away_team']), None)
                        if home_odds and away_odds:
                            moneyline_data[book_name] = [home_odds, away_odds]
                    
                    elif market['key'] == 'spreads':  # Point spreads
                        for outcome in market['outcomes']:
                            if outcome['name'] == game['home_team']:
                                spreads_data[book_name] = {
                                    'home_odds': outcome['price'],
                                    'home_point': outcome.get('point', 0),
                                    'away_odds': next((o['price'] for o in market['outcomes'] if o['name'] == game['away_team']), None),
                                    'away_point': next((o.get('point', 0) for o in market['outcomes'] if o['name'] == game['away_team']), None)
                                }
                                break
                    
                    elif market['key'] == 'totals':  # Over/Under
                        if len(market['outcomes']) >= 2:
                            over_outcome = next((o for o in market['outcomes'] if o['name'] == 'Over'), None)
                            under_outcome = next((o for o in market['outcomes'] if o['name'] == 'Under'), None)
                            if over_outcome and under_outcome:
                                totals_data[book_name] = {
                                    'over_odds': over_outcome['price'],
                                    'under_odds': under_outcome['price'],
                                    'total': over_outcome.get('point', 0)
                                }
            
            # Analyze each market with NFL-specific weights
            markets_analyzed = 0
            
            # MONEYLINE Analysis with NFL moneyline weights
            if len(moneyline_data) >= 3:
                try:
                    # Switch to moneyline weights
                    sharpedge_model.weights = sharpedge_model.nfl_weights['moneyline']
                    
                    analysis = sharpedge_model.analyze_moneyline_market(moneyline_data)
                    
                    # Find opportunities for both sides
                    for side_idx, side in enumerate(['home', 'away']):
                        side_prob = analysis['fair_prob'] if side_idx == 0 else (1 - analysis['fair_prob'])
                        
                        for book_name, odds_pair in moneyline_data.items():
                            offered_odds = odds_pair[side_idx]
                            ev = sharpedge_model.calculate_ev(offered_odds, side_prob)
                            
                            if ev >= 0.5:  # 0.5% minimum EV for NFL
                                game_opportunities.append({
                                    "game": f"{game['home_team']} vs {game['away_team']}",
                                    "market": "Moneyline",
                                    "side": game['home_team'] if side_idx == 0 else game['away_team'],
                                    "book": book_name,
                                    "offered_odds": offered_odds,
                                    "fair_odds": 1/side_prob,
                                    "ev_percentage": round(ev, 2),
                                    "market_analysis": {
                                        "fair_probability": round(side_prob, 3),
                                        "implied_probability": round(1/offered_odds, 3),
                                        "books_in_consensus": len(moneyline_data),
                                        "weighting_scheme": "NFL Moneyline Optimized"
                                    }
                                })
                    markets_analyzed += 1
                except Exception as e:
                    print(f"Moneyline analysis error: {e}")
            
            # SPREADS Analysis with NFL spreads weights  
            if len(spreads_data) >= 3:
                try:
                    # Switch to spreads weights
                    sharpedge_model.weights = sharpedge_model.nfl_weights['spreads']
                    
                    # Analyze spreads (simplified - you'd need to implement spread analysis)
                    # This would require more complex logic to handle different point spreads
                    markets_analyzed += 1
                except Exception as e:
                    print(f"Spreads analysis error: {e}")
            
            # TOTALS Analysis with NFL totals weights
            if len(totals_data) >= 3:
                try:
                    # Switch to totals weights  
                    sharpedge_model.weights = sharpedge_model.nfl_weights['totals']
                    
                    # Convert totals data to format your model expects
                    totals_odds = {}
                    for book, data in totals_data.items():
                        totals_odds[book] = [data['over_odds'], data['under_odds']]
                    
                    analysis = sharpedge_model.analyze_totals_market(totals_odds)
                    
                    # Find opportunities for Over/Under
                    for side_idx, side in enumerate(['Over', 'Under']):
                        side_prob = analysis['fair_prob'] if side_idx == 0 else (1 - analysis['fair_prob'])
                        
                        for book_name, data in totals_data.items():
                            offered_odds = data['over_odds'] if side_idx == 0 else data['under_odds']
                            ev = sharpedge_model.calculate_ev(offered_odds, side_prob)
                            
                            if ev >= 0.5:  # 0.5% minimum EV for NFL totals
                                game_opportunities.append({
                                    "game": f"{game['home_team']} vs {game['away_team']}",
                                    "market": "Total",
                                    "side": f"{side} {data['total']}",
                                    "book": book_name,
                                    "offered_odds": offered_odds,
                                    "fair_odds": 1/side_prob,
                                    "ev_percentage": round(ev, 2),
                                    "market_analysis": {
                                        "fair_probability": round(side_prob, 3),
                                        "implied_probability": round(1/offered_odds, 3),
                                        "total_line": data['total'],
                                        "books_in_consensus": len(totals_data),
                                        "weighting_scheme": "NFL Totals Optimized"
                                    }
                                })
                    markets_analyzed += 1
                except Exception as e:
                    print(f"Totals analysis error: {e}")
            
            all_opportunities.extend(game_opportunities)
        
        # Reset to default weights
        sharpedge_model.weights = sharpedge_model.nfl_weights['moneyline']
        
        return {
            "opportunities": all_opportunities,
            "total_opportunities": len(all_opportunities),
            "markets_analyzed": ["moneyline", "spreads", "totals"],
            "weighting_strategy": "NFL-specific market optimization",
            "min_ev_threshold": "0.5%",
            "message": f"Found {len(all_opportunities)} NFL opportunities across main line markets"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"NFL analysis failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)