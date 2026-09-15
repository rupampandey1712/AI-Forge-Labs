/**
 * The game dashboard.
 *
 * Information hierarchy, in priority order — this is a deliberate design
 * decision, not a layout accident:
 *
 *   1. Decay alerts. If knowledge is falling, nothing else matters today.
 *   2. Today's mission. The single call to action.
 *   3. Skill radar. Where you stand, at a glance.
 *   4. Recommendations, open mistakes, activity. Context, not demands.
 *
 * A dashboard that leads with a vanity XP number and buries the decay warning
 * would be a prettier product and a worse one.
 */

import { motion } from 'framer-motion';
import {
  AlertTriangle,
  ArrowRight,
  Bug,
  CheckCircle2,
  Clock,
  Flame,
  Swords,
  Target,
  TrendingUp,
  Zap,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from 'recharts';
import { api } from '@/lib/api';
import { Button, Card, EmptyState, LoadingPanel, Stat } from '@/components/ui';
import { KindChip, MasteryBar, StreakCalendar, TierChip } from '@/components/game/bits';
import { cn, compactNumber, duration, pct, relativeTime, titleCase } from '@/lib/utils';
import type { DecayAlert } from '@/types/api';

export default function Dashboard() {
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: api.player.dashboard });
  const daily = useQuery({ queryKey: ['daily'], queryFn: api.daily.get });

  if (dashboard.isLoading) {
    return (
      <div className="mx-auto max-w-6xl space-y-4">
        <LoadingPanel rows={2} />
        <div className="grid gap-4 lg:grid-cols-3">
          <LoadingPanel rows={5} className="lg:col-span-2" />
          <LoadingPanel rows={5} />
        </div>
      </div>
    );
  }

  if (dashboard.isError || !dashboard.data) {
    return (
      <EmptyState
        icon={<AlertTriangle className="h-8 w-8 text-signal-warn" />}
        title="Could not load your dashboard"
        description="The backend may not be running. Check http://localhost:8000/docs."
        action={<Button onClick={() => dashboard.refetch()}>Retry</Button>}
      />
    );
  }

  const { profile, skills, retention_alerts, due_reviews, recommended, open_mistakes, recent_events, streak_calendar } =
    dashboard.data;

  const radarData = skills
    .filter((s) => s.concepts_total > 0 || s.attempts > 0)
    .map((s) => ({
      skill: s.name.length > 12 ? `${s.name.slice(0, 11)}…` : s.name,
      mastery: Math.round(s.mastery * 100),
      effective: Math.round(s.effective_mastery * 100),
    }));

  const practicedSkills = skills.filter((s) => s.attempts > 0);
  const weakest = [...practicedSkills].sort((a, b) => a.effective_mastery - b.effective_mastery).slice(0, 4);

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      {/* ── 1. Decay alerts — the highest-priority information ─────────── */}
      {retention_alerts.length > 0 && (
        <div className="space-y-2.5">
          {retention_alerts.map((alert, i) => (
            <AlertBanner key={alert.slug} alert={alert} index={i} />
          ))}
        </div>
      )}

      {/* ── Headline stats ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat
          label="Level"
          value={profile.level}
          hint={`${compactNumber(profile.xp_into_level)} / ${compactNumber(profile.xp_for_next_level)} XP`}
          accent="#22d3ee"
          icon={<TrendingUp className="h-4 w-4" />}
        />
        <Stat
          label="Rank"
          value={<span className="text-lg">{titleCase(profile.rank)}</span>}
          hint={profile.next_rank ? `Next: ${titleCase(profile.next_rank)} at L${profile.next_rank_level}` : 'Top of the ladder'}
          icon={<Swords className="h-4 w-4" />}
        />
        <Stat
          label="Streak"
          value={profile.current_streak}
          hint={`Best ${profile.longest_streak} days`}
          accent="#fb923c"
          icon={<Flame className="h-4 w-4" />}
        />
        <Stat
          label="Due for review"
          value={due_reviews}
          hint={due_reviews ? 'Concepts fading now' : 'Nothing decaying'}
          accent={due_reviews > 0 ? '#fbbf24' : '#34d399'}
          icon={<Clock className="h-4 w-4" />}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          {/* ── 2. Today's mission ───────────────────────────────────── */}
          <Card
            title="Today's engineering mission"
            subtitle={
              daily.data
                ? `${daily.data.completed_count} of ${daily.data.slots.length} done · ~${daily.data.estimated_minutes} min`
                : 'Generating…'
            }
            actions={
              <Link to="/app/daily">
                <Button size="sm" variant="primary" icon={<ArrowRight className="h-3.5 w-3.5" />}>
                  Open
                </Button>
              </Link>
            }
          >
            {daily.isLoading && <LoadingPanel rows={3} className="border-0 bg-transparent p-0 shadow-none" />}
            {daily.data && (
              <ul className="space-y-2">
                {daily.data.slots.slice(0, 5).map((slot) => (
                  <li
                    key={slot.slot}
                    className={cn(
                      'flex items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors',
                      slot.completed
                        ? 'border-signal-success/25 bg-signal-success/5'
                        : 'border-forge-700 bg-forge-900/60',
                    )}
                  >
                    <div className="mt-0.5 shrink-0">
                      {slot.completed ? (
                        <CheckCircle2 className="h-4 w-4 text-signal-success" />
                      ) : (
                        <span className="flex h-4 w-4 items-center justify-center rounded-full border border-forge-600 text-[10px] font-mono text-forge-500">
                          {slot.slot + 1}
                        </span>
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={cn('truncate text-sm', slot.completed ? 'text-forge-400 line-through' : 'text-forge-100')}>
                          {slot.title}
                        </span>
                        <KindChip kind={slot.kind} />
                        <TierChip tier={slot.tier} />
                      </div>
                      {/* The reason is the whole point: a training plan you
                          understand is one you trust. */}
                      <p className="mt-1 text-xs leading-relaxed text-forge-500">{slot.reason}</p>
                    </div>
                  </li>
                ))}
                {daily.data.slots.length > 5 && (
                  <li className="pl-7 text-xs text-forge-500">
                    +{daily.data.slots.length - 5} more
                  </li>
                )}
              </ul>
            )}
          </Card>

          {/* ── Recommendations ──────────────────────────────────────── */}
          {recommended.length > 0 && (
            <Card title="What to work on next" subtitle="Chosen from your decay curve and weakest skills">
              <ul className="grid gap-2 sm:grid-cols-2">
                {recommended.slice(0, 6).map((rec) => (
                  <li key={`${rec.kind}-${rec.slug}`} className="rounded-lg border border-forge-700 bg-forge-900/50 p-3">
                    <div className="flex items-center gap-2">
                      <Zap className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden />
                      <span className="truncate text-sm font-medium text-forge-100">{rec.title}</span>
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-forge-500">{rec.reason}</p>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {/* ── Open mistakes ────────────────────────────────────────── */}
          {open_mistakes.length > 0 && (
            <Card
              title="Open mistake patterns"
              subtitle="These stay open until you go several submissions without repeating them"
              actions={
                <Link to="/app/mistakes" className="link text-xs">
                  Full log
                </Link>
              }
            >
              <ul className="space-y-2">
                {open_mistakes.map((mistake) => (
                  <li key={mistake.pattern} className="flex items-start gap-3 rounded-lg border border-forge-700 bg-forge-900/50 p-3">
                    <Bug className="mt-0.5 h-4 w-4 shrink-0 text-signal-danger" aria-hidden />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-forge-100">{mistake.title}</span>
                        <span className="font-mono text-[11px] text-forge-500">×{mistake.occurrences}</span>
                      </div>
                      <p className="mt-0.5 text-xs leading-relaxed text-forge-500">{mistake.why_it_matters}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>

        {/* ── Right column ───────────────────────────────────────────── */}
        <div className="space-y-5">
          <Card title="Skill profile" subtitle="Solid = today · ghost = peak" padded={false}>
            <div className="h-64 px-2 pt-3">
              {radarData.length >= 3 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <RadarChart data={radarData} outerRadius="72%">
                    <PolarGrid stroke="#273154" />
                    <PolarAngleAxis dataKey="skill" tick={{ fill: '#8b99c4', fontSize: 9 }} />
                    <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                    <Radar name="Peak" dataKey="mastery" stroke="#3a4670" fill="#3a4670" fillOpacity={0.3} />
                    <Radar name="Today" dataKey="effective" stroke="#22d3ee" fill="#22d3ee" fillOpacity={0.35} />
                  </RadarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyState
                  icon={<Target className="h-7 w-7" />}
                  title="Not enough data yet"
                  description="Complete a few missions and your profile will take shape."
                />
              )}
            </div>
          </Card>

          {weakest.length > 0 && (
            <Card title="Weakest skills" subtitle="Where the next gain is largest">
              <div className="space-y-3">
                {weakest.map((skill) => (
                  <Link key={skill.skill_slug} to={`/app/skills/${skill.skill_slug}`} className="block">
                    <MasteryBar
                      label={skill.name}
                      mastery={skill.mastery}
                      effective={skill.effective_mastery}
                    />
                  </Link>
                ))}
              </div>
            </Card>
          )}

          <Card padded>
            <StreakCalendar days={streak_calendar} streak={profile.current_streak} />
          </Card>

          <Card title="Recent activity">
            {recent_events.length === 0 ? (
              <p className="text-sm text-forge-500">Nothing yet — start with today&rsquo;s mission.</p>
            ) : (
              <ul className="space-y-2">
                {recent_events.slice(0, 8).map((event, i) => (
                  <li key={i} className="flex items-baseline justify-between gap-3 text-xs">
                    <span className="truncate text-forge-300">
                      {titleCase(event.type)}
                      {event.skill_slug && <span className="text-forge-500"> · {event.skill_slug}</span>}
                    </span>
                    <span className="shrink-0 text-forge-600">{relativeTime(event.at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Lifetime">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-sm">
              {[
                ['Missions', profile.missions_completed],
                ['Challenges', profile.challenges_passed],
                ['Questions', profile.questions_answered],
                ['Bosses', profile.bosses_defeated],
                ['Incidents', profile.incidents_resolved],
                ['Practice', duration(profile.total_practice_seconds)],
              ].map(([label, value]) => (
                <div key={String(label)} className="flex items-baseline justify-between gap-2">
                  <dt className="text-forge-500">{label}</dt>
                  <dd className="font-mono tabular-nums text-forge-200">{value}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      </div>
    </div>
  );
}

function AlertBanner({ alert, index }: { alert: DecayAlert; index: number }) {
  const tone =
    alert.severity === 'critical'
      ? 'border-signal-danger/50 bg-signal-danger/10 text-signal-danger'
      : alert.severity === 'warning'
        ? 'border-signal-decay/50 bg-signal-decay/10 text-signal-decay'
        : 'border-signal-warn/40 bg-signal-warn/8 text-signal-warn';

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.08 }}
      className={cn('panel overflow-hidden border', tone)}
    >
      <div className="flex items-start gap-3 p-4">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
        <div className="min-w-0 flex-1">
          <h3 className="font-display text-sm font-semibold tracking-wide">{alert.headline}</h3>
          <p className="mt-1 text-sm leading-relaxed text-forge-300">{alert.detail}</p>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-forge-400">
              {pct(alert.from_mastery)} → {pct(alert.to_mastery)}
            </span>
            <Link to={`/app/skills/${alert.slug}`}>
              <Button size="sm" variant="secondary" icon={<ArrowRight className="h-3.5 w-3.5" />}>
                Repair now
              </Button>
            </Link>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
