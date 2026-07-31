import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import { motion, useInView, AnimatePresence } from 'motion/react';

interface Candle {
  id: number;
  open: number;
  close: number;
  high: number;
  low: number;
  time: string;
}

let candleIdCounter = 0;

const toAmericanOdds = (decimal: number): string => {
  if (decimal >= 2.0) {
    return '+' + Math.round((decimal - 1) * 100);
  }
  return '-' + Math.round(100 / (decimal - 1));
};

const generateCandle = (price: number, time: string): { candle: Candle; newPrice: number } => {
  const change = (Math.random() - 0.45) * 0.15;
  const open = price;
  const close = price + change;
  const high = Math.max(open, close) + Math.random() * 0.08;
  const low = Math.min(open, close) - Math.random() * 0.08;
  return {
    candle: { id: candleIdCounter++, open, close, high, low, time },
    newPrice: close,
  };
};

const VISIBLE_CANDLES = 14;

const formatTime = (totalMinutes: number): string => {
  const hours24 = Math.floor(totalMinutes / 60) % 24;
  const mins = totalMinutes % 60;
  const period = hours24 >= 12 ? 'PM' : 'AM';
  const hours12 = hours24 % 12 || 12;
  return `${hours12}:${mins.toString().padStart(2, '0')} ${period}`;
};

const CandlestickChart: React.FC = () => {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: false, margin: "-50px" });
  const [allCandles, setAllCandles] = useState<Candle[]>([]);
  const [revealedCount, setRevealedCount] = useState(0);
  const [isStreaming, setIsStreaming] = useState(false);
  const priceRef = useRef(2.10);
  const timeRef = useRef(9 * 60);
  // Track IDs that have already been shown (so they don't re-animate)
  const shownIdsRef = useRef<Set<number>>(new Set());

  const addCandle = useCallback(() => {
    const time = formatTime(timeRef.current);
    const { candle, newPrice } = generateCandle(priceRef.current, time);
    priceRef.current = Math.max(1.3, Math.min(4.5, newPrice));
    timeRef.current += 5;
    setAllCandles(prev => [...prev, candle]);
  }, []);

  // Generate initial batch when in view
  useEffect(() => {
    if (!isInView) {
      setRevealedCount(0);
      setAllCandles([]);
      setIsStreaming(false);
      priceRef.current = 2.10;
      timeRef.current = 9 * 60;
      shownIdsRef.current = new Set();
      return;
    }

    if (allCandles.length === 0) {
      const initial: Candle[] = [];
      let p = 2.10;
      let t = 9 * 60;
      for (let i = 0; i < VISIBLE_CANDLES; i++) {
        const time = formatTime(t);
        const { candle, newPrice } = generateCandle(p, time);
        p = Math.max(1.3, Math.min(4.5, newPrice));
        t += 5;
        initial.push(candle);
      }
      priceRef.current = p;
      timeRef.current = t;
      setAllCandles(initial);
    }
  }, [isInView]);

  // Slow reveal of initial candles
  useEffect(() => {
    if (!isInView || allCandles.length === 0) return;
    if (revealedCount >= VISIBLE_CANDLES && !isStreaming) {
      setIsStreaming(true);
      return;
    }
    if (revealedCount >= allCandles.length) return;
    if (isStreaming) return;
    const timer = setTimeout(() => setRevealedCount(v => v + 1), 300);
    return () => clearTimeout(timer);
  }, [isInView, revealedCount, allCandles.length, isStreaming]);

  // Streaming: add one candle at a time
  useEffect(() => {
    if (!isStreaming || !isInView) return;
    const interval = setInterval(() => {
      addCandle();
      setRevealedCount(v => v + 1);
    }, 1500);
    return () => clearInterval(interval);
  }, [isStreaming, isInView, addCandle]);

  // Compute the visible window
  const windowStart = Math.max(0, revealedCount - VISIBLE_CANDLES);
  const displayCandles = allCandles.slice(windowStart, revealedCount);

  // Smoothly interpolated price range to avoid jumpy rescaling
  const targetMinPrice = useMemo(() => {
    if (displayCandles.length === 0) return 1.75;
    return Math.min(...displayCandles.map(c => c.low)) - 0.05;
  }, [displayCandles]);

  const targetMaxPrice = useMemo(() => {
    if (displayCandles.length === 0) return 2.45;
    return Math.max(...displayCandles.map(c => c.high)) + 0.05;
  }, [displayCandles]);

  const minPrice = targetMinPrice;
  const maxPrice = targetMaxPrice;
  const priceRange = maxPrice - minPrice || 0.5;

  const chartH = 320;
  const chartW = 700;
  const candleW = 28;
  const totalGap = chartW - VISIBLE_CANDLES * candleW;
  const gapSize = totalGap / (VISIBLE_CANDLES + 1);

  const toY = (price: number) => chartH - ((price - minPrice) / priceRange) * chartH;

  const gridLines = 5;
  const priceStep = priceRange / gridLines;

  const lastCandle = displayCandles[displayCandles.length - 1];
  const bestOdds = displayCandles.length > 0
    ? toAmericanOdds(Math.max(...displayCandles.map(c => Math.max(c.open, c.close))))
    : '+210';

  return (
    <div ref={ref} className="relative w-full rounded-2xl border border-surface bg-surface p-6 sm:p-8 glow-gold overflow-hidden">
      <div className="absolute inset-0 bg-radial-gold opacity-50 pointer-events-none" />

      <div className="relative z-10">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="font-display text-xl font-bold text-foreground">Lakers vs Celtics — Moneyline</h3>
            <p className="text-sm text-muted-foreground mt-1">Odds movement across 12 sportsbooks</p>
          </div>
          <div className="flex items-center gap-3">
            {isStreaming && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-center gap-1.5"
              >
                <motion.div
                  animate={{ scale: [1, 1.3, 1] }}
                  transition={{ repeat: Infinity, duration: 1.5 }}
                  className="w-2 h-2 rounded-full bg-candle-green"
                />
                <span className="text-xs text-muted-foreground uppercase tracking-wider">Live</span>
              </motion.div>
            )}
            <motion.div
              initial={{ opacity: 0, scale: 0.8 }}
              animate={revealedCount > 5 ? { opacity: 1, scale: 1 } : {}}
              className="rounded-lg bg-candle-green/10 px-3 py-1.5 ring-1 ring-candle-green/30"
            >
              <span className="text-candle-green font-bold text-sm">Best: {bestOdds}</span>
            </motion.div>
          </div>
        </div>

        <svg viewBox={`0 0 ${chartW} ${chartH + 30}`} className="w-full" preserveAspectRatio="xMidYMid meet">
          {/* Grid — uses transition for smooth rescaling */}
          {Array.from({ length: gridLines + 1 }, (_, i) => {
            const price = minPrice + i * priceStep;
            const y = toY(price);
            return (
              <g key={i}>
                <line x1="0" y1={y} x2={chartW} y2={y} stroke="hsl(240 4% 16%)" strokeWidth="0.5" />
                <text x={chartW - 4} y={y - 4} fill="hsl(240 5% 45%)" fontSize="10" textAnchor="end" fontFamily="Inter">
                  {toAmericanOdds(price)}
                </text>
              </g>
            );
          })}

          {/* Candles with AnimatePresence for smooth enter/exit */}
          <AnimatePresence initial={false}>
            {displayCandles.map((candle, i) => {
              const x = gapSize + i * (candleW + gapSize);
              const isGreen = candle.close >= candle.open;
              const bodyTop = toY(Math.max(candle.open, candle.close));
              const bodyBottom = toY(Math.min(candle.open, candle.close));
              const bodyHeight = Math.max(bodyBottom - bodyTop, 2);
              const wickTop = toY(candle.high);
              const wickBottom = toY(candle.low);
              const color = isGreen ? 'hsl(142, 76%, 36%)' : 'hsl(0, 72%, 51%)';
              const isLast = i === displayCandles.length - 1;
              const isNew = !shownIdsRef.current.has(candle.id);

              // Mark as shown after this render
              if (isNew) shownIdsRef.current.add(candle.id);

              return (
                <motion.g
                  key={candle.id}
                  initial={isNew ? { opacity: 0 } : false}
                  animate={{
                    opacity: 1,
                    x: 0,
                  }}
                  exit={{ opacity: 0, x: -40 }}
                  transition={{ duration: 0.6, ease: 'easeInOut' }}
                >
                  {/* Wick */}
                  <motion.line
                    x1={x + candleW / 2} y1={wickTop}
                    x2={x + candleW / 2} y2={wickBottom}
                    stroke={color} strokeWidth="1.5"
                    animate={{ y1: wickTop, y2: wickBottom }}
                    transition={{ duration: 0.5 }}
                  />
                  {/* Body */}
                  <motion.rect
                    x={x} width={candleW} fill={color} rx="2"
                    animate={{ y: bodyTop, height: bodyHeight }}
                    transition={{ duration: 0.5 }}
                  />
                  {/* Glow on green */}
                  {isGreen && (
                    <motion.rect
                      x={x - 2} width={candleW + 4}
                      fill="none" stroke={color} strokeWidth="1" opacity="0.3" rx="3"
                      animate={{ y: bodyTop - 2, height: bodyHeight + 4 }}
                      transition={{ duration: 0.5 }}
                    />
                  )}
                  {/* Pulse on latest */}
                  {isLast && isStreaming && (
                    <motion.rect
                      x={x - 4} width={candleW + 8}
                      fill="none" stroke="hsl(38, 92%, 50%)" strokeWidth="1" rx="4"
                      animate={{
                        y: bodyTop - 4,
                        height: bodyHeight + 8,
                        opacity: [0.6, 0, 0.6],
                      }}
                      transition={{ opacity: { repeat: Infinity, duration: 1.5 }, duration: 0.5 }}
                    />
                  )}
                  {/* Time labels */}
                  {i % 3 === 0 && (
                    <text x={x + candleW / 2} y={chartH + 18} fill="hsl(240 5% 40%)" fontSize="9" textAnchor="middle" fontFamily="Inter">
                      {candle.time}
                    </text>
                  )}
                </motion.g>
              );
            })}
          </AnimatePresence>

          {/* Current price line */}
          {lastCandle && (
            <motion.line
              x1={0} x2={chartW}
              stroke="hsl(38, 92%, 50%)" strokeWidth="1" strokeDasharray="4 3"
              animate={{ y1: toY(lastCandle.close), y2: toY(lastCandle.close), opacity: 0.5 }}
              transition={{ duration: 0.5 }}
            />
          )}
        </svg>

        {/* Legend */}
        <div className="flex gap-6 mt-4">
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-sm bg-candle-green" />
            <span className="text-xs text-muted-foreground uppercase tracking-wider">Odds Rising</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-sm bg-candle-red" />
            <span className="text-xs text-muted-foreground uppercase tracking-wider">Odds Falling</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-0.5 w-4 bg-gold border-dashed" />
            <span className="text-xs text-muted-foreground uppercase tracking-wider">Current Line</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CandlestickChart;
