/**
 * Instrument controls.
 *
 * The labs are tuning benches, so the control is the primary interface — not a
 * form field you fill in and submit. Three properties matter and none of them
 * are decorative:
 *
 * 1. **The current value is always visible**, in monospace, tabular-aligned.
 *    "chunk_size: 400" is the thing the player is reasoning about; hiding it
 *    behind a thumb position makes the experiment unrepeatable.
 * 2. **Every control carries a `hint`** saying what moving it trades away.
 *    A slider with no stated trade-off teaches fiddling, not engineering.
 * 3. **Changing a control marks the result stale** rather than silently
 *    refetching, so the numbers on screen always belong to the settings on
 *    screen. That is the single most important honesty property of a bench.
 */

import { motion } from 'framer-motion';
import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { quick, spring } from '@/lib/motion';

export function Slider({
  label,
  hint,
  value,
  min,
  max,
  step = 1,
  suffix = '',
  disabled,
  onChange,
}: {
  label: string;
  hint?: ReactNode;
  value: number;
  min: number;
  max: number;
  step?: number;
  suffix?: string;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  const fraction = max === min ? 0 : (value - min) / (max - min);
  return (
    <label className={cn('block select-none', disabled && 'opacity-50')}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-xs font-medium text-forge-200">{label}</span>
        <motion.span
          // Keyed on the value so each change re-mounts and pops: the number is
          // the feedback, and a number that changes without moving is missable.
          key={value}
          initial={{ scale: 1.18, color: '#22d3ee' }}
          animate={{ scale: 1, color: '#bcc6e3' }}
          transition={quick}
          className="font-mono text-xs tabular-nums"
        >
          {value}
          {suffix}
        </motion.span>
      </div>
      <div className="relative mt-2 h-5">
        <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-forge-800" />
        <motion.div
          className="absolute left-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-accent"
          animate={{ width: `${fraction * 100}%` }}
          transition={spring}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(Number(e.target.value))}
          className="lab-range absolute inset-0 w-full cursor-pointer appearance-none bg-transparent"
          aria-label={label}
        />
      </div>
      {hint && <p className="mt-1 text-[11px] leading-snug text-forge-500">{hint}</p>}
    </label>
  );
}

export function Toggle({
  label,
  hint,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  hint?: ReactNode;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className={cn('flex items-start gap-3', disabled && 'opacity-50')}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          'mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors duration-200',
          checked ? 'border-accent/60 bg-accent/25' : 'border-forge-600 bg-forge-800',
        )}
      >
        <motion.span
          className={cn(
            'block h-3.5 w-3.5 rounded-full',
            checked ? 'bg-accent shadow-glow' : 'bg-forge-400',
          )}
          animate={{ x: checked ? 19 : 3 }}
          transition={spring}
        />
      </button>
      <div className="min-w-0">
        <span className="block text-xs font-medium text-forge-200">{label}</span>
        {hint && <p className="mt-0.5 text-[11px] leading-snug text-forge-500">{hint}</p>}
      </div>
    </div>
  );
}

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string; hint?: string }[];
  value: T;
  onChange: (value: T) => void;
  label?: string;
}) {
  return (
    <div>
      {label && <span className="mb-1.5 block text-xs font-medium text-forge-200">{label}</span>}
      <div className="flex gap-1 rounded-lg border border-forge-700 bg-forge-900/70 p-1">
        {options.map((option) => {
          const active = option.value === value;
          return (
            <button
              key={String(option.value)}
              type="button"
              title={option.hint}
              onClick={() => onChange(option.value)}
              className={cn(
                'relative flex-1 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors',
                active ? 'text-forge-950' : 'text-forge-300 hover:text-forge-100',
              )}
            >
              {active && (
                <motion.span
                  // One shared layoutId makes the pill *slide* between options
                  // instead of blinking — the movement is what shows which
                  // option you came from.
                  layoutId={`seg-${label ?? 'x'}`}
                  className="absolute inset-0 rounded-md bg-accent"
                  transition={spring}
                />
              )}
              <span className="relative z-10">{option.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Marks readouts as belonging to settings that have since changed.
 *
 * Without this a bench lies: you move `top_k`, the old numbers stay on screen,
 * and you attribute them to the new setting. Dimming plus an explicit "stale"
 * badge is cheaper than refetching on every keystroke and more honest than
 * showing nothing.
 */
export function Stale({ stale, children }: { stale: boolean; children: ReactNode }) {
  return (
    <div className="relative">
      <motion.div animate={{ opacity: stale ? 0.42 : 1 }} transition={quick}>
        {children}
      </motion.div>
      {stale && (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="pointer-events-none absolute right-3 top-3 rounded-full border border-signal-warn/40 bg-signal-warn/15 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-signal-warn"
        >
          Stale — rerun
        </motion.div>
      )}
    </div>
  );
}

/** A labelled number with an optional delta against a baseline. */
export function Readout({
  label,
  value,
  delta,
  hint,
  good = 'up',
  mono = true,
}: {
  label: string;
  value: string | number;
  delta?: number;
  hint?: string;
  /** Which direction counts as an improvement — latency is the obvious 'down'. */
  good?: 'up' | 'down';
  mono?: boolean;
}) {
  const improved = delta === undefined ? null : good === 'up' ? delta > 0 : delta < 0;
  return (
    <div className="rounded-lg border border-forge-700/70 bg-forge-900/50 px-3 py-2.5" title={hint}>
      <div className="text-[10px] uppercase tracking-wide text-forge-500">{label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <motion.span
          key={String(value)}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={quick}
          className={cn('text-lg font-semibold text-forge-100', mono && 'font-mono tabular-nums')}
        >
          {value}
        </motion.span>
        {delta !== undefined && Math.abs(delta) > 1e-9 && (
          <span
            className={cn(
              'font-mono text-[11px] tabular-nums',
              improved ? 'text-signal-success' : 'text-signal-danger',
            )}
          >
            {delta > 0 ? '+' : ''}
            {delta.toFixed(3)}
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * The lab's own commentary on what just happened.
 *
 * Every lab returns a `diagnosis` / `insight` string from the backend, and it
 * renders in the same place with the same treatment everywhere. That
 * consistency is the point: the player learns that the instrument always tells
 * them what the numbers mean, so they stop guessing.
 */
export function Insight({
  children,
  tone = 'info',
}: {
  children: ReactNode;
  tone?: 'info' | 'warn' | 'danger' | 'success';
}) {
  const tones = {
    info: 'border-accent/30 bg-accent/[0.07] text-forge-200',
    warn: 'border-signal-warn/35 bg-signal-warn/[0.08] text-forge-200',
    danger: 'border-signal-danger/35 bg-signal-danger/[0.08] text-forge-200',
    success: 'border-signal-success/35 bg-signal-success/[0.08] text-forge-200',
  };
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={spring}
      className={cn('rounded-lg border px-3.5 py-2.5 text-xs leading-relaxed', tones[tone])}
    >
      {children}
    </motion.div>
  );
}
