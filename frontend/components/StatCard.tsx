import React from 'react';
import { motion } from 'motion/react';
import { LucideIcon } from 'lucide-react';

interface StatCardProps {
  icon: LucideIcon;
  value: string;
  label: string;
  index: number;
}

const StatCard: React.FC<StatCardProps> = ({ icon: Icon, value, label, index }) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 40, scale: 0.9 }}
      whileInView={{ opacity: 1, y: 0, scale: 1 }}
      viewport={{ once: false, margin: "-60px" }}
      transition={{
        type: "spring",
        stiffness: 200,
        damping: 20,
        delay: index * 0.12,
      }}
      className="group relative rounded-2xl border border-surface bg-surface p-6 text-center overflow-hidden hover:border-gold/30 transition-colors"
    >
      <div className="absolute inset-0 bg-radial-gold opacity-0 group-hover:opacity-60 transition-opacity duration-500 pointer-events-none" />
      <div className="relative z-10">
        <div className="mx-auto mb-3 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-gold/10 text-gold glow-gold">
          <Icon size={22} />
        </div>
        <p className="text-3xl font-black font-display gradient-gold-text">{value}</p>
        <p className="mt-1 text-sm text-muted-foreground uppercase tracking-wider">{label}</p>
      </div>
    </motion.div>
  );
};

export default StatCard;
