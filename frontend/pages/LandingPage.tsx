import React from 'react';
import { Link } from 'react-router-dom';
import { TrendingUp, ShieldCheck, Zap, ArrowRight } from 'lucide-react';

const LandingPage: React.FC = () => {
  return (
    <div className="flex flex-col">
      {/* Hero Section */}
      <section className="relative overflow-hidden bg-zinc-950 px-6 py-24 sm:py-32 lg:px-8">
        <div className="absolute inset-0 -z-10 bg-[radial-gradient(45rem_50rem_at_top,theme(colors.zinc.800),theme(colors.zinc.950))] opacity-20" />
        <div className="absolute inset-y-0 right-1/2 -z-10 mr-16 w-[200%] origin-bottom-left skew-x-[-30deg] bg-zinc-950 shadow-xl shadow-zinc-900/10 ring-1 ring-zinc-900 sm:mr-28 lg:mr-0 xl:mr-16 xl:origin-center" />
        
        <div className="mx-auto max-w-2xl text-center">
          <h1 className="text-4xl font-bold tracking-tight text-white sm:text-6xl">
            Beat the Sportsbooks with <span className="text-amber-500">Precision</span>
          </h1>
          <p className="mt-6 text-lg leading-8 text-zinc-400">
            SharpEdge provides real-time odds comparison, positive EV bets, and arbitrage tools to give you the mathematical edge over the house.
          </p>
          <div className="mt-10 flex items-center justify-center gap-x-6">
            <Link
              to="/markets"
              className="rounded-full bg-amber-500 px-8 py-3.5 text-sm font-bold text-black shadow-sm transition-all hover:bg-amber-400 hover:scale-105 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-500"
            >
              View Live Odds
            </Link>
            <Link to="/positive-ev" className="group text-sm font-semibold leading-6 text-white">
              See Top EV Bets <span aria-hidden="true" className="inline-block transition-transform group-hover:translate-x-1">→</span>
            </Link>
          </div>
        </div>
      </section>

      {/* Feature Grid */}
      <section className="bg-zinc-900 py-24 sm:py-32">
        <div className="mx-auto max-w-7xl px-6 lg:px-8">
          <div className="mx-auto max-w-2xl lg:text-center">
            <h2 className="text-base font-semibold leading-7 text-amber-500">Smarter Betting</h2>
            <p className="mt-2 text-3xl font-bold tracking-tight text-white sm:text-4xl">
              Everything you need to find value
            </p>
          </div>
          <div className="mx-auto mt-16 max-w-2xl sm:mt-20 lg:mt-24 lg:max-w-none">
            <dl className="grid max-w-xl grid-cols-1 gap-x-8 gap-y-16 lg:max-w-none lg:grid-cols-3">
              <div className="flex flex-col rounded-2xl bg-zinc-950 p-8 ring-1 ring-zinc-800 transition-colors hover:ring-amber-500/50">
                <dt className="flex items-center gap-x-3 text-base font-semibold leading-7 text-white">
                  <TrendingUp className="h-5 w-5 flex-none text-amber-500" aria-hidden="true" />
                  Positive EV
                </dt>
                <dd className="mt-4 flex flex-auto flex-col text-base leading-7 text-zinc-400">
                  <p className="flex-auto">
                    Identify bets where the implied probability is lower than the true probability, giving you a long-term mathematical advantage.
                  </p>
                </dd>
              </div>
              <div className="flex flex-col rounded-2xl bg-zinc-950 p-8 ring-1 ring-zinc-800 transition-colors hover:ring-amber-500/50">
                <dt className="flex items-center gap-x-3 text-base font-semibold leading-7 text-white">
                  <Zap className="h-5 w-5 flex-none text-amber-500" aria-hidden="true" />
                  Real-Time Arbitrage
                </dt>
                <dd className="mt-4 flex flex-auto flex-col text-base leading-7 text-zinc-400">
                  <p className="flex-auto">
                    Lock in risk-free profits by betting on all outcomes of an event across different sportsbooks when pricing discrepancies occur.
                  </p>
                </dd>
              </div>
              <div className="flex flex-col rounded-2xl bg-zinc-950 p-8 ring-1 ring-zinc-800 transition-colors hover:ring-amber-500/50">
                <dt className="flex items-center gap-x-3 text-base font-semibold leading-7 text-white">
                  <ShieldCheck className="h-5 w-5 flex-none text-amber-500" aria-hidden="true" />
                  Market Transparency
                </dt>
                <dd className="mt-4 flex flex-auto flex-col text-base leading-7 text-zinc-400">
                  <p className="flex-auto">
                    View odds from every major sportsbook in one place. Never take a bad line again. Compare, bet, and win.
                  </p>
                </dd>
              </div>
            </dl>
          </div>
        </div>
      </section>
    </div>
  );
};

export default LandingPage;
