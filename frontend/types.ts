export interface MoneylineOdds {
  [bookmaker: string]: number[]; // [Away, Home] assumption
}

export interface SpreadOddsDetails {
  away_odds: number;
  away_point: number;
  home_odds: number;
  home_point: number;
}

export interface SpreadOdds {
  [bookmaker: string]: SpreadOddsDetails;
}

export interface TotalOddsDetails {
  over_odds: number;
  under_odds: number;
  point: number;
}

export interface TotalOdds {
  [bookmaker: string]: TotalOddsDetails;
}

export interface MarketData {
  moneyline?: {
    odds_data: MoneylineOdds;
  };
  spreads?: {
    odds_data: SpreadOdds;
  };
  totals?: {
    odds_data: TotalOdds;
  };
}

export interface MatchData {
  away_team: string;
  home_team: string;
  commence_time: string;
  sport: string;
  markets: MarketData;
}

export interface MarketResponse {
  [key: string]: MatchData;
}
