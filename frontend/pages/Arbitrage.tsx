import React, { useState, useEffect } from 'react';
import { TrendingUp, DollarSign, RefreshCw, ExternalLink, AlertCircle, Percent } from 'lucide-react';

interface ArbOpportunity {
  match: string;
  market: string;
  side1: string;
  side2: string;
  book1: string;
  book2: string;
  odds1: number;
  odds2: number;
  arb_margin: number;
  time: string;
}

const SPORTS = [
  { id: 'NBA', name: 'NBA' },
  { id: 'NFL', name: 'NFL' },
  { id: 'NHL', name: 'NHL' },
  { id: 'MLB', name: 'MLB' },
  { id: 'NCAAB', name: 'NCAAB' }
];

const Arbitrage: React.FC = () => {
  const [sport, setSport] = useState('NBA');
  const [data, setData] = useState<ArbOpportunity[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const BASE_URL = "https://retrieve-odds-stack-oddscachebucket-1wl5a0lcdm9v.s3.amazonaws.com/arbitrage";
      const url = `${BASE_URL}/${sport}/moneyline_arb.json`;
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error('Failed to fetch data');
      }
      const json = await response.json();
      setData(json);
    } catch (err) {
      console.error(err);
      setError('Failed to load arbitrage opportunities. They might not be available for this sport right now.');
      setData([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [sport]);

  const calculateBets = (odds1: number, odds2: number) => {
    let bet1, bet2, payout, profit;
    if (odds1 < odds2) {
      bet1 = 100;
      payout = bet1 * odds1;
      bet2 = payout / odds2;
    } else {
      bet2 = 100;
      payout = bet2 * odds2;
      bet1 = payout / odds1;
    }
    
    const totalBet = bet1 + bet2;
    profit = payout - totalBet;
    
    return {
      bet1: bet1.toFixed(2),
      bet2: bet2.toFixed(2),
      totalBet: totalBet.toFixed(2),
      payout: payout.toFixed(2),
      profit: profit.toFixed(2)
    };
  };

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

  const getBookLink = (bookName: string) => {
    const bookMap: Record<string, string> = {
      'DraftKings': 'https://sportsbook.draftkings.com',
      'FanDuel': 'https://sportsbook.fanduel.com',
      'BetMGM': 'https://sports.betmgm.com',
      'Caesars': 'https://williamhill.com',
      'BetRivers': 'https://betrivers.com',
      'PointsBet': 'https://pointsbet.com',
      'MyBookie': 'https://mybookie.ag',
      'Bovada': 'https://bovada.lv',
      'BetOnline': 'https://betonline.ag',
      'BetUS': 'https://betus.com.pa',
      'LowVig.ag': 'https://lowvig.ag'
    };
    return bookMap[bookName] || '#';
  };

  return (
    <div className="min-h-screen bg-black px-4 py-8 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-5xl">
        <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <h1 className="text-3xl font-bold text-white">Arbitrage Opportunities</h1>
            <p className="mt-2 text-zinc-400">Risk-free profit by betting on all possible outcomes across different sportsbooks.</p>
          </div>
          <div className="flex items-center gap-4">
            <button 
              onClick={fetchData}
              disabled={loading}
              className="flex items-center gap-2 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-zinc-300 transition-colors hover:bg-zinc-800 hover:text-white disabled:opacity-50"
            >
              <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
            <span className="hidden sm:inline-flex items-center gap-2 rounded-full bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-500 ring-1 ring-amber-500/20 animate-glow">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
              </span>
              Live Updates Active
            </span>
          </div>
        </div>

        {/* Sport Filter */}
        <div className="mb-8 overflow-x-auto pb-2 hide-scrollbar">
          <div className="flex gap-2">
            {SPORTS.map((s) => (
              <button
                key={s.id}
                onClick={() => setSport(s.id)}
                className={`whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                  sport === s.id
                    ? 'bg-amber-500 text-black'
                    : 'bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-white'
                }`}
              >
                {s.name}
              </button>
            ))}
          </div>
        </div>

        {/* Error State */}
        {error && !loading && (
          <div className="mb-8 flex items-center gap-3 rounded-xl border border-red-900/50 bg-red-950/20 p-4 text-red-400">
            <AlertCircle size={20} />
            <p>{error}</p>
          </div>
        )}

        {/* Loading State */}
        {loading && data.length === 0 && (
          <div className="flex h-64 items-center justify-center">
            <div className="flex flex-col items-center gap-4 text-zinc-500">
              <RefreshCw size={32} className="animate-spin text-amber-500" />
              <p>Scanning markets for arbitrage...</p>
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && data.length === 0 && (
          <div className="flex h-64 flex-col items-center justify-center rounded-xl border border-zinc-800 bg-zinc-950 p-8 text-center">
            <TrendingUp size={48} className="mb-4 text-zinc-700" />
            <h3 className="text-xl font-bold text-white">No Arbitrage Found</h3>
            <p className="mt-2 max-w-md text-zinc-500">
              There are currently no risk-free arbitrage opportunities for this sport. Markets move fast, so check back soon.
            </p>
          </div>
        )}

        {/* Results */}
        <div className="space-y-6">
          {data.map((arb, idx) => {
            const bets = calculateBets(arb.odds1, arb.odds2);
            const dateStr = new Date(arb.time).toLocaleString('en-US', {
              weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
            });

            return (
              <div key={idx} className="overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950 transition-all hover:border-amber-500/30">
                {/* Header */}
                <div className="flex flex-col gap-4 border-b border-zinc-800 bg-zinc-900/40 p-5 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="flex items-center gap-2 text-xs font-medium text-zinc-500">
                      <span className="uppercase tracking-wider">{arb.market}</span>
                      <span>•</span>
                      <span>{dateStr}</span>
                    </div>
                    <h3 className="mt-1 text-lg font-bold text-white">{arb.match}</h3>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex flex-col items-end">
                      <span className="text-xs text-zinc-500">Guaranteed Profit</span>
                      <span className="text-lg font-bold text-green-400">${bets.profit}</span>
                    </div>
                    <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-900/20 ring-1 ring-green-500/30">
                      <span className="text-sm font-bold text-green-400">{arb.arb_margin}%</span>
                    </div>
                  </div>
                </div>

                {/* Body */}
                <div className="grid gap-0 sm:grid-cols-2">
                  {/* Side 1 */}
                  <div className="flex flex-col justify-between border-b border-zinc-800 p-5 sm:border-b-0 sm:border-r">
                    <div>
                      <div className="mb-4 flex items-center justify-between">
                        <span className="font-medium text-zinc-300">{arb.book1}</span>
                        <span className="rounded bg-zinc-900 px-2 py-1 font-mono text-sm font-bold text-amber-500">
                          {decimalToAmerican(arb.odds1)} <span className="text-xs text-zinc-500 font-normal">({arb.odds1})</span>
                        </span>
                      </div>
                      <h4 className="mb-6 text-xl font-bold text-white">{arb.side1}</h4>
                      
                      <div className="mb-6 rounded-lg bg-zinc-900/50 p-4 ring-1 ring-zinc-800">
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-zinc-400">Suggested Bet</span>
                          <span className="font-mono text-lg font-bold text-white">${bets.bet1}</span>
                        </div>
                      </div>
                    </div>
                    
                    <a 
                      href={getBookLink(arb.book1)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex w-full items-center justify-center gap-2 rounded-lg bg-zinc-800 px-4 py-3 text-sm font-bold text-white transition-colors hover:bg-zinc-700"
                    >
                      Go to {arb.book1} <ExternalLink size={16} />
                    </a>
                  </div>

                  {/* Side 2 */}
                  <div className="flex flex-col justify-between p-5">
                    <div>
                      <div className="mb-4 flex items-center justify-between">
                        <span className="font-medium text-zinc-300">{arb.book2}</span>
                        <span className="rounded bg-zinc-900 px-2 py-1 font-mono text-sm font-bold text-amber-500">
                          {decimalToAmerican(arb.odds2)} <span className="text-xs text-zinc-500 font-normal">({arb.odds2})</span>
                        </span>
                      </div>
                      <h4 className="mb-6 text-xl font-bold text-white">{arb.side2}</h4>
                      
                      <div className="mb-6 rounded-lg bg-zinc-900/50 p-4 ring-1 ring-zinc-800">
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-zinc-400">Suggested Bet</span>
                          <span className="font-mono text-lg font-bold text-white">${bets.bet2}</span>
                        </div>
                      </div>
                    </div>
                    
                    <a 
                      href={getBookLink(arb.book2)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex w-full items-center justify-center gap-2 rounded-lg bg-zinc-800 px-4 py-3 text-sm font-bold text-white transition-colors hover:bg-zinc-700"
                    >
                      Go to {arb.book2} <ExternalLink size={16} />
                    </a>
                  </div>
                </div>

                {/* Footer Summary */}
                <div className="border-t border-zinc-800 bg-zinc-900/20 px-5 py-3">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-zinc-500">Total Stake: <span className="font-mono text-zinc-300">${bets.totalBet}</span></span>
                    <span className="text-zinc-500">Payout: <span className="font-mono text-zinc-300">${bets.payout}</span></span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default Arbitrage;
