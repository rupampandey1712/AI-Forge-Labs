/**
 * Analytics.
 *
 * Rule applied throughout: never show a composite score without its components.
 * "Interview readiness 62%" is a number; "62% — held back by production
 * awareness at 31%, which carries 10% of the weight" is feedback. Every gauge
 * on this page is clickable through to what produced it.
 */

import { TrendingDown, TrendingUp } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { api } from '@/lib/api';
import { Card, LoadingPanel, Stat, Tabs, Tab, TabList, TabPanel } from '@/components/ui';
import { Gauge, MasteryBar } from '@/components/game/bits';
import { masteryColor, pct, TIER_LABELS, titleCase } from '@/lib/utils';

const CHART_TOOLTIP = {
  background: '#0f152a',
  border: '1px solid #273154',
  borderRadius: 8,
  fontSize: 12,
};

export default function Analytics() {
  const analytics = useQuery({ queryKey: ['analytics'], queryFn: api.analytics.progress });
  const readiness = useQuery({ queryKey: ['readiness'], queryFn: api.analytics.readiness });

  if (analytics.isLoading || !analytics.data) {
    return <LoadingPanel rows={10} className="mx-auto max-w-6xl" />;
  }

  const data = analytics.data;

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">Analytics</h1>
        <p className="mt-1 text-sm text-forge-400">
          {titleCase(data.rank)} · level {data.level} · simulating the problems a{' '}
          {data.experience_band}-year engineer is expected to solve
        </p>
      </div>

      {/* ── Composite gauges ────────────────────────────────────────────── */}
      <Card title="Where you stand" subtitle="Each of these is a weighted blend — see the breakdown below">
        <div className="flex flex-wrap justify-around gap-4">
          <Gauge value={data.interview_readiness} label="Interview readiness" />
          <Gauge value={data.debugging_score} label="Debugging" color="#f43f5e" />
          <Gauge value={data.architecture_score} label="Architecture" color="#94a3b8" />
          <Gauge value={data.production_score} label="Production" color="#fbbf24" />
          <Gauge value={data.coding_speed_index} label="Coding pace" color="#a78bfa" />
          <Gauge value={data.consistency_score} label="Consistency" color="#34d399" />
        </div>
      </Card>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Total XP" value={data.total_xp.toLocaleString()} accent="#a78bfa" />
        <Stat label="Practice (7d)" value={`${data.practice_minutes_7d}m`} />
        <Stat label="Practice (30d)" value={`${data.practice_minutes_30d}m`} />
        <Stat
          label="Decayed concepts"
          value={data.recently_forgotten.length}
          accent={data.recently_forgotten.length ? '#fb923c' : '#34d399'}
        />
      </div>

      {/* ── Readiness breakdown ─────────────────────────────────────────── */}
      {readiness.data && (
        <Card
          title="Interview readiness, decomposed"
          subtitle="The number is only useful with the components that made it"
        >
          <div className="grid gap-5 lg:grid-cols-[1fr_1.4fr]">
            <div>
              <div className="stat-label mb-2">By target level</div>
              <div className="space-y-2">
                {Object.entries(readiness.data.by_level).map(([level, value]) => (
                  <div key={level} className="flex items-center gap-3">
                    <span className="w-20 shrink-0 text-xs capitalize text-forge-400">{level}</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-forge-800">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${value * 100}%`,
                          backgroundColor: masteryColor(value),
                        }}
                      />
                    </div>
                    <span className="w-9 shrink-0 text-right font-mono text-xs tabular-nums text-forge-400">
                      {Math.round(value * 100)}%
                    </span>
                  </div>
                ))}
              </div>

              <div className="stat-label mb-2 mt-5">Largest available gains</div>
              <ul className="space-y-1.5">
                {readiness.data.next_actions.map((action) => (
                  <li key={action.slug} className="rounded-lg border border-forge-700 bg-forge-900/50 p-2.5">
                    <div className="text-sm font-medium text-forge-100">{action.title}</div>
                    <p className="mt-0.5 text-xs leading-relaxed text-forge-500">{action.reason}</p>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <div className="stat-label mb-2">Contribution by component</div>
              <ul className="space-y-1.5">
                {readiness.data.components.map((component) => (
                  <li key={component.slug} className="flex items-center gap-2 text-xs">
                    <span className="w-28 shrink-0 truncate text-forge-400">{component.name}</span>
                    <div className="flex h-2.5 flex-1 overflow-hidden rounded-full bg-forge-800">
                      <div
                        className="h-full bg-accent"
                        style={{ width: `${(component.contribution / 0.2) * 100}%` }}
                        title={`contributing ${(component.contribution * 100).toFixed(1)} pts`}
                      />
                      <div
                        className="h-full bg-forge-600/60"
                        style={{ width: `${(component.headroom / 0.2) * 100}%` }}
                        title={`headroom ${(component.headroom * 100).toFixed(1)} pts`}
                      />
                    </div>
                    <span className="w-16 shrink-0 text-right font-mono tabular-nums text-forge-500">
                      {Math.round(component.value * 100)}% · w{Math.round(component.weight * 100)}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-[11px] leading-relaxed text-forge-600">
                Cyan is what the component currently contributes; grey is the headroom it still
                holds. The longest grey bar is where an hour of work buys the most.
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* ── Trends ──────────────────────────────────────────────────────── */}
      <Tabs defaultValue="xp">
        <TabList>
          <Tab value="xp">XP over time</Tab>
          <Tab value="activity">Activity</Tab>
          <Tab value="accuracy">Accuracy</Tab>
          <Tab value="tiers">Depth</Tab>
          <Tab value="sources">XP sources</Tab>
        </TabList>

        <TabPanel value="xp">
          <Card padded={false}>
            <div className="h-64 p-4">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.xp_over_time} margin={{ top: 8, right: 12, bottom: 4, left: -20 }}>
                  <CartesianGrid stroke="#1c2544" strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fill: '#5b6a99', fontSize: 10 }} stroke="#273154" />
                  <YAxis tick={{ fill: '#5b6a99', fontSize: 10 }} stroke="#273154" />
                  <ReTooltip contentStyle={CHART_TOOLTIP} />
                  <Line type="monotone" dataKey="value" stroke="#a78bfa" strokeWidth={2} dot={false} name="XP" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </TabPanel>

        <TabPanel value="activity">
          <Card padded={false}>
            <div className="h-64 p-4">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.activity_over_time} margin={{ top: 8, right: 12, bottom: 4, left: -20 }}>
                  <CartesianGrid stroke="#1c2544" strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fill: '#5b6a99', fontSize: 10 }} stroke="#273154" />
                  <YAxis tick={{ fill: '#5b6a99', fontSize: 10 }} stroke="#273154" />
                  <ReTooltip contentStyle={CHART_TOOLTIP} />
                  <Bar dataKey="value" fill="#22d3ee" radius={[3, 3, 0, 0]} name="Actions" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </TabPanel>

        <TabPanel value="accuracy">
          <Card padded={false}>
            <div className="h-64 p-4">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.accuracy_over_time} margin={{ top: 8, right: 12, bottom: 4, left: -20 }}>
                  <CartesianGrid stroke="#1c2544" strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fill: '#5b6a99', fontSize: 10 }} stroke="#273154" />
                  <YAxis
                    domain={[0, 1]}
                    tickFormatter={(v) => `${Math.round(v * 100)}%`}
                    tick={{ fill: '#5b6a99', fontSize: 10 }}
                    stroke="#273154"
                  />
                  <ReTooltip
                    contentStyle={CHART_TOOLTIP}
                    formatter={(v: number) => `${Math.round(v * 100)}%`}
                  />
                  <Line type="monotone" dataKey="value" stroke="#34d399" strokeWidth={2} dot={false} name="Score" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </TabPanel>

        <TabPanel value="tiers">
          <Card
            subtitle="How deep you actually work. A profile weighted to tiers 1-3 is a profile that will not survive a senior interview."
            padded={false}
          >
            <div className="h-64 p-4">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={data.tier_distribution.map((t) => ({
                    ...t,
                    label: `T${t.tier}`,
                    name: TIER_LABELS[t.tier],
                  }))}
                  margin={{ top: 8, right: 12, bottom: 4, left: -20 }}
                >
                  <CartesianGrid stroke="#1c2544" strokeDasharray="3 3" />
                  <XAxis dataKey="label" tick={{ fill: '#5b6a99', fontSize: 10 }} stroke="#273154" />
                  <YAxis tick={{ fill: '#5b6a99', fontSize: 10 }} stroke="#273154" />
                  <ReTooltip contentStyle={CHART_TOOLTIP} labelFormatter={(_, p) => p?.[0]?.payload?.name ?? ''} />
                  <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                    {data.tier_distribution.map((tier) => (
                      <Cell
                        key={tier.tier}
                        fill={
                          tier.tier <= 2
                            ? '#3a4670'
                            : tier.tier <= 4
                              ? '#22d3ee'
                              : tier.tier <= 6
                                ? '#a78bfa'
                                : tier.tier <= 8
                                  ? '#fbbf24'
                                  : '#f43f5e'
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </TabPanel>

        <TabPanel value="sources">
          <Card subtitle="What the game actually paid you for">
            <ul className="space-y-1.5">
              {data.xp_by_source.map((source) => {
                const max = Math.max(...data.xp_by_source.map((s) => s.amount), 1);
                return (
                  <li key={source.source} className="flex items-center gap-3 text-xs">
                    <span className="w-40 shrink-0 truncate text-forge-400">
                      {titleCase(source.source)}
                    </span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-forge-800">
                      <div
                        className="h-full rounded-full bg-signal-xp"
                        style={{ width: `${(source.amount / max) * 100}%` }}
                      />
                    </div>
                    <span className="w-14 shrink-0 text-right font-mono tabular-nums text-forge-400">
                      {source.amount.toLocaleString()}
                    </span>
                  </li>
                );
              })}
            </ul>
          </Card>
        </TabPanel>
      </Tabs>

      {/* ── Mastery tables ──────────────────────────────────────────────── */}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Strongest" actions={<TrendingUp className="h-4 w-4 text-signal-success" />}>
          <div className="space-y-3">
            {data.strongest_skills.map((skill) => (
              <MasteryBar
                key={skill.slug}
                label={skill.name}
                mastery={skill.mastery}
                effective={skill.effective_mastery}
              />
            ))}
          </div>
        </Card>

        <Card title="Weakest" actions={<TrendingDown className="h-4 w-4 text-signal-warn" />}>
          <div className="space-y-3">
            {data.weakest_skills.map((skill) => (
              <MasteryBar
                key={skill.slug}
                label={skill.name}
                mastery={skill.mastery}
                effective={skill.effective_mastery}
              />
            ))}
          </div>
        </Card>
      </div>

      {data.mastery_by_category.length > 0 && (
        <Card title="Mastery by area">
          <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            {data.mastery_by_category.map((category) => (
              <MasteryBar
                key={category.slug}
                label={`${category.name} (${category.attempts})`}
                mastery={category.mastery}
              />
            ))}
          </div>
        </Card>
      )}

      {data.recently_forgotten.length > 0 && (
        <Card title="Recently forgotten" subtitle="Largest drops from peak mastery">
          <ul className="space-y-1.5">
            {data.recently_forgotten.map((concept) => (
              <li
                key={concept.concept_slug}
                className="flex items-center justify-between gap-3 rounded-lg border border-signal-decay/25 bg-signal-decay/5 px-3 py-2 text-sm"
              >
                <span className="truncate text-forge-200">{concept.concept_slug}</span>
                <span className="shrink-0 font-mono text-xs">
                  <span className="text-forge-500">{pct(concept.from)}</span>
                  <span className="mx-1 text-forge-600">→</span>
                  <span className="text-signal-decay">{pct(concept.to)}</span>
                  <span className="ml-2 text-forge-600">{concept.days.toFixed(0)}d</span>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {data.most_common_mistakes.length > 0 && (
        <Card title="Most repeated mistakes">
          <ul className="space-y-1.5">
            {data.most_common_mistakes.map((mistake) => (
              <li
                key={mistake.pattern}
                className="flex items-center justify-between gap-3 rounded-lg border border-forge-700 bg-forge-900/50 px-3 py-2 text-sm"
              >
                <span className="truncate text-forge-200">{mistake.title}</span>
                <span className="shrink-0 font-mono text-xs text-forge-500">
                  ×{mistake.occurrences}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
