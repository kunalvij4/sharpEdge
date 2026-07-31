import React, { useState } from 'react';
import { motion } from 'motion/react';
import { Zap, Shield, Target, TrendingUp, BarChart3, Clock, Activity, DollarSign, Timer } from 'lucide-react';
import CandlestickChart from '../components/CandlestickChart';
import FeatureCard from '../components/FeatureCard';
import StatCard from '../components/StatCard';
import RocketLaunch from '../components/RocketLaunch';
import TypewriterHeading from '../components/TypewriterHeading';

const PromoLanding: React.FC = () => {
  const [email, setEmail] = useState('');

  

  const features = [
    { icon: TrendingUp, title: "Real-Time Edge Detection", desc: "Our scanners monitor every second across 50+ sportsbooks, catching value discrepancies before the market corrects." },
    { icon: Shield, title: "Smart Risk Management", desc: "Integrated Kelly Criterion and bankroll optimization ensure you're always wagering the mathematically optimal amount." },
    { icon: Target, title: "Unrivaled Accuracy", desc: "Backtested against 10M+ data points with a 67% hit rate on positive EV plays, delivering consistent long-term ROI." },
    { icon: BarChart3, title: "Odds Comparison Engine", desc: "Instantly compare lines across every major book. Never leave money on the table by betting at an inferior price." },
    { icon: Clock, title: "Instant Alerts", desc: "Get push notifications the moment a +EV opportunity appears. Speed is everything — and we're the fastest." },
    { icon: Zap, title: "AI-Powered Projections", desc: "Our machine learning models process injury reports, weather data, and historical trends to generate sharp projections." },
  ];

  return (
    <div className="relative bg-background text-foreground overflow-x-hidden">

      {/* Hero Section */}
      <section className="relative flex min-h-screen flex-col items-center justify-center px-4 text-center overflow-hidden">
        {/* Background effects */}
        <div className="absolute inset-0 bg-radial-gold opacity-30 pointer-events-none" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-gold/5 blur-[120px] pointer-events-none" />
        
        <TypewriterHeading
          text="The Future of Sports Betting is Almost Here."
          highlightWords={['Future', 'Sports', 'Betting']}
          className="relative z-10 max-w-5xl text-5xl font-black tracking-tighter sm:text-7xl md:text-8xl font-display"
          speed={55}
          startDelay={300}
        />

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 3, duration: 1 }}
          className="relative z-10 mt-8 max-w-2xl text-lg text-muted-foreground md:text-xl"
        >
          Stop guessing. Start winning. Join the elite circle of bettors using mathematical precision to beat the books.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 3.8, duration: 0.8 }}
          className="relative z-10 mt-16 inline-block rounded-full border border-gold/30 bg-gold/10 px-8 py-3 text-lg font-black text-gold tracking-[0.2em] uppercase glow-gold"
        >
          Coming Soon
        </motion.div>

        {/* Scroll indicator */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 2.5 }}
          className="absolute bottom-10 z-10"
        >
          <motion.div
            animate={{ y: [0, 8, 0] }}
            transition={{ repeat: Infinity, duration: 2, ease: "easeInOut" }}
            className="w-5 h-8 rounded-full border-2 border-muted-foreground/30 flex items-start justify-center p-1"
          >
            <motion.div className="w-1 h-2 rounded-full bg-gold" />
          </motion.div>
        </motion.div>
      </section>

      {/* Candlestick Chart Section */}
      <section className="relative px-4 py-24 md:py-32">
        <div className="mx-auto max-w-5xl">
          <motion.div
            initial={{ opacity: 0, y: 40 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: false, margin: "-100px" }}
            transition={{ duration: 0.7 }}
            className="text-center mb-12"
          >
            <h2 className="font-display text-4xl font-bold md:text-6xl">
              <span className="gradient-gold-text">Real-Time</span> Odds Tracking
            </h2>
            <p className="mt-4 text-muted-foreground max-w-xl mx-auto">
              Watch the market move in real time. Our engine captures every odds shift so you never miss a value play.
            </p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 60 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: false, margin: "-50px" }}
            transition={{ duration: 0.8, delay: 0.2 }}
          >
            <CandlestickChart />
          </motion.div>

          {/* Stat Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-10">
            <StatCard icon={Activity} value="12,000+" label="Markets Tracked" index={0} />
            <StatCard icon={DollarSign} value="$80K+" label="Profits Generated" index={1} />
            <StatCard icon={Timer} value="5 sec" label="Avg Update Time" index={2} />
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="relative px-4 py-24 md:py-32">
        <div className="absolute inset-0 bg-radial-gold opacity-20 pointer-events-none" />
        <div className="mx-auto max-w-7xl relative z-10">
          <motion.div
            initial={{ opacity: 0, y: 40 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: false, margin: "-100px" }}
            transition={{ duration: 0.7 }}
            className="text-center mb-16"
          >
            <h2 className="font-display text-4xl font-bold md:text-6xl">
              Your <span className="gradient-gold-text">Unfair Advantage</span>
            </h2>
            <p className="mt-4 text-muted-foreground max-w-xl mx-auto">
              Every tool you need to find, analyze, and execute positive expected value bets.
            </p>
          </motion.div>

          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {features.map((feature, i) => (
              <FeatureCard key={i} index={i} {...feature} />
            ))}
          </div>
        </div>
      </section>

      {/* Rocket Launch Section */}
      <section className="relative px-4 py-16 overflow-hidden">
        <div className="mx-auto max-w-3xl text-center">
          <motion.h2
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: false, margin: "-80px" }}
            transition={{ duration: 0.6 }}
            className="font-display text-4xl font-black uppercase tracking-tighter md:text-5xl glow-text-gold mb-4"
          >
            Watch Your Profits <span className="gradient-gold-text">Take Off</span>
          </motion.h2>
          <RocketLaunch />
        </div>
      </section>

      {/* CTA / Email Sign Up Section */}
      <section className="relative px-4 py-24 md:py-32 overflow-hidden">
        {/* Glow bg */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] rounded-full bg-gold/8 blur-[150px] pointer-events-none" />

        <div className="relative z-10 mx-auto max-w-3xl text-center">
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: false, margin: "-100px" }}
            transition={{ duration: 0.7 }}
          >
            <h2 className="font-display text-4xl font-black uppercase tracking-tighter md:text-6xl glow-text-gold">
              Launch Your Profits
            </h2>

            <div className="mt-12">
              <div className="flex flex-col items-center gap-4 sm:flex-row justify-center">
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="Enter your email"
                  className="w-full rounded-full border border-surface bg-surface px-6 py-4 text-foreground placeholder:text-muted-foreground focus:border-gold focus:outline-none focus:ring-1 focus:ring-gold/50 sm:w-80 transition-all"
                />
                <button className="w-full rounded-full gradient-gold px-8 py-4 font-bold text-primary-foreground transition-all hover:scale-105 active:scale-95 sm:w-auto whitespace-nowrap glow-gold-strong text-base">
                  Get Early Access
                </button>
              </div>

              <div className="mt-8 space-y-2">
                <p className="text-lg text-muted-foreground">
                  Join the first <span className="text-gold font-black">500</span> people to sign up
                </p>
                <p className="text-sm text-muted-foreground/60">
                  Receive a <span className="text-gold font-bold">50% lifetime discount</span> at launch.
                </p>
              </div>
            </div>
          </motion.div>
        </div>

        {/* Floating particles */}
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          {[...Array(15)].map((_, i) => (
            <motion.div
              key={i}
              className="absolute h-1 w-1 rounded-full bg-gold/30"
              initial={{
                x: Math.random() * 100 + "%",
                y: Math.random() * 100 + "%",
                opacity: 0,
              }}
              animate={{
                y: [null, "-100%"],
                opacity: [0, 0.8, 0],
              }}
              transition={{
                duration: Math.random() * 5 + 5,
                repeat: Infinity,
                delay: Math.random() * 5,
              }}
            />
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-surface py-12 px-4 text-center">
        <div className="flex items-center justify-center gap-2 mb-6">
          <div className="h-8 w-8 rounded gradient-gold flex items-center justify-center font-black text-primary-foreground font-display text-sm">S</div>
          <span className="text-xl font-bold tracking-tighter font-display">SHARPEDGE</span>
        </div>
        <p className="text-muted-foreground text-sm">© 2026 SharpEdge Analytics. All rights reserved. Gamble responsibly.</p>
      </footer>
    </div>
  );
};

export default PromoLanding;
