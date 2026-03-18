import React, { useState, useEffect, useMemo } from "react";
import { Percent, TrendingUp, DollarSign, ChevronDown, RefreshCw, AlertCircle } from "lucide-react";

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

const EV_BASE_URL =
  "https://retrieve-odds-stack-oddscachebucket-1wl5a0lcdm9v.s3.amazonaws.com/ev/";

const SPORTS = ["NBA", "NFL", "NHL", "MLB", "NCAAB"];

function decimalToAmerican(decimal: number): string {
  if (decimal >= 2) {
    return `+${Math.round((decimal - 1) * 100)}`;
  }
  return `-${Math.round(100 / (decimal - 1))}`;
}

function getDKLeague(sport: string) {
  const map: Record<string, string> = {
    NBA: "basketball/nba",
    NFL: "football/nfl",
    MLB: "baseball/mlb",
    NHL: "hockey/nhl",
    NCAAB: "basketball/ncaab",
  };
  return map[sport] || "";
}

function getMGMLeague(sport: string) {
  const map: Record<string, string> = {
    NBA: "basketball-7/betting/usa-9/nba-6004",
    NFL: "football-11/betting/usa-9/nfl-35",
    MLB: "baseball-23/betting/usa-9/mlb-75",
    NHL: "hockey-12/betting/usa-9/nhl-34",
    NCAAB: "basketball-7/betting/usa-9/ncaa-264",
  };
  return map[sport] || "";
}

const BOOK_LINKS: Record<string, (bet: EVBet) => string> = {
  FanDuel: (bet) =>
    `https://sportsbook.fanduel.com/navigation/${bet.sport.toLowerCase()}`,

  DraftKings: (bet) =>
    `https://sportsbook.draftkings.com/leagues/${getDKLeague(bet.sport)}`,

  BetMGM: (bet) =>
    `https://sports.betmgm.com/en/sports/${getMGMLeague(bet.sport)}`,

  BetRivers: (bet) =>
    `https://betrivers.com/?page=sportsbook&group=${bet.sport.toLowerCase()}`,

  Caesars: (bet) =>
    `https://sportsbook.caesars.com/us/${bet.sport.toLowerCase()}`,

  ESPNBet: (bet) =>
    `https://espnbet.com/sports/${bet.sport.toLowerCase()}`,

  Fanatics: (bet) =>
    `https://sportsbook.fanatics.com/sports/${bet.sport.toLowerCase()}`,

  PointsBet: (bet) =>
    `https://pointsbet.com/sports/${bet.sport.toLowerCase()}`,

  Bovada: () =>
    `https://www.bovada.lv/sports/basketball/nba`,

  BetOnline: () =>
    `https://www.betonline.ag/sportsbook/basketball/nba`,

  MyBookie: () =>
    `https://www.mybookie.ag/sportsbook/nba/`,
};

const PositiveEV: React.FC = () => {
  const [bets, setBets] = useState<EVBet[]>([]);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSport, setSelectedSport] = useState<string>("All");

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    const allBets: EVBet[] = [];

    try {
      for (const sport of SPORTS) {
        try {
          const res = await fetch(`${EV_BASE_URL}${sport}/moneyline_ev.json`);
          if (!res.ok) continue;

          const data = await res.json();

          data.forEach((bet: any) => {
            // find opposite EV entry for same match
            const oppositeEntry = data.find(
              (b: any) =>
                b.match === bet.match &&
                b.bet === bet.opposite_bet
            );

            const books: BookOdds[] = [];

            // main book
            books.push({
              name: bet.book,
              bet_odds: decimalToAmerican(bet.odds),
              opposite_odds:
                bet.away_odds
                  ? decimalToAmerican(bet.away_odds)
                  : oppositeEntry
                  ? decimalToAmerican(oppositeEntry.odds)
                  : "-"
            });

            // other books
            bet.other_books?.forEach((b: any) => {
              let oppositeOdds: number | null = null;

              // case 1: away_other_books exists
              if (bet.away_other_books) {
                const match = bet.away_other_books.find(
                  (away: any) => away.book === b.book
                );
                if (match) oppositeOdds = match.odds;
              }

              // case 2: use opposite EV row
              if (!oppositeOdds && oppositeEntry) {
                if (oppositeEntry.book === b.book) {
                  oppositeOdds = oppositeEntry.odds;
                } else {
                  const match = oppositeEntry.other_books?.find(
                    (ob: any) => ob.book === b.book
                  );
                  if (match) oppositeOdds = match.odds;
                }
              }

              books.push({
                name: b.book,
                bet_odds: decimalToAmerican(b.odds),
                opposite_odds: oppositeOdds
                  ? decimalToAmerican(oppositeOdds)
                  : "-"
              });
            });

            allBets.push({
              id: bet.id,
              sport: bet.sport || sport,
              match: bet.match,
              market: bet.market,
              bet: bet.bet,
              opposite_bet: bet.opposite_bet,
              wager_display: bet.wager_display,
              opposite_wager_display: bet.opposite_wager_display,
              book: bet.book,
              odds: decimalToAmerican(bet.odds),
              ev: Number(bet.ev.toFixed(2)),
              kelly: Number((bet.kelly * 100).toFixed(2)),
              time: new Date(bet.time).toLocaleTimeString(),
              other_books: books
            });
          });
        } catch (err) {
          console.error(`EV fetch error for ${sport}:`, err);
        }
      }
      setBets(allBets);
    } catch (err) {
      console.error("Overall EV fetch error:", err);
      setError("Failed to load Positive EV bets.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const toggleExpand = (id: number) => {
    setExpandedId(expandedId === id ? null : id);
  };

  const filteredBets = useMemo(() => {
    if (selectedSport === "All") return bets;
    return bets.filter((bet) => bet.sport === selectedSport);
  }, [bets, selectedSport]);

  return (
    <div className="min-h-screen bg-black px-4 py-8 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">

        <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <h1 className="text-3xl font-bold text-white">
              Positive EV Bets
            </h1>
            <p className="mt-2 text-zinc-400">
              Mathematically profitable bets based on real-time market discrepancies.
            </p>
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
            {["All", ...SPORTS].map((s) => (
              <button
                key={s}
                onClick={() => setSelectedSport(s)}
                className={`whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                  selectedSport === s
                    ? 'bg-amber-500 text-black'
                    : 'bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-white'
                }`}
              >
                {s}
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
        {loading && bets.length === 0 && (
          <div className="flex h-64 items-center justify-center">
            <div className="flex flex-col items-center gap-4 text-zinc-500">
              <RefreshCw size={32} className="animate-spin text-amber-500" />
              <p>Scanning markets for Positive EV bets...</p>
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && filteredBets.length === 0 && (
          <div className="flex h-64 flex-col items-center justify-center rounded-xl border border-zinc-800 bg-zinc-950 p-8 text-center">
            <TrendingUp size={48} className="mb-4 text-zinc-700" />
            <h3 className="text-xl font-bold text-white">No EV Bets Found</h3>
            <p className="mt-2 max-w-md text-zinc-500">
              There are currently no Positive EV bets available for {selectedSport === 'All' ? 'any sport' : selectedSport}. Markets move fast, so check back soon.
            </p>
          </div>
        )}

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {filteredBets.map((bet) => {
            const isExpanded = expandedId === bet.id;

            return (
              <div
                key={bet.id}
                onClick={() => toggleExpand(bet.id)}
                className={`group relative flex flex-col justify-between overflow-hidden rounded-2xl border bg-zinc-950 transition-all cursor-pointer ${
                  isExpanded
                    ? "border-amber-500/50 shadow-lg shadow-amber-900/10 ring-1 ring-amber-500/20"
                    : "border-zinc-800 hover:border-amber-500/30"
                }`}
              >
                <div className="absolute top-0 right-0 p-4 z-10">
                  <span className="flex items-center gap-1 rounded-full bg-green-900/30 px-2 py-1 text-xs font-bold text-green-400 ring-1 ring-green-500/20">
                    <TrendingUp size={12} /> {bet.ev}% EV
                  </span>
                </div>

                <div className="p-6 pb-2">
                  <div className="mb-4">
                    <p className="text-xs uppercase tracking-wider text-zinc-500">
                      {bet.sport} • {bet.time}
                    </p>
                    <h3 className="mt-1 text-lg font-bold text-white">
                      {bet.match}
                    </h3>
                    <p className="text-sm text-zinc-400">{bet.market}</p>
                  </div>

                  <div className="mb-4 rounded-lg bg-zinc-900/50 p-4 ring-1 ring-zinc-800">
                    <div className="flex justify-between">
                      <span className="text-lg font-semibold text-amber-500">
                        {bet.bet}
                      </span>
                      <span className="font-mono text-xl font-bold text-white">
                        {bet.odds}
                      </span>
                    </div>

                    <div className="mt-2 flex justify-between border-t border-zinc-800 pt-2 text-xs">
                      <span className="text-zinc-500">Bookmaker</span>
                      <span className="text-zinc-300">{bet.book}</span>
                    </div>
                  </div>

                  <div className="flex justify-between py-2">
                    <div>
                      <span className="text-xs text-zinc-500">
                        Kelly Stake
                      </span>
                      <div className="flex items-center gap-1 text-sm font-bold text-zinc-200">
                        <Percent size={12} className="text-amber-500" />
                        {bet.kelly}%
                      </div>
                    </div>

                    <ChevronDown
                      className={`text-zinc-500 transition-transform ${
                        isExpanded ? "rotate-180" : ""
                      }`}
                    />
                  </div>
                </div>

                {isExpanded && (
                  <div className="border-t border-zinc-800 bg-zinc-900/50 p-4">
                    <div className="mb-3 flex justify-between text-xs uppercase text-zinc-500">
                      <span>Book</span>
                      <div className="flex gap-4">
                        <span className="w-28 text-right">
                          {bet.wager_display}
                        </span>
                        <span className="w-28 text-right">
                          {bet.opposite_wager_display}
                        </span>
                      </div>
                    </div>

                    <div className="space-y-2">
                      {bet.other_books.map((bookOdds, idx) => {
                        const isBestBook =
                          bookOdds.name === bet.book;

                        return (
                          <div
                            key={idx}
                            className={`flex justify-between rounded px-2 py-1.5 text-sm ${
                              isBestBook
                                ? "bg-amber-500/10 ring-1 ring-amber-500/30"
                                : "hover:bg-zinc-800"
                            }`}
                          >
                            <span
                              className={`${
                                isBestBook
                                  ? "text-amber-500"
                                  : "text-zinc-400"
                              }`}
                            >
                              {bookOdds.name}
                            </span>

                            <div className="flex gap-4">
                              <span className="w-28 text-right font-mono text-zinc-300">
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
                        onClick={(e) => {
                          e.stopPropagation();

                          const linkFn = BOOK_LINKS[bet.book];
                          const url = linkFn ? linkFn(bet) : "https://google.com";

                          window.open(url, "_blank");

                          navigator.clipboard.writeText(
                            `${bet.bet} ML (${bet.odds}) on ${bet.book}`
                          );
                        }}
                        className="w-full flex items-center justify-center gap-2 rounded-lg bg-amber-500 px-4 py-3 text-sm font-bold text-black hover:bg-amber-400"
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
