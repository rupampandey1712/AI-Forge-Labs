/**
 * The Daily Engineering Mission.
 *
 * The critical UI decision here: every slot shows *why the generator chose it*.
 * A daily that looks arbitrary gets skipped; a daily that says "recall on this
 * has fallen to 61% after 34 days" gets done. The reason line is not decoration,
 * it is the retention mechanism made legible.
 */

import { motion } from 'framer-motion';
import { ArrowRight, CheckCircle2, Clock, Flame } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Card, LoadingPanel, Progress, Stat } from '@/components/ui';
import { KindChip, TierChip } from '@/components/game/bits';
import { cn } from '@/lib/utils';
import type { DailySlot } from '@/types/api';

const POOL_LABEL: Record<string, string> = {
  repair: 'Knowledge repair',
  mistake: 'Mistake pattern',
  frontier: 'Next tier up',
  breadth: 'Breadth',
  variety: 'Rotation',
  interview: 'Interview',
};

export default function Daily() {
  const daily = useQuery({ queryKey: ['daily'], queryFn: api.daily.get });
  const history = useQuery({ queryKey: ['daily-history'], queryFn: () => api.daily.history(21) });

  if (daily.isLoading || !daily.data) return <LoadingPanel rows={8} className="mx-auto max-w-4xl" />;

  const data = daily.data;
  const progress = data.slots.length ? data.completed_count / data.slots.length : 0;

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">
            Daily Engineering Mission
          </h1>
          <p className="mt-1 text-sm text-forge-400">
            {new Date(data.for_date).toLocaleDateString(undefined, {
              weekday: 'long',
              day: 'numeric',
              month: 'long',
            })}{' '}
            · assembled from your decay curve, your open mistakes and your current ceiling
          </p>
        </div>
        {data.completed && (
          <span className="chip border-signal-success/40 bg-signal-success/10 text-signal-success">
            Complete · +{data.xp_awarded} XP
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Progress" value={`${data.completed_count}/${data.slots.length}`} accent="#22d3ee" />
        <Stat label="Estimated" value={`${data.estimated_minutes}m`} icon={<Clock className="h-4 w-4" />} />
        <Stat label="Streak" value={data.streak} accent="#fb923c" icon={<Flame className="h-4 w-4" />} />
        <Stat
          label="Repair slots"
          value={data.slots.filter((s) => s.reason.toLowerCase().includes('recall')).length}
          hint="Decaying knowledge"
        />
      </div>

      <Progress value={progress} height={6} />

      <div className="space-y-3">
        {data.slots.map((slot, index) => (
          <SlotCard key={slot.slot} slot={slot} index={index} />
        ))}
      </div>

      {data.generation_reason && Object.keys(data.generation_reason).length > 0 && (
        <Card title="How today's plan was built" subtitle="The generator's own reasoning">
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            {Object.entries(data.generation_reason).map(([key, value]) => (
              <div key={key} className="flex items-baseline justify-between gap-3">
                <dt className="text-forge-500">{key.replace(/_/g, ' ')}</dt>
                <dd className="font-mono text-xs text-forge-300">{String(value)}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs leading-relaxed text-forge-500">
            The plan is fixed for the day. Rerolling would let you dodge exactly the concepts the
            model says you are about to lose — which is the one thing this feature exists to prevent.
          </p>
        </Card>
      )}

      {history.data && history.data.length > 1 && (
        <Card title="Recent days">
          <div className="flex flex-wrap gap-1.5">
            {history.data.map((day) => (
              <div
                key={day.date}
                title={`${day.date}: ${day.completed_slots}/${day.slots}`}
                className={cn(
                  'flex h-9 w-9 flex-col items-center justify-center rounded-md border text-[10px]',
                  day.completed
                    ? 'border-signal-success/40 bg-signal-success/10 text-signal-success'
                    : day.completed_slots > 0
                      ? 'border-signal-warn/40 bg-signal-warn/10 text-signal-warn'
                      : 'border-forge-700 bg-forge-900 text-forge-600',
                )}
              >
                <span className="font-mono">{new Date(day.date).getDate()}</span>
                <span className="font-mono text-[9px] opacity-70">
                  {day.completed_slots}/{day.slots}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function SlotCard({ slot, index }: { slot: DailySlot; index: number }) {
  const href =
    slot.ref_type === 'challenge'
      ? `/app/challenge/${slot.ref_slug}`
      : slot.ref_type === 'mission'
        ? `/app/missions/${slot.ref_slug}`
        : `/app/practice?question=${slot.ref_slug}`;

  // The pool is inferred from the reason text so the label stays in sync with
  // whatever the generator actually said, rather than duplicating its policy.
  const pool = slot.reason.toLowerCase().includes('recall')
    ? 'repair'
    : slot.reason.toLowerCase().includes('you have hit')
      ? 'mistake'
      : slot.reason.toLowerCase().includes('ceiling')
        ? 'frontier'
        : slot.reason.toLowerCase().includes('breadth')
          ? 'breadth'
          : slot.kind === 'interview'
            ? 'interview'
            : 'variety';

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
    >
      <Link
        to={href}
        className={cn(
          'panel panel-hover flex items-start gap-4 p-4',
          slot.completed && 'border-signal-success/30 bg-signal-success/5',
        )}
      >
        <div className="mt-0.5 shrink-0">
          {slot.completed ? (
            <CheckCircle2 className="h-5 w-5 text-signal-success" />
          ) : (
            <span className="flex h-5 w-5 items-center justify-center rounded-full border border-forge-600 font-mono text-[11px] text-forge-400">
              {slot.slot + 1}
            </span>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="chip border-forge-600 bg-forge-800/70 text-forge-400">
              {POOL_LABEL[pool]}
            </span>
            <KindChip kind={slot.kind} />
            <TierChip tier={slot.tier} />
            <span className="ml-auto text-[11px] text-forge-500">~{slot.estimated_minutes}m</span>
          </div>

          <h3
            className={cn(
              'mt-2 text-sm font-medium',
              slot.completed ? 'text-forge-500 line-through' : 'text-forge-100',
            )}
          >
            {slot.title}
          </h3>

          <p
            className={cn(
              'mt-1 text-xs leading-relaxed',
              pool === 'repair' ? 'text-signal-decay' : 'text-forge-500',
            )}
          >
            {slot.reason}
          </p>

          {slot.completed && slot.score !== null && (
            <div className="mt-1.5 font-mono text-[11px] text-signal-success">
              scored {(slot.score * 100).toFixed(0)}%
            </div>
          )}
        </div>

        {!slot.completed && (
          <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-forge-500" aria-hidden />
        )}
      </Link>
    </motion.div>
  );
}
