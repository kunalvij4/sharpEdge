import React, { useState, useMemo } from 'react';
import { ChevronDown, ChevronUp, Trophy, Calendar, Filter, Search } from 'lucide-react';
import { MarketResponse, MatchData, MoneylineOdds, SpreadOdds, TotalOdds, SpreadOddsDetails, TotalOddsDetails } from '../types';

// Mock Data provided by user
const MOCK_MARKET_DATA: MarketResponse = {
  "NFL_Arizona Cardinals_vs_Jacksonville Jaguars": {
    "away_team": "Jacksonville Jaguars",
    "commence_time": "2025-11-23T21:05:00Z",
    "home_team": "Arizona Cardinals",
    "markets": {
      "moneyline": {
        "odds_data": {
          "BetMGM": [2.4, 1.61],
          "BetOnline": [2.35, 1.65],
          "BetRivers": [2.32, 1.6],
          "BetUS": [2.34, 1.65],
          "Bovada": [2.3, 1.67],
          "DraftKings": [2.24, 1.68],
          "FanDuel": [2.34, 1.63],
          "LowVig.ag": [2.35, 1.65],
          "MyBookie": [2.26, 1.65]
        }
      },
      "spreads": {
        "odds_data": {
          "BetMGM": { "away_odds": 2.0, "away_point": -3.0, "home_odds": 1.83, "home_point": 3.0 },
          "BetOnline": { "away_odds": 1.95, "away_point": -3.0, "home_odds": 1.87, "home_point": 3.0 },
          "BetRivers": { "away_odds": 1.89, "away_point": -3.0, "home_odds": 1.88, "home_point": 3.0 },
          "BetUS": { "away_odds": 1.95, "away_point": -3.0, "home_odds": 1.87, "home_point": 3.0 },
          "Bovada": { "away_odds": 1.83, "away_point": -2.5, "home_odds": 2.0, "home_point": 2.5 },
          "DraftKings": { "away_odds": 1.85, "away_point": -2.5, "home_odds": 1.98, "home_point": 2.5 },
          "FanDuel": { "away_odds": 1.82, "away_point": -2.5, "home_odds": 2.0, "home_point": 2.5 },
          "LowVig.ag": { "away_odds": 2.0, "away_point": -3.0, "home_odds": 1.91, "home_point": 3.0 },
          "MyBookie": { "away_odds": 1.83, "away_point": -2.5, "home_odds": 2.0, "home_point": 2.5 }
        }
      },
      "totals": {
        "odds_data": {
          "BetMGM": { "over_odds": 1.91, "point": 47.5, "under_odds": 1.91 },
          "BetOnline": { "over_odds": 1.91, "point": 47.5, "under_odds": 1.91 },
          "BetRivers": { "over_odds": 1.88, "point": 47.0, "under_odds": 1.89 },
          "BetUS": { "over_odds": 1.91, "point": 47.5, "under_odds": 1.91 },
          "Bovada": { "over_odds": 1.91, "point": 47.5, "under_odds": 1.91 },
          "DraftKings": { "over_odds": 1.93, "point": 47.5, "under_odds": 1.89 },
          "FanDuel": { "over_odds": 1.95, "point": 47.5, "under_odds": 1.87 },
          "LowVig.ag": { "over_odds": 1.93, "point": 47.5, "under_odds": 1.93 },
          "MyBookie": { "over_odds": 1.91, "point": 47.5, "under_odds": 1.91 }
        }
      }
    },
    "sport": "NFL"
  },
  "NFL_Baltimore Ravens_vs_Cincinnati Bengals": {
    "away_team": "Cincinnati Bengals",
    "commence_time": "2025-11-28T01:20:00Z",
    "home_team": "Baltimore Ravens",
    "markets": {
      "moneyline": {
        "odds_data": {
          "BetMGM": [1.27, 4.0],
          "BetRivers": [1.23, 4.1],
          "DraftKings": [1.24, 4.2],
          "MyBookie": [1.24, 3.92]
        }
      },
      "spreads": {
        "odds_data": {
          "BetMGM": { "away_odds": 1.87, "away_point": 7.0, "home_odds": 1.95, "home_point": -7.0 },
          "BetOnline": { "away_odds": 1.95, "away_point": 6.5, "home_odds": 1.87, "home_point": -6.5 },
          "BetRivers": { "away_odds": 1.88, "away_point": 7.5, "home_odds": 1.88, "home_point": -7.5 },
          "BetUS": { "away_odds": 1.95, "away_point": 6.5, "home_odds": 1.87, "home_point": -6.5 },
          "DraftKings": { "away_odds": 1.87, "away_point": 7.5, "home_odds": 1.95, "home_point": -7.5 },
          "LowVig.ag": { "away_odds": 2.0, "away_point": 6.5, "home_odds": 1.91, "home_point": -6.5 },
          "MyBookie": { "away_odds": 1.91, "away_point": 7.5, "home_odds": 1.91, "home_point": -7.5 }
        }
      },
      "totals": {
        "odds_data": {
          "BetMGM": { "over_odds": 1.91, "point": 52.5, "under_odds": 1.91 },
          "BetOnline": { "over_odds": 1.91, "point": 53.0, "under_odds": 1.91 },
          "BetRivers": { "over_odds": 1.92, "point": 51.5, "under_odds": 1.85 },
          "BetUS": { "over_odds": 1.91, "point": 53.0, "under_odds": 1.91 },
          "DraftKings": { "over_odds": 1.95, "point": 53.5, "under_odds": 1.87 },
          "LowVig.ag": { "over_odds": 1.93, "point": 53.0, "under_odds": 1.93 },
          "MyBookie": { "over_odds": 1.91, "point": 51.5, "under_odds": 1.91 }
        }
      }
    },
    "sport": "NFL"
  }
};

const MarketCard: React.FC<{ matchId: string; data: MatchData; selectedBook: string }> = ({ matchId, data, selectedBook }) => {
  const [expanded, setExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState<'moneyline' | 'spreads' | 'totals'>('moneyline');

  // Helper to format date
  const dateStr = new Date(data.commence_time).toLocaleString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });

  const decimalToAmerican = (decimal: number): string => {
    if (!decimal || decimal === 1) return '-';
    let val: number;
    if (decimal >= 2) {
      val = (decimal - 1) * 100;
      return `+${Math.round(val)}`;
    } else {
      val = -100 / (decimal - 1);
      return `${Math.round(val)}`;
    }
  };

  // Calculate display odds (Best vs Selected Book)
  const displayOdds = useMemo(() => {
    if (!data.markets.moneyline) return { home: '-', away: '-', type: 'Best' };
    
    // If a specific book is selected, show that book's odds
    if (selectedBook !== 'All') {
      const bookOdds = data.markets.moneyline.odds_data[selectedBook];
      if (bookOdds) {
        return { 
          home: decimalToAmerican(bookOdds[1]), 
          away: decimalToAmerican(bookOdds[0]), 
          type: selectedBook
        };
      }
      return { home: 'N/A', away: 'N/A', type: selectedBook };
    }

    // Default: Show Best Odds
    const odds = Object.values(data.markets.moneyline.odds_data);
    const bestAway = Math.max(...odds.map(o => o[0]));
    const bestHome = Math.max(...odds.map(o => o[1]));
    return { 
      home: decimalToAmerican(bestHome), 
      away: decimalToAmerican(bestAway), 
      type: 'Best' 
    };
  }, [data.markets.moneyline, selectedBook]);

  // Helper component for the odds grid
  const OddsGrid = ({ type }: { type: 'moneyline' | 'spreads' | 'totals' }) => {
    const market = data.markets[type];
    if (!market) return <div className="p-4 text-zinc-500 text-center">No data available</div>;

    // Filter books based on selection
    const allBooks = Object.keys(market.odds_data);
    const books = selectedBook === 'All' 
      ? allBooks 
      : allBooks.filter(b => b === selectedBook);

    if (books.length === 0) {
      return <div className="p-8 text-center text-zinc-500">No odds available for {selectedBook} in this market.</div>;
    }

    return (
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm text-zinc-400">
          <thead className="bg-zinc-900 text-xs uppercase text-zinc-500">
            <tr>
              <th className="px-4 py-3 font-medium">Bookmaker</th>
              {type === 'moneyline' && (
                <>
                  <th className="px-4 py-3 font-medium text-right">{data.away_team}</th>
                  <th className="px-4 py-3 font-medium text-right">{data.home_team}</th>
                </>
              )}
              {type === 'spreads' && (
                <>
                  <th className="px-4 py-3 font-medium text-right">{data.away_team} (Spread)</th>
                  <th className="px-4 py-3 font-medium text-right">{data.home_team} (Spread)</th>
                </>
              )}
              {type === 'totals' && (
                <>
                  <th className="px-4 py-3 font-medium text-right">Over</th>
                  <th className="px-4 py-3 font-medium text-right">Under</th>
                </>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {books.map((book) => {
              const oddData = market.odds_data[book];
              return (
                <tr key={book} className="hover:bg-zinc-900/50">
                  <td className="px-4 py-3 font-medium text-zinc-300">{book}</td>
                  
                  {type === 'moneyline' && Array.isArray(oddData) && (
                    <>
                      <td className="px-4 py-3 text-right font-mono text-amber-500">{decimalToAmerican(oddData[0])}</td>
                      <td className="px-4 py-3 text-right font-mono text-amber-500">{decimalToAmerican(oddData[1])}</td>
                    </>
                  )}

                  {type === 'spreads' && !Array.isArray(oddData) && (
                    <>
                      <td className="px-4 py-3 text-right">
                        <span className="mr-2 text-zinc-500">{(oddData as SpreadOddsDetails).away_point > 0 ? '+' : ''}{(oddData as SpreadOddsDetails).away_point}</span>
                        <span className="font-mono text-amber-500">{decimalToAmerican((oddData as SpreadOddsDetails).away_odds)}</span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className="mr-2 text-zinc-500">{(oddData as SpreadOddsDetails).home_point > 0 ? '+' : ''}{(oddData as SpreadOddsDetails).home_point}</span>
                        <span className="font-mono text-amber-500">{decimalToAmerican((oddData as SpreadOddsDetails).home_odds)}</span>
                      </td>
                    </>
                  )}

                  {type === 'totals' && !Array.isArray(oddData) && (
                    <>
                      <td className="px-4 py-3 text-right">
                        <span className="mr-2 text-zinc-500">O {(oddData as TotalOddsDetails).point}</span>
                        <span className="font-mono text-amber-500">{decimalToAmerican((oddData as TotalOddsDetails).over_odds)}</span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className="mr-2 text-zinc-500">U {(oddData as TotalOddsDetails).point}</span>
                        <span className="font-mono text-amber-500">{decimalToAmerican((oddData as TotalOddsDetails).under_odds)}</span>
                      </td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <div className="mb-6 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950 transition-all">
      {/* Header / Summary Row */}
      <div 
        className="cursor-pointer bg-zinc-900/40 p-5 hover:bg-zinc-900/80"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          {/* Match Info */}
          <div className="flex items-center gap-4">
            <div className="rounded-lg bg-zinc-900 p-2 text-zinc-500">
               <Trophy size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2 text-xs font-medium text-zinc-500">
                <span className="uppercase tracking-wider">{data.sport}</span>
                <span>•</span>
                <span className="flex items-center gap-1"><Calendar size={12} /> {dateStr}</span>
              </div>
              <h3 className="text-lg font-bold text-zinc-100">
                {data.away_team} <span className="text-zinc-600">@</span> {data.home_team}
              </h3>
            </div>
          </div>

          {/* Quick Odds Preview */}
          <div className="flex items-center gap-4 md:gap-8">
            <div className="text-right">
              <p className="text-xs text-zinc-500">{displayOdds.type} {data.away_team}</p>
              <p className="font-mono text-lg font-bold text-amber-500">{displayOdds.away}</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-zinc-500">{displayOdds.type} {data.home_team}</p>
              <p className="font-mono text-lg font-bold text-amber-500">{displayOdds.home}</p>
            </div>
            <div className="ml-2 text-zinc-500">
              {expanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
            </div>
          </div>
        </div>
      </div>

      {/* Expanded Content */}
      {expanded && (
        <div className="border-t border-zinc-800 bg-zinc-950">
          {/* Tabs */}
          <div className="flex border-b border-zinc-800">
            {(['moneyline', 'spreads', 'totals'] as const).map((tab) => (
              <button
                key={tab}
                onClick={(e) => { e.stopPropagation(); setActiveTab(tab); }}
                className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
                  activeTab === tab
                    ? 'border-b-2 border-amber-500 bg-zinc-900 text-amber-500'
                    : 'text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200'
                }`}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </div>

          {/* Table */}
          <div className="animate-in fade-in slide-in-from-top-2 duration-200">
            <OddsGrid type={activeTab} />
          </div>
        </div>
      )}
    </div>
  );
};

const CurrentMarkets: React.FC = () => {
  const [selectedLeague, setSelectedLeague] = useState<string>('All');
  const [selectedBook, setSelectedBook] = useState<string>('All');

  // Extract unique leagues
  const leagues = useMemo(() => {
    const leagueSet = new Set<string>(['All']);
    Object.values(MOCK_MARKET_DATA).forEach(match => leagueSet.add(match.sport));
    return Array.from(leagueSet);
  }, []);

  // Extract unique books from all markets
  const books = useMemo(() => {
    const bookSet = new Set<string>(['All']);
    Object.values(MOCK_MARKET_DATA).forEach(match => {
      if (match.markets.moneyline?.odds_data) Object.keys(match.markets.moneyline.odds_data).forEach(k => bookSet.add(k));
      if (match.markets.spreads?.odds_data) Object.keys(match.markets.spreads.odds_data).forEach(k => bookSet.add(k));
      if (match.markets.totals?.odds_data) Object.keys(match.markets.totals.odds_data).forEach(k => bookSet.add(k));
    });
    return Array.from(bookSet).sort();
  }, []);

  // Filter matches based on selected league
  const filteredMatches = useMemo(() => {
    return Object.entries(MOCK_MARKET_DATA).filter(([_, data]) => {
      return selectedLeague === 'All' || data.sport === selectedLeague;
    });
  }, [selectedLeague]);

  return (
    <div className="min-h-screen bg-black px-4 py-8 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-5xl">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-white">Current Markets</h1>
          <p className="mt-2 text-zinc-400">Real-time odds from all major sportsbooks. Filter to find your edge.</p>
        </div>
        
        {/* Filter Controls */}
        <div className="mb-8 flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          {/* League Filter (Tabs/Pills) */}
          <div className="flex-1 overflow-x-auto pb-2 md:pb-0 hide-scrollbar">
            <div className="flex gap-2">
              {leagues.map((league) => (
                <button
                  key={league}
                  onClick={() => setSelectedLeague(league)}
                  className={`rounded-full px-4 py-2 text-sm font-medium transition-colors whitespace-nowrap ${
                    selectedLeague === league
                      ? 'bg-amber-500 text-black'
                      : 'bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-white'
                  }`}
                >
                  {league}
                </button>
              ))}
            </div>
          </div>

          {/* Sportsbook Filter (Dropdown) */}
          <div className="relative min-w-[200px]">
             <div className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500">
                <Search size={16} />
             </div>
             <select
               value={selectedBook}
               onChange={(e) => setSelectedBook(e.target.value)}
               className="w-full appearance-none rounded-lg bg-zinc-900 py-2.5 pl-10 pr-10 text-sm font-medium text-white ring-1 ring-zinc-800 transition-all focus:outline-none focus:ring-2 focus:ring-amber-500"
             >
               <option value="All">All Sportsbooks</option>
               {books.filter(b => b !== 'All').map(book => (
                 <option key={book} value={book}>{book}</option>
               ))}
             </select>
             <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-zinc-500">
               <ChevronDown size={16} />
             </div>
          </div>
        </div>

        {/* Matches List */}
        <div className="space-y-4">
          {filteredMatches.length > 0 ? (
            filteredMatches.map(([key, data]) => (
              <MarketCard key={key} matchId={key} data={data} selectedBook={selectedBook} />
            ))
          ) : (
            <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-12 text-center">
               <Filter className="mx-auto h-12 w-12 text-zinc-600 mb-4" />
               <h3 className="text-lg font-medium text-white">No matches found</h3>
               <p className="text-zinc-500 mt-2">Try adjusting your filters to see more results.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CurrentMarkets;