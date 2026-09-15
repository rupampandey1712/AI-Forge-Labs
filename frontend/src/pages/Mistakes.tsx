/**
 * The Mistake Log.
 *
 * A mistake here is a *named pattern*, not a wrong answer. That distinction is
 * the whole design: "blocking_call_in_async" is something you can stop doing;
 * "you got question 47 wrong" is not. Records stay open until several clean
 * submissions in a row close them, because getting it right once is luck.
 */

import { Bug, CheckCircle2, Clock } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Card, Chip, EmptyState, LoadingPanel, Stat } from '@/components/ui';
import { SeverityChip } from '@/components/game/bits';
import { cn, relativeTime, titleCase } from '@/lib/utils';

const CLEAN_STREAK_TARGET = 3;

export default function Mistakes() {
  const [includeResolved, setIncludeResolved] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ['mistakes', includeResolved],
    queryFn: () => api.retention.mistakes(includeResolved),
  });

  if (isLoading || !data) return <LoadingPanel rows={6} className="mx-auto max-w-4xl" />;

  const open = data.filter((m) => !m.resolved);
  const resolved = data.filter((m) => m.resolved);
  const critical = open.filter((m) => m.severity === 'critical').length;

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">Mistake Log</h1>
          <p className="mt-1 text-sm text-forge-400">
            Patterns detected in your submissions. Each one closes after{' '}
            {CLEAN_STREAK_TARGET} consecutive clean passes — a habit, not a lucky attempt.
          </p>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-forge-400">
          <input
            type="checkbox"
            checked={includeResolved}
            onChange={(e) => setIncludeResolved(e.target.checked)}
            className="accent-accent"
          />
          Show resolved
        </label>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Stat label="Open patterns" value={open.length} accent={open.length ? '#f43f5e' : '#34d399'} />
        <Stat label="Critical" value={critical} accent={critical ? '#f43f5e' : undefined} />
        <Stat label="Resolved" value={resolved.length} accent="#34d399" />
      </div>

      {open.length === 0 ? (
        <Card>
          <EmptyState
            icon={<CheckCircle2 className="h-8 w-8 text-signal-success" />}
            title="No open mistake patterns"
            description="Nothing detected in your recent submissions. Take on a harder tier — the detector only fires on code that is doing something interesting."
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {open
            .slice()
            .sort((a, b) => b.occurrences - a.occurrences)
            .map((mistake) => (
              <Card
                key={mistake.pattern}
                className={cn(
                  'border',
                  mistake.severity === 'critical'
                    ? 'border-signal-danger/40'
                    : mistake.severity === 'high'
                      ? 'border-signal-decay/40'
                      : 'border-forge-700',
                )}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Bug className="h-4 w-4 shrink-0 text-signal-danger" />
                  <h3 className="font-display text-base font-semibold text-forge-100">
                    {mistake.title}
                  </h3>
                  <SeverityChip severity={mistake.severity} />
                  <span className="font-mono text-xs text-forge-500">×{mistake.occurrences}</span>
                  {mistake.category && (
                    <Chip className="normal-case tracking-normal">{titleCase(mistake.category)}</Chip>
                  )}
                  <span className="ml-auto flex items-center gap-1 text-[11px] text-forge-500">
                    <Clock className="h-3 w-3" />
                    {relativeTime(mistake.last_seen_at)}
                  </span>
                </div>

                <p className="mt-2 text-sm leading-relaxed text-forge-300">{mistake.description}</p>

                <div className="mt-3 rounded-lg border border-forge-700 bg-forge-950/50 p-3">
                  <div className="stat-label mb-1">Why it matters</div>
                  <p className="text-sm leading-relaxed text-forge-300">{mistake.why_it_matters}</p>
                </div>

                <div className="mt-2 rounded-lg border border-signal-success/25 bg-signal-success/5 p-3">
                  <div className="stat-label mb-1 text-signal-success">The correct approach</div>
                  <p className="text-sm leading-relaxed text-forge-300">{mistake.correct_approach}</p>
                </div>

                <div className="mt-3 flex items-center gap-3">
                  <div className="flex-1">
                    <div className="mb-1 flex items-baseline justify-between text-[11px] text-forge-500">
                      <span>Clean streak</span>
                      <span className="font-mono">
                        {mistake.clean_streak}/{CLEAN_STREAK_TARGET}
                      </span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-forge-800">
                      <div
                        className="h-full rounded-full bg-signal-success transition-all"
                        style={{
                          width: `${Math.min(100, (mistake.clean_streak / CLEAN_STREAK_TARGET) * 100)}%`,
                        }}
                      />
                    </div>
                  </div>
                  {mistake.concept_slug && (
                    <Link
                      to={`/app/concepts/${mistake.concept_slug}`}
                      className="link shrink-0 text-xs"
                    >
                      Read the concept →
                    </Link>
                  )}
                </div>
              </Card>
            ))}
        </div>
      )}

      {includeResolved && resolved.length > 0 && (
        <Card title="Resolved" subtitle="Patterns you have stopped repeating">
          <ul className="space-y-2">
            {resolved.map((mistake) => (
              <li
                key={mistake.pattern}
                className="flex items-center gap-2.5 rounded-lg border border-signal-success/20 bg-signal-success/5 px-3 py-2"
              >
                <CheckCircle2 className="h-4 w-4 shrink-0 text-signal-success" />
                <span className="truncate text-sm text-forge-300">{mistake.title}</span>
                <span className="ml-auto shrink-0 font-mono text-[11px] text-forge-500">
                  hit {mistake.occurrences}×
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
