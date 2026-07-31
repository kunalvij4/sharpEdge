import React, { useState, useRef, useEffect, useMemo } from 'react';
import { motion, useInView, AnimatePresence } from 'motion/react';
import { Rocket, DollarSign } from 'lucide-react';

interface ConfettiPiece {
  id: number;
  x: number;
  y: number;
  rotation: number;
  delay: number;
  duration: number;
  isDollar: boolean;
  size: number;
}

const RocketLaunch: React.FC = () => {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: false, margin: "-100px" });
  const [phase, setPhase] = useState<'idle' | 'launching' | 'exploded'>('idle');

  useEffect(() => {
    if (!isInView) {
      setPhase('idle');
      return;
    }
    setPhase('launching');
    const timer = setTimeout(() => setPhase('exploded'), 1800);
    return () => clearTimeout(timer);
  }, [isInView]);

  // Stable confetti pieces — memoized so they don't regenerate on every render
  const confettiPieces = useMemo<ConfettiPiece[]>(() =>
    [...Array(50)].map((_, i) => ({
      id: i,
      x: (Math.random() - 0.5) * 400,
      y: -(Math.random() * 300 + 50),
      rotation: Math.random() * 720 - 360,
      delay: Math.random() * 0.4,
      duration: Math.random() * 1.5 + 1.5,
      isDollar: Math.random() > 0.4,
      size: Math.random() * 16 + 14,
    })),
  []);

  const rainPieces = useMemo(() =>
    [...Array(25)].map((_, i) => ({
      id: i,
      leftPct: Math.random() * 100,
      rotateEnd: Math.random() * 720,
      duration: Math.random() * 2 + 2,
      delay: Math.random() * 2 + 0.5,
    })),
  []);

  return (
    <div ref={ref} className="relative flex items-center justify-center h-[350px] overflow-hidden">
      {/* Rocket */}
      <AnimatePresence>
        {phase !== 'exploded' && (
          <motion.div
            className="flex flex-col items-center z-20"
            initial={{ y: 200, opacity: 0 }}
            animate={phase === 'launching'
              ? { y: [200, -20], opacity: [0, 1, 1], scale: [0.8, 1.2] }
              : { y: 200, opacity: 0 }
            }
            exit={{ scale: [1.2, 2], opacity: [1, 0] }}
            transition={{ duration: 1.8, ease: 'easeOut' }}
          >
            <Rocket size={56} className="text-gold rotate-[-45deg]" />
            <motion.div
              animate={{ scaleY: [1, 1.8, 1], opacity: [0.6, 1, 0.6] }}
              transition={{ repeat: Infinity, duration: 0.12 }}
              className="mt-1 h-12 w-4 bg-gradient-to-t from-transparent via-candle-red to-gold blur-sm rounded-full"
            />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Explosion flash */}
      <AnimatePresence>
        {phase === 'exploded' && (
          <motion.div
            initial={{ scale: 0, opacity: 1 }}
            animate={{ scale: [0, 3], opacity: [1, 0] }}
            transition={{ duration: 0.6 }}
            className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-32 h-32 rounded-full bg-gold/40 blur-xl z-10"
          />
        )}
      </AnimatePresence>

      {/* Dollar confetti — burst from center */}
      <AnimatePresence>
        {phase === 'exploded' && confettiPieces.map((piece) => (
          <motion.div
            key={piece.id}
            className="absolute left-1/2 top-1/2 z-30 font-black"
            initial={{ x: '-50%', y: '-50%', opacity: 0, scale: 0, rotate: 0 }}
            animate={{
              x: piece.x,
              y: [piece.y, piece.y + 500],
              opacity: [0, 1, 1, 0],
              scale: [0, 1.2, 1],
              rotate: piece.rotation,
            }}
            transition={{
              duration: piece.duration,
              delay: piece.delay,
              ease: 'easeOut',
            }}
          >
            {piece.isDollar ? (
              <DollarSign className="text-gold drop-shadow-[0_0_8px_hsla(38,92%,50%,0.6)]" size={piece.size} />
            ) : (
              <span className="text-gold/80" style={{ fontSize: piece.size }}>$</span>
            )}
          </motion.div>
        ))}
      </AnimatePresence>

      {/* Persistent rain — positioned with left % so they span the container */}
      {phase === 'exploded' && (
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          {rainPieces.map((p) => (
            <motion.div
              key={`rain-${p.id}`}
              className="absolute text-gold/50 font-black text-2xl"
              style={{ left: `${p.leftPct}%` }}
              initial={{ y: "-10%", rotate: 0, opacity: 0 }}
              animate={{
                y: "110%",
                rotate: p.rotateEnd,
                opacity: [0, 0.7, 0.7, 0],
              }}
              transition={{
                duration: p.duration,
                repeat: Infinity,
                delay: p.delay,
                ease: "linear",
              }}
            >
              $
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
};

export default RocketLaunch;
