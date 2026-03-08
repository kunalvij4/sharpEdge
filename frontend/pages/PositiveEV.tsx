import React, { useState } from 'react';
import { Percent, TrendingUp, DollarSign, ChevronDown, ChevronUp } from 'lucide-react';

interface BookOdds {
  name: string;
  bet_odds: string;
  opposite_odds: string;
}

interface EVBet {
  id: number;
  sport: string;
  match: string;
  market: string;
  bet: string;
  opposite_bet: string;
  wager_display: string;
  opposite_wager_display: string;
  book: string;
  odds: string;
  ev: number;
  kelly: number;
  time: string;
  other_books: BookOdds[];
}

const MOCK_EV_DATA: EVBet[] = [
  { 
    id: 1, 
    sport: 'NBA', 
    match: 'Lakers @ Warriors', 
    market: 'Player Props', 
    bet: 'LeBron James Over 25.5 Pts', 
    opposite_bet: 'Under 25.5 Pts',
    wager_display: 'Over 25.5',
    opposite_wager_display: 'Under 25.5',
    book: 'DraftKings', 
    odds: '+110', 
    ev: 4.5, 
    kelly: 2.1, 
    time: '7:30 PM',
    other_books: [
      { name: 'DraftKings', bet_odds: '+110', opposite_odds: '-140' },
      { name: 'FanDuel', bet_odds: '-110', opposite_odds: '-110' },
      { name: 'BetMGM', bet_odds: '-115', opposite_odds: '-105' },
      { name: 'Caesars', bet_odds: '-120', opposite_odds: '-110' }
    ]
  },
  { 
    id: 2, 
    sport: 'NFL', 
    match: 'Jaguars @ Cardinals', 
    market: 'Moneyline', 
    bet: 'Jaguars ML', 
    opposite_bet: 'Cardinals ML',
    wager_display: 'Jaguars',
    opposite_wager_display: 'Cardinals',
    book: 'BetMGM', 
    odds: '+140', 
    ev: 3.2, 
    kelly: 1.5, 
    time: 'Sun, 4:05 PM',
    other_books: [
      { name: 'BetMGM', bet_odds: '+140', opposite_odds: '-165' },
      { name: 'DraftKings', bet_odds: '+130', opposite_odds: '-155' },
      { name: 'FanDuel', bet_odds: '+135', opposite_odds: '-160' },
      { name: 'Bovada', bet_odds: '+125', opposite_odds: '-150' }
    ]
  },
  { 
    id: 3, 
    sport: 'NHL', 
    match: 'Bruins @ Maple Leafs', 
    market: 'Total Goals', 
    bet: 'Over 6.5', 
    opposite_bet: 'Under 6.5',
    wager_display: 'Over 6.5',
    opposite_wager_display: 'Under 6.5',
    book: 'FanDuel', 
    odds: '-105', 
    ev: 2.8, 
    kelly: 1.2, 
    time: '7:00 PM',
    other_books: [
      { name: 'FanDuel', bet_odds: '-105', opposite_odds: '-115' },
      { name: 'BetRivers', bet_odds: '-115', opposite_odds: '-105' },
      { name: 'DraftKings', bet_odds: '-120', opposite_odds: '+100' },
      { name: 'BetUS', bet_odds: '-118', opposite_odds: '-102' }
    ]
  },
  { 
    id: 4, 
    sport: 'NBA', 
    match: 'Celtics @ Heat', 
    market: 'Spread', 
    bet: 'Celtics -4.5', 
    opposite_bet: 'Heat +4.5',
    wager_display: 'Celtics -4.5',
    opposite_wager_display: 'Heat +4.5',
    book: 'Caesars', 
    odds: '-110', 
    ev: 2.1, 
    kelly: 1.0, 
    time: '8:00 PM',
    other_books: [
      { name: 'Caesars', bet_odds: '-110', opposite_odds: '-110' },
      { name: 'BetMGM', bet_odds: '-120', opposite_odds: '+100' },
      { name: 'FanDuel', bet_odds: '-125', opposite_odds: '+105' },
      { name: 'DraftKings', bet_odds: '-115', opposite_odds: '-105' }
    ]
  },
  { 
    id: 5, 
    sport: 'UFC', 
    match: 'Jones vs Miocic', 
    market: 'Method of Victory', 
    bet: 'Jones by KO/TKO', 
    opposite_bet: 'Any Other Result',
    wager_display: 'Jones KO/TKO',
    opposite_wager_display: 'Field',
    book: 'BetRivers', 
    odds: '+250', 
    ev: 6.7, 
    kelly: 1.8, 
    time: 'Sat, 11:00 PM',
    other_books: [
      { name: 'BetRivers', bet_odds: '+250', opposite_odds: '-300' },
      { name: 'DraftKings', bet_odds: '+210', opposite_odds: '-280' },
      { name: 'FanDuel', bet_odds: '+200', opposite_odds: '-275' },
      { name: 'BetMGM', bet_odds: '+215', opposite_odds: '-290' }
    ]
  },
  { 
    id: 6, 
    sport: 'NCAAB', 
    match: 'Duke @ UNC', 
    market: 'Total Points', 
    bet: 'Under 145.5', 
    opposite_bet: 'Over 145.5',
    wager_display: 'Under 145.5',
    opposite_wager_display: 'Over 145.5',
    book: 'PointsBet', 
    odds: '-110', 
    ev: 1.9, 
    kelly: 0.9, 
    time: 'Sat, 6:00 PM',
    other_books: [
      { name: 'PointsBet', bet_odds: '-110', opposite_odds: '-110' },
      { name: 'DraftKings', bet_odds: '-120', opposite_odds: '+100' },
      { name: 'BetMGM', bet_odds: '-125', opposite_odds: '+105' },
      { name: 'FanDuel', bet_odds: '-130', opposite_odds: '+110' }
    ]
  },
];

const PositiveEV: React.FC = () => {
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const toggleExpand = (id: number) => {
    setExpandedId(expandedId === id ? null : id);
  };

  return (
    <div className="min-h-screen bg-black px-4 py-8 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <div className="mb-8 flex items-end justify-between">
          <div>
            <h1 className="text-3xl font-bold text-white">Positive EV Bets</h1>
            <p className="mt-2 text-zinc-400">Mathematically profitable bets based on real-time market discrepancies.</p>
          </div>
          <div className="hidden sm:block">
            <span className="inline-flex items-center rounded-full bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-500 ring-1 ring-inset ring-amber-500/20">
              Live Updates Active
            </span>
          </div>
        </div>

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {MOCK_EV_DATA.map((bet) => {
            const isExpanded = expandedId === bet.id;
            
            return (
              <div 
                key={bet.id} 
                onClick={() => toggleExpand(bet.id)}
                className={`group relative flex flex-col justify-between overflow-hidden rounded-2xl border bg-zinc-950 transition-all cursor-pointer ${
                  isExpanded 
                    ? 'border-amber-500/50 shadow-lg shadow-amber-900/10 ring-1 ring-amber-500/20' 
                    : 'border-zinc-800 hover:border-amber-500/30'
                }`}
              >
                <div className="absolute top-0 right-0 p-4 z-10">
                  <span className="flex items-center gap-1 rounded-full bg-green-900/30 px-2 py-1 text-xs font-bold text-green-400 ring-1 ring-inset ring-green-500/20">
                    <TrendingUp size={12} /> {bet.ev}% EV
                  </span>
                </div>
                
                <div className="p-6 pb-2">
                  <div className="mb-4">
                    <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">{bet.sport} • {bet.time}</p>
                    <h3 className="mt-1 text-lg font-bold text-white">{bet.match}</h3>
                    <p className="text-sm text-zinc-400">{bet.market}</p>
                  </div>

                  <div className="mb-4 rounded-lg bg-zinc-900/50 p-4 ring-1 ring-zinc-800">
                    <div className="flex items-center justify-between">
                      <span className="text-lg font-semibold text-amber-500">{bet.bet}</span>
                      <span className="font-mono text-xl font-bold text-white">{bet.odds}</span>
                    </div>
                    <div className="mt-2 flex items-center justify-between border-t border-zinc-800 pt-2 text-xs">
                      <span className="text-zinc-500">Bookmaker</span>
                      <span className="font-medium text-zinc-300">{bet.book}</span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between py-2">
                    <div className="flex flex-col">
                      <span className="text-xs text-zinc-500">Kelly Stake</span>
                      <span className="flex items-center gap-1 text-sm font-bold text-zinc-200">
                        <Percent size={12} className="text-amber-500" /> {bet.kelly}%
                      </span>
                    </div>
                    {/* Visual indicator for expansion */}
                    <div className={`transition-transform duration-300 ${isExpanded ? 'rotate-180' : ''}`}>
                      <ChevronDown className="text-zinc-500" size={20} />
                    </div>
                  </div>
                </div>
                
                {/* Expanded Details Section */}
                {isExpanded && (
                  <div className="border-t border-zinc-800 bg-zinc-900/50 p-4 animate-in slide-in-from-top-2 duration-200">
                    <div className="mb-3 flex items-center justify-between text-xs font-semibold uppercase text-zinc-500">
                      <span>Book</span>
                      <div className="flex gap-4">
                        <span className="w-28 text-right truncate" title={bet.wager_display}>{bet.wager_display}</span>
                        <span className="w-28 text-right truncate" title={bet.opposite_wager_display}>{bet.opposite_wager_display}</span>
                      </div>
                    </div>
                    <div className="space-y-2">
                      {bet.other_books.map((bookOdds, idx) => {
                        const isBestBook = bookOdds.name === bet.book;
                        return (
                          <div key={idx} className={`flex items-center justify-between rounded px-2 py-1.5 text-sm ${isBestBook ? 'bg-amber-500/10 ring-1 ring-amber-500/30' : 'hover:bg-zinc-800'}`}>
                            <span className={`font-medium ${isBestBook ? 'text-amber-500' : 'text-zinc-400'}`}>
                              {bookOdds.name}
                            </span>
                            <div className="flex gap-4">
                              <span className={`w-28 text-right font-mono ${isBestBook ? 'font-bold text-amber-500' : 'text-zinc-300'}`}>
                                {bookOdds.bet_odds}
                              </span>
                              <span className="w-28 text-right font-mono text-zinc-500">
                                {bookOdds.opposite_odds}
                              </span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    <div className="mt-4 pt-4 border-t border-zinc-800/50">
                       <button 
                         onClick={(e) => e.stopPropagation()} 
                         className="w-full flex items-center justify-center gap-2 rounded-lg bg-amber-500 px-4 py-3 text-sm font-bold text-black transition-colors hover:bg-amber-400"
                       >
                        <DollarSign size={16} /> Place Bet on {bet.book}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default PositiveEV;
