import React, { useState, useMemo, useEffect } from "react";
import {
  ChevronDown,
  ChevronUp,
  Trophy,
  Calendar,
  Filter,
  Search
} from "lucide-react";
import pako from "pako";
import {
  MarketResponse,
  MatchData,
  SpreadOddsDetails,
  TotalOddsDetails
} from "../types";

// AUTO-LOAD LEAGUES FROM S3 CACHE
// Add leagues here as your backend grows
const LEAGUES = ["NBA"];

// S3 CACHE BASE
const CACHE_BASE =
  "https://retrieve-odds-stack-oddscachebucket-1wl5a0lcdm9v.s3.amazonaws.com/cache";

// FETCH + DECOMPRESS ONE LEAGUE
async function fetchLeagueData(league: string): Promise<MarketResponse> {
  try {
    const res = await fetch(`${CACHE_BASE}/${league}/moneyline.json.gz`);

    console.log(res);
    
    const buffer = await res.arrayBuffer();

    const text = new TextDecoder().decode(buffer);

    const json = JSON.parse(text);

    const games = json.games;

    const transformed: MarketResponse = {};

    Object.entries(games).forEach(([key, game]: any) => {
      const oddsData = game.data.odds_data;

      const match: MatchData = {
        sport: game.sport,
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
                  <th className="px-4 py-3 text-right">
                    {data.away_team}
                  </th>
                  <th className="px-4 py-3 text-right">
                    {data.home_team}
                  </th>
                </>
              )}
            </tr>
          </thead>

          <tbody className="divide-y divide-zinc-800">
            {books.map((book) => {
              const oddData = market.odds_data[book];

              return (
                <tr key={book}>
                  <td className="px-4 py-3 text-zinc-300">
                    {book}
                  </td>

                  {type === "moneyline" &&
                    Array.isArray(oddData) && (
                      <>
                        <td className="px-4 py-3 text-right font-mono text-amber-500">
                          {decimalToAmerican(oddData[0])}
                        </td>

                        <td className="px-4 py-3 text-right font-mono text-amber-500">
                          {decimalToAmerican(oddData[1])}
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
          <OddsGrid type="moneyline" />
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

    Object.values(marketData).forEach((match) =>
      leagueSet.add(match.sport)
    );

    return Array.from(leagueSet);
  }, [marketData]);

  const books = useMemo(() => {
    const bookSet = new Set<string>(["All"]);

    Object.values(marketData).forEach((match) => {
      if (match.markets.moneyline?.odds_data)
        Object.keys(match.markets.moneyline.odds_data).forEach(
          (k) => bookSet.add(k)
        );
    });

    return Array.from(bookSet).sort();
  }, [marketData]);

  const filteredMatches = useMemo(() => {
    return Object.entries(marketData).filter(([_, data]) => {
      return (
        selectedLeague === "All" ||
        data.sport === selectedLeague
      );
    });
  }, [marketData, selectedLeague]);

  return (
    <div className="min-h-screen bg-black px-4 py-8">
      <div className="mx-auto max-w-5xl">

        <h1 className="text-3xl font-bold text-white">
          Current Markets
        </h1>

        <div className="space-y-4 mt-6">
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