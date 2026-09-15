/**
 * The celebration layer: XP, level-ups, promotions, badges.
 *
 * DESIGN INTENT (spec §2: "do NOT make this visually childish"): no confetti,
 * no bouncing mascots. The reward reads like a system notification from a
 * console that respects you — a precise number, an itemised breakdown of
 * *why* you earned it, and a promotion that feels institutional rather than
 * cartoonish.
 *
 * The itemised breakdown is the actual design goal. A player who can see
 * "+110 tier-8 cleared, +33 first attempt, +30 explained the WHY" learns what
 * the game values, and therefore what good engineering is (spec §63).
 */

import { AnimatePresence, motion } from 'framer-motion';
import { Award, Building2, ChevronsUp, Sparkles, Trophy, Zap } from 'lucide-react';
import { useEffect } from 'react';
import { useRewards, type RewardEvent } from '@/stores/game';
import { cn, titleCase } from '@/lib/utils';
import type { XPGrant } from '@/types/api';

const DWELL_MS: Record<RewardEvent['kind'], number> = {
  xp: 2600,
  badge: 3000,
  achievement: 3200,
  building: 3200,
  level: 3400,
  rank: 4200,
};

const ICONS: Record<RewardEvent['kind'], typeof Zap> = {
  xp: Zap,
  level: ChevronsUp,
  rank: Trophy,
  badge: Award,
  achievement: Sparkles,
  building: Building2,
};

const ACCENTS: Record<RewardEvent['kind'], string> = {
  xp: 'from-signal-xp/25 to-transparent border-signal-xp/40 text-signal-xp',
  level: 'from-accent/25 to-transparent border-accent/50 text-accent',
  rank: 'from-signal-warn/25 to-transparent border-signal-warn/50 text-signal-warn',
  badge: 'from-signal-success/20 to-transparent border-signal-success/40 text-signal-success',
  achievement: 'from-signal-xp/20 to-transparent border-signal-xp/40 text-signal-xp',
  building: 'from-accent/20 to-transparent border-accent/40 text-accent',
};

export function RewardOverlay() {
  const current = useRewards((s) => s.current);
  const next = useRewards((s) => s.next);

  useEffect(() => {
    if (!current) return;
    const timer = setTimeout(next, DWELL_MS[current.kind]);
    return () => clearTimeout(timer);
  }, [current, next]);

  return (
    <div
      className="pointer-events-none fixed inset-x-0 top-20 z-40 flex justify-center px-4"
      // Announced politely: a reward must not interrupt a screen-reader user
      // mid-sentence while they are reading a failure explanation.
      aria-live="polite"
      aria-atomic="true"
    >
      <AnimatePresence mode="wait">
        {current && <RewardCard key={current.id} event={current} onDismiss={next} />}
      </AnimatePresence>
    </div>
  );
}

function RewardCard({ event, onDismiss }: { event: RewardEvent; onDismiss: () => void }) {
  const Icon = ICONS[event.kind];
  const grants = (event.payload?.grants as XPGrant[] | undefined) ?? [];
  const isBig = event.kind === 'level' || event.kind === 'rank';

  return (
    <motion.div
      role="status"
      onClick={onDismiss}
      initial={{ opacity: 0, y: -24, scale: 0.94 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -12, scale: 0.97 }}
      transition={{ type: 'spring', stiffness: 300, damping: 26 }}
      className={cn(
        'pointer-events-auto w-full max-w-md cursor-pointer overflow-hidden rounded-xl border',
        'bg-gradient-to-b from-forge-850 to-forge-900 shadow-2xl backdrop-blur',
        ACCENTS[event.kind].split(' ').filter((c) => c.startsWith('border-')).join(' '),
      )}
    >
      {/* A single sweeping light pass, not a particle storm. */}
      <motion.div
        className={cn('absolute inset-0 bg-gradient-to-b', ACCENTS[event.kind])}
        initial={{ opacity: 0.85 }}
        animate={{ opacity: 0 }}
        transition={{ duration: 1.4, ease: 'easeOut' }}
      />

      <div className="relative flex items-start gap-3.5 p-4">
        <motion.div
          initial={{ scale: 0.5, rotate: isBig ? -14 : 0 }}
          animate={{ scale: 1, rotate: 0 }}
          transition={{ type: 'spring', stiffness: 420, damping: 16 }}
          className={cn(
            'flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border',
            ACCENTS[event.kind],
          )}
        >
          <Icon className="h-5 w-5" aria-hidden />
        </motion.div>

        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <h3
              className={cn(
                'font-display font-semibold tracking-tight',
                isBig ? 'text-lg' : 'text-base',
                ACCENTS[event.kind].split(' ').filter((c) => c.startsWith('text-')).join(' '),
              )}
            >
              {event.title}
            </h3>
          </div>
          {event.subtitle && (
            <p className="mt-0.5 truncate text-xs text-forge-300">
              {event.kind === 'rank' ? titleCase(event.subtitle) : event.subtitle}
            </p>
          )}

          {grants.length > 0 && (
            <ul className="mt-2.5 space-y-1 border-t border-forge-700/70 pt-2">
              {grants.map((grant, i) => (
                <motion.li
                  key={`${grant.source}-${i}`}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.12 + i * 0.07 }}
                  className="flex items-baseline justify-between gap-3 text-xs"
                >
                  <span className="truncate text-forge-400">{grant.reason}</span>
                  <span className="shrink-0 font-mono tabular-nums text-signal-xp">
                    +{grant.amount}
                  </span>
                </motion.li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </motion.div>
  );
}

/**
 * The small "+24 XP" that floats off the element you just interacted with.
 * Separate from the overlay because it is anchored to a position, not to the
 * viewport, and it must not queue — several can play at once.
 */
export function FloatingXP({ amount, className }: { amount: number; className?: string }) {
  return (
    <motion.span
      initial={{ opacity: 0, y: 0, scale: 0.85 }}
      animate={{ opacity: [0, 1, 1, 0], y: -52, scale: [0.85, 1.06, 1, 1] }}
      transition={{ duration: 1.3, times: [0, 0.18, 0.7, 1], ease: 'easeOut' }}
      className={cn(
        'pointer-events-none absolute select-none font-display text-sm font-bold text-signal-xp',
        className,
      )}
      aria-hidden
    >
      +{amount} XP
    </motion.span>
  );
}
