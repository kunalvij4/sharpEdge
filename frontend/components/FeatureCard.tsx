import React from 'react';
import { motion } from 'motion/react';
import { LucideIcon } from 'lucide-react';

interface FeatureCardProps {
  icon: LucideIcon;
  title: string;
  desc: string;
  index: number;
}

const FeatureCard: React.FC<FeatureCardProps> = ({ icon: Icon, title, desc, index }) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 60, rotateX: 15 }}
      whileInView={{ opacity: 1, y: 0, rotateX: 0 }}
      viewport={{ once: false, margin: "-80px" }}
      transition={{
        type: "spring",
        stiffness: 200,
        damping: 20,
        delay: index * 0.15,
      }}
      whileHover={{ y: -8, transition: { duration: 0.2 } }}
      className="group relative rounded-2xl border border-surface bg-surface p-8 transition-colors hover:border-gold/40 overflow-hidden"
    >
      {/* Hover glow */}
      <div className="absolute inset-0 bg-radial-gold opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" />

      <div className="relative z-10">
        <motion.div
          whileHover={{ scale: 1.1, rotate: 5 }}
          className="mb-6 inline-flex h-14 w-14 items-center justify-center rounded-xl bg-gold/10 text-gold group-hover:gradient-gold group-hover:text-primary-foreground transition-all duration-300 glow-gold"
        >
          <Icon size={26} />
        </motion.div>
        <h3 className="font-display text-xl font-bold text-foreground">{title}</h3>
        <p className="mt-3 text-muted-foreground leading-relaxed text-sm">{desc}</p>
      </div>
    </motion.div>
  );
};

export default FeatureCard;
