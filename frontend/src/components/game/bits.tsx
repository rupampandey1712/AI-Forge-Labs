/** Small, reusable game-domain display components. */

import { motion } from 'framer-motion';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Flame } from 'lucide-react';
import { cn, KIND_STYLES, masteryColor, severityColor, TIER_LABELS, tierColor } from '@/lib/utils';
import { Tooltip } from '@/components/ui';
import { fadeUp, hoverLift, REDUCED_MOTION, stagger } from '@/lib/motion';

/** The difficulty ladder made visible. Tier is the spine of the whole game. */
export function TierChip({ tier, showLabel = false }: { tier: number; showLabel?: boolean }) {
  return (
    <Tooltip label={`Tier ${tier} — ${TIER_LABELS[tier] ?? 'Unknown'}`}>
      <span className={cn('chip', tierColor(tier))}>
        T{tier}
        {showLabel && <span className="normal-case tracking-normal">{TIER_LABELS[tier]}</span>}
      </span>
    </Tooltip>
  );
}

export function SeverityChip({ severity }: { severity: string }) {
  return (
    <span className={cn('chip', severityColor[severity] ?? severityColor.low)}>{severity}</span>
  );
}

/**
 * A mastery bar that shows BOTH current and decayed values.
 *
 * This double-bar is the most important two pixels in the UI: the ghosted
 * segment is knowledge the player has lost. Showing only one number would hide
 * the entire premise of the retention engine.
 */
export function MasteryBar({
  mastery,
  effective,
  label,
  className,
}: {
  mastery: number;
  effective?: number;
  label?: string;
  className?: string;
}) {
  const decayed = effective !== undefined && effective < mastery - 0.01;
  const color = masteryColor(effective ?? mastery);

  return (
    <div className={cn('w-full', className)}>
      {label && (
        <div className="mb-1 flex items-baseline justify-between gap-2">
          <span className="truncate text-xs text-forge-300">{label}</span>
          <span className="shrink-0 font-mono text-xs tabular-nums">
            <span style={{ color }}>{((effective ?? mastery) * 100).toFixed(0)}%</span>
            {decayed && (
              <span className="ml-1 text-forge-500 line-through">
                {(mastery * 100).toFixed(0)}%
              </span>
            )}
          </span>
        </div>
      )}
      <div className="relative h-2 w-full overflow-hidden rounded-full bg-forge-800">
        {/* Peak mastery, ghosted — the height you reached. */}
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-forge-600/70"
          style={{ width: `${Math.min(100, mastery * 100)}%` }}
        />
        {/* Effective mastery — where you are today. */}
        <motion.div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ backgroundColor: color }}
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(100, (effective ?? mastery) * 100)}%` }}
          transition={{ type: 'spring', stiffness: 110, damping: 20 }}
        />
      </div>
    </div>
  );
}

/** GitHub-style activity grid. Habit is the product; make it visible. */
export function StreakCalendar({
  days,
  streak,
  className,
}: {
  days: { date: string; count: number }[];
  streak: number;
  className?: string;
}) {
  const max = Math.max(1, ...days.map((d) => d.count));
  const intensity = (count: number) => {
    if (count === 0) return 'bg-forge-800';
    const ratio = count / max;
    if (ratio > 0.75) return 'bg-accent';
    if (ratio > 0.5) return 'bg-accent/70';
    if (ratio > 0.25) return 'bg-accent/45';
    return 'bg-accent/25';
  };

  return (
    <div className={className}>
      <div className="mb-2 flex items-center justify-between">
        <span className="stat-label">Activity</span>
        <span className="flex items-center gap-1 text-xs font-medium text-signal-decay">
          <Flame className="h-3.5 w-3.5" aria-hidden />
          {streak} day{streak === 1 ? '' : 's'}
        </span>
      </div>
      <div className="grid grid-flow-col grid-rows-7 gap-[3px]" role="img" aria-label={`${streak} day streak`}>
        {days.map((day) => (
          <Tooltip key={day.date} label={`${day.date}: ${day.count} action${day.count === 1 ? '' : 's'}`}>
            <span className={cn('h-2.5 w-2.5 rounded-[2px]', intensity(day.count))} />
          </Tooltip>
        ))}
      </div>
    </div>
  );
}

/** Circular gauge for the composite scores (readiness, debugging, …). */
export function Gauge({
  value,
  label,
  size = 96,
  color,
}: {
  value: number;
  label: string;
  size?: number;
  color?: string;
}) {
  const clamped = Math.max(0, Math.min(1, value));
  const stroke = 7;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const resolved = color ?? masteryColor(clamped);

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth={stroke}
            className="text-forge-800"
          />
          <motion.circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={resolved}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            initial={{ strokeDashoffset: circumference }}
            animate={{ strokeDashoffset: circumference * (1 - clamped) }}
            transition={{ type: 'spring', stiffness: 60, damping: 18 }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="font-display text-lg font-semibold tabular-nums" style={{ color: resolved }}>
            {(clamped * 100).toFixed(0)}
          </span>
        </div>
      </div>
      <span className="text-center text-[11px] leading-tight text-forge-400">{label}</span>
    </div>
  );
}

export function KindChip({ kind }: { kind: string }) {
  const style = KIND_STYLES[kind] ?? {
    label: kind.replace(/_/g, ' '),
    className: 'border-forge-600 bg-forge-800 text-forge-300',
  };
  return <span className={cn('chip', style.className)}>{style.label}</span>;
}

/**
 * A list or grid whose children cascade in.
 *
 * WHY A WRAPPER rather than animating every card at its own call site: the
 * cascade only reads as deliberate if every list in the app uses the same
 * timing, and a per-page `transition={{ delay: i * 0.05 }}` guarantees it will
 * not. This also keeps the index arithmetic out of the page — children inherit
 * `hidden`/`show` from the parent variant, so no child needs to know its own
 * position.
 *
 * `as` exists because the semantic element matters: a list of concepts should
 * be a `<ul>` even when it is laid out as a grid.
 */
export function Stagger({
  children,
  className,
  delay = 0.04,
  as = 'div',
}: {
  children: ReactNode;
  className?: string;
  /** Seconds between children. Small on purpose — 12 cards at 60ms is already
   *  at the edge of feeling slow rather than intentional. */
  delay?: number;
  as?: 'div' | 'ul';
}) {
  const Component = as === 'ul' ? motion.ul : motion.div;
  return (
    <Component
      variants={stagger(delay)}
      initial="hidden"
      animate="show"
      className={className}
    >
      {children}
    </Component>
  );
}

/**
 * One child of a <Stagger>. Lifts on hover when it is interactive.
 *
 * Note it renders a plain `motion.div` wrapper rather than cloning the child:
 * cards in this codebase are `<Link>`s, `<button>`s and `<section>`s, and
 * wrapping is the only approach that works for all three without each caller
 * knowing which it has.
 */
export function StaggerItem({
  children,
  className,
  interactive = false,
  as = 'div',
}: {
  children: ReactNode;
  className?: string;
  interactive?: boolean;
  as?: 'div' | 'li';
}) {
  const Component = as === 'li' ? motion.li : motion.div;
  return (
    <Component variants={fadeUp} className={className} {...(interactive ? hoverLift : {})}>
      {children}
    </Component>
  );
}

/**
 * A number that counts up to its value rather than snapping.
 *
 * Used for XP, coins and streaks, where the *change* is the reward. A total
 * that jumps from 1,240 to 1,308 communicates the new total; one that counts up
 * communicates that you earned 68.
 *
 * Skips the animation entirely under reduced motion, and on the first render,
 * so a page load does not spend 700ms counting every stat up from zero.
 */
export function CountUp({
  value,
  duration = 0.7,
  className,
  format = (n: number) => Math.round(n).toLocaleString(),
}: {
  value: number;
  duration?: number;
  className?: string;
  format?: (n: number) => string;
}) {
  const [display, setDisplay] = useState(value);
  const previous = useRef(value);

  useEffect(() => {
    const from = previous.current;
    previous.current = value;
    if (REDUCED_MOTION || from === value) {
      setDisplay(value);
      return;
    }
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / (duration * 1000));
      // Ease-out cubic: fast at first, settling at the end. A linear count
      // reads as a loading spinner rather than as a value arriving.
      const eased = 1 - (1 - t) ** 3;
      setDisplay(from + (value - from) * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);

  return <span className={cn('tabular-nums', className)}>{format(display)}</span>;
}
