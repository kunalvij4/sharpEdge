-- SharpEdge EV Database Schema

-- Table to store raw odds data from each sportsbook
CREATE TABLE IF NOT EXISTS odds_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL,
    book_name TEXT NOT NULL,
    odds_for REAL NOT NULL,
    odds_against REAL NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    sport TEXT,
    market_type TEXT, -- 'moneyline', 'spread', 'total', 'props'
    team_home TEXT,
    team_away TEXT
);

-- Table to store calculated fair odds
CREATE TABLE IF NOT EXISTS fair_odds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL UNIQUE,
    fair_prob REAL NOT NULL,
    fair_odds_decimal REAL NOT NULL,
    fair_odds_american TEXT NOT NULL,
    books_used INTEGER,
    exchanges_used INTEGER,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    sport TEXT,
    market_type TEXT
);

-- Table to store EV opportunities
CREATE TABLE IF NOT EXISTS ev_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL,
    book_name TEXT NOT NULL,
    offered_odds REAL NOT NULL,
    fair_odds REAL NOT NULL,
    fair_prob REAL NOT NULL,
    ev_percentage REAL NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    sport TEXT,
    market_type TEXT,
    is_positive_ev BOOLEAN DEFAULT 1
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_odds_timestamp ON odds_data(timestamp);
CREATE INDEX IF NOT EXISTS idx_odds_market ON odds_data(market_id);
CREATE INDEX IF NOT EXISTS idx_ev_timestamp ON ev_bets(timestamp);
CREATE INDEX IF NOT EXISTS idx_ev_positive ON ev_bets(is_positive_ev, ev_percentage);