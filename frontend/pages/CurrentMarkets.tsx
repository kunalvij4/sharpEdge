import React, { useState, useMemo, useEffect } from "react";
import { ChevronDown, ChevronUp, Trophy, Filter } from "lucide-react";
import { MarketResponse, MatchData } from "../types";

const LEAGUES = ["NBA", "NFL", "NHL", "MLB", "NCAAB"];

// S3 CACHE BASE
const CACHE_BASE =
  "https://retrieve-odds-stack-oddscachebucket-1wl5a0lcdm9v.s3.amazonaws.com/cache";

async function fetchLeagueData(league: string): Promise<MarketResponse> {
  try {
    const res = await fetch(`${CACHE_BASE}/${league}/moneyline.json.gz`);
    if (!res.ok) return {};

    const buffer = await res.arrayBuffer();
    const text = new TextDecoder().decode(buffer);
    const json = JSON.parse(text);
    const games = json.games;

    const transformed: MarketResponse = {};

    Object.entries(games).forEach(([key, game]: any) => {
      const oddsData = game.data.odds_data;

      const match: MatchData = {
        sport: game.sport || league,
        home_team: game.home_team,
        away_team: game.away_team,
        commence_time: game.commence_time,
        markets: {
          moneyline: {
            odds_data: Object.fromEntries(
              Object.entries(oddsData).map(([book, odds]: any) => [
                book,
                [odds.away_odds, odds.home_odds]
              ])
            )
          }
        }
      };

      // Load spreads if present
      if (game.data.spreads) {
        match.markets.spreads = { odds_data: game.data.spreads };
      }

      // Load totals if present
      if (game.data.totals) {
        match.markets.totals = { odds_data: game.data.totals };
      }

      transformed[key] = match;
    });

    return transformed;
  } catch (err) {
    console.error("League fetch failed:", league, err);
    return {};
  }
}

/*
FETCH ALL LEAGUES IN PARALLEL
*/
async function fetchAllMarkets(): Promise<MarketResponse> {
  const responses = await Promise.all(
    LEAGUES.map((league) => fetchLeagueData(league))
  );

  const merged: MarketResponse = {};

  responses.forEach((leagueData) => {
    Object.assign(merged, leagueData);
  });

  return merged;
}

const MarketCard: React.FC<{
  matchId: string;
  data: MatchData;
  selectedBook: string;
}> = ({ matchId, data, selectedBook }) => {
  const [expanded, setExpanded] = useState(false);
  const [activeTab, setActiveTab] =
    useState<"moneyline" | "spreads" | "totals">("moneyline");

  const dateStr = new Date(data.commence_time).toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  });

  const decimalToAmerican = (decimal: number): string => {
    if (!decimal || decimal === 1) return "-";

    if (decimal >= 2) {
      return `+${Math.round((decimal - 1) * 100)}`;
    }

    return `${Math.round(-100 / (decimal - 1))}`;
  };

  const displayOdds = useMemo(() => {
    if (!data.markets.moneyline)
      return { home: "-", away: "-", type: "Best" };

    if (selectedBook !== "All") {
      const bookOdds =
        data.markets.moneyline.odds_data[selectedBook];

      if (bookOdds) {
        return {
          home: decimalToAmerican(bookOdds[1]),
          away: decimalToAmerican(bookOdds[0]),
          type: selectedBook
        };
      }

      return { home: "N/A", away: "N/A", type: selectedBook };
    }

    const odds = Object.values(data.markets.moneyline.odds_data);

    const bestAway = Math.max(...odds.map((o) => o[0]));
    const bestHome = Math.max(...odds.map((o) => o[1]));

    return {
      home: decimalToAmerican(bestHome),
      away: decimalToAmerican(bestAway),
      type: "Best"
    };
  }, [data.markets.moneyline, selectedBook]);

  const OddsGrid = ({
    type
  }: {
    type: "moneyline" | "spreads" | "totals";
  }) => {
    const market = data.markets[type];

    if (!market)
      return (
        <div className="p-4 text-zinc-500 text-center">
          No data available
        </div>
      );

    const allBooks = Object.keys(market.odds_data);

    const books =
      selectedBook === "All"
        ? allBooks
        : allBooks.filter((b) => b === selectedBook);

    if (books.length === 0) {
      return (
        <div className="p-8 text-center text-zinc-500">
          No odds available for {selectedBook} in this market.
        </div>
      );
    }

    return (
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm text-zinc-400">
          <thead className="bg-zinc-900 text-xs uppercase text-zinc-500">
            <tr>
              <th className="px-4 py-3 font-medium">Bookmaker</th>

              {type === "moneyline" && (
                <>
                  <th className="px-4 py-3 text-right">{data.away_team}</th>
                  <th className="px-4 py-3 text-right">{data.home_team}</th>
                </>
              )}

              {type === "spreads" && (
                <>
                  <th className="px-4 py-3 text-right">{data.away_team} Spread</th>
                  <th className="px-4 py-3 text-right">{data.away_team} Odds</th>
                  <th className="px-4 py-3 text-right">{data.home_team} Spread</th>
                  <th className="px-4 py-3 text-right">{data.home_team} Odds</th>
                </>
              )}

              {type === "totals" && (
                <>
                  <th className="px-4 py-3 text-right">Line</th>
                  <th className="px-4 py-3 text-right">Over</th>
                  <th className="px-4 py-3 text-right">Under</th>
                </>
              )}
            </tr>
          </thead>

          <tbody className="divide-y divide-zinc-800">
            {books.map((book) => {
              const oddData = market.odds_data[book] as any;

              return (
                <tr key={book}>
                  <td className="px-4 py-3 text-zinc-300">{book}</td>

                  {type === "moneyline" && Array.isArray(oddData) && (
                    <>
                      <td className="px-4 py-3 text-right font-mono text-amber-500">
                        {decimalToAmerican(oddData[0])}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-amber-500">
                        {decimalToAmerican(oddData[1])}
                      </td>
                    </>
                  )}

                  {type === "spreads" && oddData && (
                    <>
                      <td className="px-4 py-3 text-right font-mono text-zinc-300">
                        {oddData.away_point > 0 ? `+${oddData.away_point}` : oddData.away_point}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-amber-500">
                        {decimalToAmerican(oddData.away_odds)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-zinc-300">
                        {oddData.home_point > 0 ? `+${oddData.home_point}` : oddData.home_point}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-amber-500">
                        {decimalToAmerican(oddData.home_odds)}
                      </td>
                    </>
                  )}

                  {type === "totals" && oddData && (
                    <>
                      <td className="px-4 py-3 text-right font-mono text-zinc-300">
                        {oddData.point}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-amber-500">
                        {decimalToAmerican(oddData.over_odds)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-amber-500">
                        {decimalToAmerican(oddData.under_odds)}
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
    <div className="mb-6 rounded-xl border border-zinc-800 bg-zinc-950">
      <div
        className="cursor-pointer bg-zinc-900/40 p-5"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs text-zinc-500">
              {data.sport} • {dateStr}
            </div>

            <h3 className="text-lg font-bold text-white">
              {data.away_team} @ {data.home_team}
            </h3>
          </div>

          <div className="flex gap-6 text-right">
            <div>
              <div className="text-xs text-zinc-500">
                {displayOdds.type} {data.away_team}
              </div>
              <div className="font-mono text-lg text-amber-500">
                {displayOdds.away}
              </div>
            </div>

            <div>
              <div className="text-xs text-zinc-500">
                {displayOdds.type} {data.home_team}
              </div>
              <div className="font-mono text-lg text-amber-500">
                {displayOdds.home}
              </div>
            </div>

            {expanded ? <ChevronUp /> : <ChevronDown />}
          </div>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-zinc-800">
          <div className="flex gap-1 bg-zinc-900/60 px-4 pt-3">
            {(["moneyline", "spreads", "totals"] as const).map((tab) => (
              <button
                key={tab}
                onClick={(e) => { e.stopPropagation(); setActiveTab(tab); }}
                className={`rounded-t-md px-4 py-2 text-xs font-medium capitalize transition-colors ${
                  activeTab === tab
                    ? "bg-zinc-950 text-amber-500"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
          <OddsGrid type={activeTab} />
        </div>
      )}
    </div>
  );
};

const CurrentMarkets: React.FC = () => {
  const [marketData, setMarketData] = useState<MarketResponse>({});
  const [selectedLeague, setSelectedLeague] =
    useState<string>("All");
  const [selectedBook, setSelectedBook] =
    useState<string>("All");

  useEffect(() => {
    fetchAllMarkets().then(setMarketData);
  }, []);

  const leagues = useMemo(() => {
    const leagueSet = new Set<string>(["All"]);

    (Object.values(marketData) as MatchData[]).forEach((match) =>
      leagueSet.add(match.sport)
    );

    return Array.from(leagueSet);
  }, [marketData]);

  const books = useMemo(() => {
    const bookSet = new Set<string>(["All"]);

    (Object.values(marketData) as MatchData[]).forEach((match) => {
      if (match.markets.moneyline?.odds_data)
        Object.keys(match.markets.moneyline.odds_data).forEach(
          (k) => bookSet.add(k)
        );
    });

    return Array.from(bookSet).sort();
  }, [marketData]);

  const filteredMatches = useMemo(() => {
    return (Object.entries(marketData) as [string, MatchData][]).filter(([_, data]) => {
      return (
        selectedLeague === "All" ||
        data.sport === selectedLeague
      );
    });
  }, [marketData, selectedLeague]);

  return (
    <div className="min-h-screen bg-black px-4 py-8">
      <div className="mx-auto max-w-5xl">

        <div className="mb-8">
          <h1 className="text-3xl font-bold text-white">
            Current Markets
          </h1>
          <p className="mt-2 text-zinc-400">
            Live odds across all major sportsbooks.
          </p>
        </div>

        {/* Sport Filter */}
        <div className="mb-6 overflow-x-auto pb-2 hide-scrollbar">
          <div className="flex gap-2">
            {leagues.map((s) => (
              <button
                key={s}
                onClick={() => setSelectedLeague(s)}
                className={`whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                  selectedLeague === s
                    ? "bg-amber-500 text-black"
                    : "bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-white"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {/* Book Filter */}
        <div className="mb-6 flex items-center gap-3">
          <Filter size={16} className="text-zinc-500" />
          <select
            value={selectedBook}
            onChange={(e) => setSelectedBook(e.target.value)}
            className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-300 focus:border-amber-500 focus:outline-none"
          >
            {books.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        </div>

        {/* Empty State */}
        {filteredMatches.length === 0 && (
          <div className="flex h-64 flex-col items-center justify-center rounded-xl border border-zinc-800 bg-zinc-950 p-8 text-center">
            <Trophy size={48} className="mb-4 text-zinc-700" />
            <h3 className="text-xl font-bold text-white">No Games Available</h3>
            <p className="mt-2 max-w-md text-zinc-500">
              No games currently scheduled for {selectedLeague === "All" ? "any sport" : selectedLeague}. Check back closer to game time.
            </p>
          </div>
        )}

        <div className="space-y-4">
          {filteredMatches.map(([key, data]) => (
            <MarketCard
              key={key}
              matchId={key}
              data={data}
              selectedBook={selectedBook}
            />
          ))}
        </div>
      </div>
    </div>
  );
};

export default CurrentMarkets;