import React, { useState, useEffect } from 'react';
import { motion } from 'motion/react';

interface TypewriterHeadingProps {
  text: string;
  highlightWords?: string[];
  className?: string;
  speed?: number;
  startDelay?: number;
}

const TypewriterHeading: React.FC<TypewriterHeadingProps> = ({
  text,
  highlightWords = [],
  className = '',
  speed = 60,
  startDelay = 400,
}) => {
  const [displayedCount, setDisplayedCount] = useState(0);
  const [started, setStarted] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setStarted(true), startDelay);
    return () => clearTimeout(t);
  }, [startDelay]);

  useEffect(() => {
    if (!started) return;
    if (displayedCount >= text.length) return;
    const timer = setTimeout(() => setDisplayedCount(c => c + 1), speed);
    return () => clearTimeout(timer);
  }, [started, displayedCount, text.length, speed]);

  // Split into words, track char positions
  const words = text.split(' ');
  let charIndex = 0;

  return (
    <h1 className={className}>
      {words.map((word, wi) => {
        const wordStart = charIndex;
        const wordEnd = charIndex + word.length;
        charIndex = wordEnd + 1; // +1 for space

        const isHighlight = highlightWords.includes(word.replace(/[^a-zA-Z]/g, ''));

        // Render each character
        const chars = word.split('').map((char, ci) => {
          const globalIdx = wordStart + ci;
          const visible = globalIdx < displayedCount;
          return (
            <span
              key={ci}
              style={{ opacity: visible ? 1 : 0, transition: 'opacity 0.05s' }}
            >
              {char}
            </span>
          );
        });

        return (
          <span
            key={wi}
            className={`inline-block mr-3 ${isHighlight ? 'gradient-gold-text' : ''}`}
          >
            {chars}
          </span>
        );
      })}
      {/* Blinking cursor */}
      {displayedCount < text.length && (
        <motion.span
          animate={{ opacity: [1, 0, 1] }}
          transition={{ repeat: Infinity, duration: 0.8 }}
          className="inline-block w-[3px] sm:w-[4px] h-[0.85em] bg-gold ml-1 align-middle rounded-sm"
        />
      )}
    </h1>
  );
};

export default TypewriterHeading;
