/**
 * The Knowledge Retention Dashboard — the screen that justifies the product.
 *
 * The centrepiece is the forecast chart: two lines, one showing what happens if
 * you keep practising and one showing what happens if you do not. An abstract
 * forgetting curve convinces nobody; *your* forgetting curve, with your
 * concepts on it, is the most persuasive thing the app can show.
 *
 * Everything else on the page answers one question: what should I review, and
 * why that rather than something else?
 */

import { AlertTriangle, Clock, TrendingDown, TrendingUp } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { api } from '@/lib/api';
import { Card, Chip, EmptyState, LoadingPanel, Stat } from '@/components/ui';
import { Gauge, MasteryBar } from '@/components/game/bits';
import { cn, pct, titleCase } from '@/lib/utils';
import type { ConceptDecay } from '@/types/api';

export default function Retention() {
  const { data, isLoading } = useQuery({ queryKey: ['retention'], queryFn: api.retention.dashboard });

  if (isLoading || !data) return <LoadingPanel rows={10} className="mx-auto max-w-6xl" />;

  if (data.concepts_tracked === 0) {
    return (
      <div className="mx-auto max-w-2xl">
        <Card>
          <EmptyState
            icon={<Clock className="h-8 w-8" />}
            title="Nothing to forget yet"
            description="Complete a few challenges and the retention engine will start modelling what you are losing — and when to bring it back."
          />
        </Card>
      </div>
    );
  }

  // The "keep practising" line is a flat reference at the target retention the
  // scheduler is designed to hold. Showing it next to the decay line is what
  // makes the gap legible.
  const forecast = data.forecast.map((point) => ({
    day: point.day,
    'If you stop': Math.round(point.retention * 100),
    'If you keep reviewing': 90,
    mastery: Math.round(point.effective_mastery * 100),
  }));

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">Knowledge Retention</h1>
        <p className="mt-1 text-sm text-forge-400">
          Every concept you have practised, modelled against a forgetting curve. This is what stops
          the game from being a course you finish and forget.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat
          label="Overall recall"
          value={pct(data.overall_retention)}
          hint="Mean P(recall) right now"
          accent="#22d3ee"
        />
        <Stat label="Concepts tracked" value={data.concepts_tracked} hint="With at least one attempt" />
        <Stat
          label="Due now"
          value={data.concepts_due}
          hint="Below the 90% recall target"
          accent={data.concepts_due ? '#fbbf24' : '#34d399'}
        />
        <Stat
          label="Decayed"
          value={data.concepts_decayed}
          hint={`${data.concepts_critical} critical`}
          accent={data.concepts_decayed ? '#fb923c' : '#34d399'}
        />
      </div>

      {data.alerts.length > 0 && (
        <div className="space-y-2.5">
          {data.alerts.map((alert) => (
            <div
              key={alert.slug}
              className={cn(
                'panel border p-4',
                alert.severity === 'critical'
                  ? 'border-signal-danger/50 bg-signal-danger/8'
                  : 'border-signal-decay/50 bg-signal-decay/8',
              )}
            >
              <div className="flex items-start gap-3">
                <AlertTriangle
                  className={cn(
                    'mt-0.5 h-5 w-5 shrink-0',
                    alert.severity === 'critical' ? 'text-signal-danger' : 'text-signal-decay',
                  )}
                />
                <div className="min-w-0 flex-1">
                  <h3 className="font-display text-sm font-semibold tracking-wide">{alert.headline}</h3>
                  <p className="mt-1 text-sm leading-relaxed text-forge-300">{alert.detail}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {alert.concept_slugs.map((slug) => (
                      <Link
                        key={slug}
                        to={`/app/concepts/${slug}`}
                        className="chip border-forge-600 bg-forge-800 text-forge-300 hover:border-accent hover:text-accent"
                      >
                        {slug}
                      </Link>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── The forecast ────────────────────────────────────────────────── */}
      <Card
        title="90-day forecast"
        subtitle="What happens to your recall if you stop practising today"
        padded={false}
      >
        <div className="h-72 p-4">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={forecast} margin={{ top: 8, right: 12, bottom: 4, left: -18 }}>
              <defs>
                <linearGradient id="decayFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#fb923c" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#fb923c" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#1c2544" strokeDasharray="3 3" />
              <XAxis
                dataKey="day"
                tick={{ fill: '#5b6a99', fontSize: 11 }}
                tickFormatter={(v) => `${v}d`}
                stroke="#273154"
              />
              <YAxis
                domain={[0, 100]}
                tick={{ fill: '#5b6a99', fontSize: 11 }}
                tickFormatter={(v) => `${v}%`}
                stroke="#273154"
              />
              <ReTooltip
                contentStyle={{
                  background: '#0f152a',
                  border: '1px solid #273154',
                  borderRadius: 8,
                  fontSize: 12,
                }}
                labelFormatter={(v) => `Day ${v}`}
                formatter={(value: number, name: string) => [`${value}%`, name]}
              />
              <Legend wrapperStyle={{ fontSize: 11, color: '#8b99c4' }} />
              <Area
                type="monotone"
                dataKey="If you stop"
                stroke="#fb923c"
                strokeWidth={2}
                fill="url(#decayFill)"
              />
              <Line
                type="monotone"
                dataKey="If you keep reviewing"
                stroke="#34d399"
                strokeWidth={2}
                strokeDasharray="5 4"
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <p className="border-t border-forge-700 px-4 py-2.5 text-xs leading-relaxed text-forge-500">
          The scheduler aims to catch each concept at ~90% recall — late enough that the review is
          effortful (which is what makes it stick), early enough that you have not lost it. The
          orange curve is what the absence of that looks like.
        </p>
      </Card>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="Due now" subtitle="Sorted by urgency, not by date" className="lg:col-span-2">
          {data.due_now.length === 0 ? (
            <p className="text-sm text-forge-500">Nothing is due. Everything is holding above target.</p>
          ) : (
            <ul className="space-y-2">
              {data.due_now.map((concept) => (
                <ConceptRow key={concept.concept_slug} concept={concept} />
              ))}
            </ul>
          )}
        </Card>

        <div className="space-y-5">
          <Card title="Retention by skill">
            <div className="space-y-3">
              {data.by_skill.map((skill) => (
                <div key={skill.skill_slug}>
                  <MasteryBar
                    label={skill.name}
                    mastery={skill.mastery}
                    effective={skill.effective_mastery}
                  />
                  {skill.due > 0 && (
                    <div className="mt-0.5 text-[11px] text-signal-warn">
                      {skill.due} due · {skill.decayed} decayed
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>

          <Card title="Calibration" subtitle="Overall recall vs. target">
            <div className="flex justify-around">
              <Gauge value={data.overall_retention} label="Recall now" />
              <Gauge
                value={data.concepts_tracked ? 1 - data.concepts_decayed / data.concepts_tracked : 1}
                label="Holding steady"
                color="#34d399"
              />
            </div>
          </Card>
        </div>
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <Card
          title="Recently forgotten"
          subtitle="Biggest drop from peak"
          actions={<TrendingDown className="h-4 w-4 text-signal-decay" />}
        >
          {data.recently_forgotten.length === 0 ? (
            <p className="text-sm text-forge-500">Nothing has slipped meaningfully.</p>
          ) : (
            <ul className="space-y-2">
              {data.recently_forgotten.map((concept) => (
                <ConceptRow key={concept.concept_slug} concept={concept} compact />
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="Strongest"
          subtitle="Holding well — these will come back rarely"
          actions={<TrendingUp className="h-4 w-4 text-signal-success" />}
        >
          <ul className="space-y-2">
            {data.strongest.map((concept) => (
              <ConceptRow key={concept.concept_slug} concept={concept} compact />
            ))}
          </ul>
        </Card>
      </div>

      {data.upcoming.length > 0 && (
        <Card title="Coming up" subtitle="Scheduled reviews, in order">
          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {data.upcoming.map((concept) => (
              <li
                key={concept.concept_slug}
                className="rounded-lg border border-forge-700 bg-forge-900/50 px-3 py-2"
              >
                <Link to={`/app/concepts/${concept.concept_slug}`} className="block truncate text-sm text-forge-200 hover:text-accent">
                  {concept.title}
                </Link>
                <div className="mt-0.5 flex items-center justify-between text-[11px] text-forge-500">
                  <span>{titleCase(concept.skill_slug)}</span>
                  <span className="font-mono">
                    {concept.due_at ? new Date(concept.due_at).toLocaleDateString() : '—'}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function ConceptRow({ concept, compact = false }: { concept: ConceptDecay; compact?: boolean }) {
  const urgencyTone =
    concept.urgency > 0.7
      ? 'border-signal-danger/40 bg-signal-danger/5'
      : concept.urgency > 0.4
        ? 'border-signal-decay/30 bg-signal-decay/5'
        : 'border-forge-700 bg-forge-900/50';

  return (
    <li className={cn('rounded-lg border px-3 py-2.5', urgencyTone)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <Link
            to={`/app/concepts/${concept.concept_slug}`}
            className="block truncate text-sm font-medium text-forge-100 hover:text-accent"
          >
            {concept.title}
          </Link>
          {!compact && (
            <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-forge-500">
              <Chip className="normal-case">{titleCase(concept.skill_slug)}</Chip>
              <span>
                {concept.days_since_practice < 0
                  ? 'never practised'
                  : `${concept.days_since_practice.toFixed(0)}d since practice`}
              </span>
              {concept.lapses > 0 && (
                <span className="text-signal-danger">{concept.lapses} lapse{concept.lapses === 1 ? '' : 's'}</span>
              )}
            </div>
          )}
        </div>
        <div className="shrink-0 text-right font-mono text-xs">
          <div className="text-forge-500">
            {pct(concept.peak_mastery)}
            <span className="mx-1 text-forge-600">→</span>
            <span
              className={
                concept.effective_mastery < concept.peak_mastery * 0.75
                  ? 'text-signal-decay'
                  : 'text-signal-success'
              }
            >
              {pct(concept.effective_mastery)}
            </span>
          </div>
          <div className="mt-0.5 text-[10px] text-forge-600">
            recall {pct(concept.retrievability)}
          </div>
        </div>
      </div>
      {!compact && (
        <MasteryBar
          className="mt-2"
          mastery={concept.peak_mastery}
          effective={concept.effective_mastery}
        />
      )}
    </li>
  );
}
