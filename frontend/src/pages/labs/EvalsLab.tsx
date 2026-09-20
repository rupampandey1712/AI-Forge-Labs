/**
 * The Evaluation Lab — the discipline that separates a demo from a system.
 *
 * THE PROBLEM IT TEACHES: you change a RAG configuration, try three questions
 * by hand, they look better, you ship. Two weeks later something else is worse
 * and nobody can say when it broke. Vibes do not compose, and they do not
 * regression-test.
 *
 * So this page does three things, in order:
 *
 *   1. **Shows you the golden set** before you run anything. A golden set you
 *      cannot read and disagree with is not something you should be gating
 *      deploys on, so it is rendered in full, including the deliberately
 *      unanswerable case that checks the system refuses rather than invents.
 *   2. **Runs two configurations side by side.** A single evaluation produces a
 *      number with nothing to compare it to, which is how a 0.62 gets called
 *      "pretty good".
 *   3. **Returns a verdict with reasons attached.** ship / hold / rollback, and
 *      *why* — because the judgement is the deliverable, not the metric.
 *
 * The per-case breakdown matters as much as the aggregate: a mean of 0.8 hides
 * the difference between "uniformly decent" and "excellent except it confidently
 * fabricates an answer to the one question it should refuse".
 */

import { useState } from 'react';
import { motion } from 'framer-motion';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  AlertOctagon,
  CheckCircle2,
  FlaskConical,
  PauseCircle,
  Play,
  ShieldCheck,
  Swords,
} from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { api } from '@/lib/api';
import { Button, Card, Chip, EmptyState } from '@/components/ui';
import { Insight, Readout, Slider, Toggle } from '@/components/labs/controls';
import { fadeUp, pageTransition, quick, spring, stagger } from '@/lib/motion';
import { cn } from '@/lib/utils';
import type { EvalRunResponse, RAGConfig } from '@/types/labs';

/** The four metrics that decide whether a retrieval change is safe to ship. */
const HEADLINE = ['faithfulness', 'precision_at_k', 'recall_at_k', 'answer_relevance'] as const;

const METRIC_HELP: Record<string, string> = {
  faithfulness:
    'How much of the answer is actually supported by retrieved context. This is the hallucination metric, and it is the one with a hard floor — an unfaithful answer is worse than no answer.',
  precision_at_k: 'Of what you retrieved, how much was relevant. Falls as k rises.',
  recall_at_k: 'Of what was relevant, how much you retrieved. Rises as k rises.',
  answer_relevance: 'Whether the answer addresses the question that was actually asked.',
  context_relevance: 'Whether the retrieved context was on-topic at all.',
  groundedness: 'Whether claims trace back to a source.',
  mrr: 'How high the first relevant result landed.',
  ndcg_at_k: 'Ranking quality — rewards putting the best chunk first, not merely including it.',
};

const PRESETS: { name: string; config: RAGConfig; note: string }[] = [
  { name: 'Baseline k=1', config: { top_k: 1 }, note: 'Retrieve one chunk. High precision, and it misses anything that needs two.' },
  { name: 'Wide k=8', config: { top_k: 8 }, note: 'Retrieve broadly. Recall climbs, precision falls, context bloats.' },
  {
    name: 'Tuned',
    config: { top_k: 5, use_hybrid: true, use_reranker: true },
    note: 'Hybrid retrieval with reranking — the configuration you would actually ship.',
  },
];

export default function EvalsLab() {
  const { data: golden } = useQuery({ queryKey: ['labs', 'golden'], queryFn: api.labs.goldenSet });

  const [config, setConfig] = useState<RAGConfig>({ top_k: 4, use_hybrid: false, use_reranker: false });
  const [useJudge, setUseJudge] = useState(false);
  const [runs, setRuns] = useState<EvalRunResponse[]>([]);
  const [baselineId, setBaselineId] = useState<string | null>(null);

  const evaluate = useMutation({
    mutationFn: (name: string) =>
      api.labs.runEval({
        name,
        config,
        use_golden_set: true,
        use_llm_judge: useJudge,
        baseline_evaluation_id: baselineId,
      }),
    // Newest first, capped: an unbounded list turns the comparison into a wall.
    onSuccess: (data) => setRuns((previous) => [data, ...previous].slice(0, 6)),
  });

  const latest = runs[0];
  const compareTo = runs.find((run) => run.evaluation_id === baselineId);

  return (
    <motion.div
      variants={pageTransition}
      initial="hidden"
      animate="show"
      className="mx-auto max-w-7xl space-y-5"
    >
      <header>
        <div className="flex items-center gap-2.5">
          <ShieldCheck className="h-6 w-6 text-signal-warn" />
          <h1 className="font-display text-2xl font-semibold tracking-tight">Evaluation Lab</h1>
        </div>
        <p className="mt-1.5 max-w-3xl text-sm text-forge-400">
          "I tried three questions and it looked better" is how a regression ships. Run a fixed set
          against two configurations, compare them, and get a verdict with its reasoning attached —
          because the judgement is the deliverable, not the metric.
        </p>
      </header>

      <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
        <div className="space-y-4">
          <Card title="Configuration under test">
            <div className="space-y-4">
              <div className="space-y-1.5">
                {PRESETS.map((preset) => (
                  <button
                    key={preset.name}
                    type="button"
                    onClick={() => setConfig(preset.config)}
                    title={preset.note}
                    className={cn(
                      'block w-full rounded-lg border px-2.5 py-1.5 text-left text-[11px] transition-colors',
                      JSON.stringify(preset.config) === JSON.stringify(config)
                        ? 'border-accent/50 bg-accent/10 text-accent'
                        : 'border-forge-700/70 text-forge-400 hover:text-forge-200',
                    )}
                  >
                    <span className="font-medium">{preset.name}</span>
                    <span className="mt-0.5 block text-[10px] leading-snug text-forge-500">
                      {preset.note}
                    </span>
                  </button>
                ))}
              </div>

              <Slider
                label="top_k"
                value={config.top_k ?? 4}
                min={1}
                max={12}
                onChange={(value) => setConfig((c) => ({ ...c, top_k: value }))}
              />
              <Toggle
                label="Hybrid search"
                checked={config.use_hybrid ?? false}
                onChange={(value) => setConfig((c) => ({ ...c, use_hybrid: value }))}
              />
              <Toggle
                label="Reranker"
                checked={config.use_reranker ?? false}
                onChange={(value) => setConfig((c) => ({ ...c, use_reranker: value }))}
              />
              <Toggle
                label="LLM-as-judge"
                checked={useJudge}
                onChange={setUseJudge}
                hint="Adds a second opinion from the model itself. Slower, and it inherits the model's blind spots — which is exactly why the deterministic metrics stay in the verdict."
              />

              {runs.length > 0 && (
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-forge-200">
                    Compare against
                  </label>
                  <select
                    value={baselineId ?? ''}
                    onChange={(e) => setBaselineId(e.target.value || null)}
                    className="w-full rounded-lg border border-forge-700 bg-forge-900/70 px-3 py-2 text-xs text-forge-100 outline-none focus:border-accent"
                  >
                    <option value="">No baseline</option>
                    {runs.map((run) => (
                      <option key={run.evaluation_id ?? run.name} value={run.evaluation_id ?? ''}>
                        {run.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <Button
                variant="primary"
                className="w-full"
                loading={evaluate.isPending}
                icon={<Play className="h-4 w-4" />}
                onClick={() =>
                  evaluate.mutate(
                    `k=${config.top_k}${config.use_hybrid ? ' hybrid' : ''}${config.use_reranker ? ' rerank' : ''}`,
                  )
                }
              >
                Run evaluation
              </Button>
            </div>
          </Card>

          <Card title="Golden set" subtitle={`${golden?.length ?? 0} cases — read them before trusting them`}>
            <ul className="space-y-2">
              {golden?.map((testCase) => (
                <li key={testCase.question} className="text-[11px] leading-snug">
                  <span
                    className={cn(
                      'block',
                      testCase.relevant.length === 0 ? 'text-signal-warn' : 'text-forge-300',
                    )}
                  >
                    {testCase.relevant.length === 0 && '⚠ '}
                    {testCase.question}
                  </span>
                  <span className="mt-0.5 block text-forge-500">→ {testCase.expected}</span>
                </li>
              ))}
            </ul>
            <Insight tone="warn">
              The ⚠ case has no answer in the corpus. Its correct behaviour is a refusal. A system
              that scores well on the other four and invents an answer to this one is more dangerous
              than a system that scores worse across the board.
            </Insight>
          </Card>
        </div>

        <div className="space-y-4">
          {!latest ? (
            <Card>
              <EmptyState
                icon={<FlaskConical className="h-8 w-8" />}
                title="Run an evaluation"
                description="Then change the configuration and run it again. One evaluation is a number with nothing to compare it to."
              />
            </Card>
          ) : (
            <>
              <VerdictCard run={latest} />
              <MetricComparison latest={latest} baseline={compareTo} />
              {runs.length > 1 && <RunComparison runs={runs} />}
              <PerCaseTable run={latest} />
            </>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function VerdictCard({ run }: { run: EvalRunResponse }) {
  const config = {
    ship: { icon: CheckCircle2, color: '#34d399', label: 'Ship it' },
    hold: { icon: PauseCircle, color: '#fbbf24', label: 'Hold' },
    rollback: { icon: AlertOctagon, color: '#f43f5e', label: 'Roll back' },
  }[run.verdict] ?? { icon: PauseCircle, color: '#fbbf24', label: run.verdict };
  const Icon = config.icon;

  return (
    <motion.div
      key={run.evaluation_id ?? run.name}
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={spring}
    >
      <Card accent={config.color}>
        <div className="flex items-start gap-4">
          <motion.span
            initial={{ scale: 0.4, rotate: -12 }}
            animate={{ scale: 1, rotate: 0 }}
            transition={{ ...spring, delay: 0.08 }}
            className="grid h-12 w-12 shrink-0 place-items-center rounded-xl border"
            style={{
              borderColor: `${config.color}55`,
              backgroundColor: `${config.color}18`,
              color: config.color,
            }}
          >
            <Icon className="h-6 w-6" />
          </motion.span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-2">
              <h2 className="font-display text-xl font-semibold" style={{ color: config.color }}>
                {config.label}
              </h2>
              <span className="font-mono text-sm text-forge-400">{run.name}</span>
              <Chip className="font-mono">
                {run.cases_passed}/{run.cases_total} passed
              </Chip>
              {run.judged_by !== 'deterministic' && <Chip>judged by {run.judged_by}</Chip>}
            </div>
            <ul className="mt-2.5 space-y-1.5">
              {run.reasons.map((reason, index) => (
                <motion.li
                  key={reason}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.12 + index * 0.06, ...quick }}
                  className="text-xs leading-relaxed text-forge-300"
                >
                  • {reason}
                </motion.li>
              ))}
            </ul>
          </div>
        </div>
      </Card>
    </motion.div>
  );
}

function MetricComparison({
  latest,
  baseline,
}: {
  latest: EvalRunResponse;
  baseline?: EvalRunResponse;
}) {
  const radar = Object.entries(latest.metrics)
    .filter(([key]) => METRIC_HELP[key])
    .map(([key, value]) => ({
      metric: key.replace(/_at_k$/, '@k').replace(/_/g, ' '),
      current: Number((value * 100).toFixed(1)),
      baseline: baseline ? Number(((baseline.metrics[key] ?? 0) * 100).toFixed(1)) : undefined,
    }));

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Headline metrics" subtitle={baseline ? `vs ${baseline.name}` : 'No baseline selected'}>
        <motion.div
          variants={stagger(0.05)}
          initial="hidden"
          animate="show"
          className="grid grid-cols-2 gap-3"
        >
          {HEADLINE.filter((key) => latest.metrics[key] !== undefined).map((key) => (
            <motion.div key={key} variants={fadeUp}>
              <Readout
                label={key.replace(/_at_k$/, '@k').replace(/_/g, ' ')}
                value={latest.metrics[key].toFixed(3)}
                delta={baseline ? latest.metrics[key] - (baseline.metrics[key] ?? 0) : undefined}
                hint={METRIC_HELP[key]}
              />
            </motion.div>
          ))}
        </motion.div>
      </Card>

      <Card title="Metric profile" subtitle="Shape matters more than area — a spike beside a trough is a specific failure">
        <ResponsiveContainer width="100%" height={240}>
          <RadarChart data={radar}>
            <PolarGrid stroke="#273154" />
            <PolarAngleAxis dataKey="metric" tick={{ fill: '#8b99c4', fontSize: 10 }} />
            <PolarRadiusAxis domain={[0, 100]} tick={{ fill: '#3a4670', fontSize: 9 }} />
            {baseline && (
              <Radar name={baseline.name} dataKey="baseline" stroke="#5b6a99" fill="#5b6a99" fillOpacity={0.18} />
            )}
            <Radar name={latest.name} dataKey="current" stroke="#22d3ee" fill="#22d3ee" fillOpacity={0.32} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <ReTooltip
              contentStyle={{
                background: '#0b1020',
                border: '1px solid #273154',
                borderRadius: 8,
                fontSize: 11,
              }}
            />
          </RadarChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );
}

function RunComparison({ runs }: { runs: EvalRunResponse[] }) {
  const data = [...runs].reverse().map((run) => ({
    name: run.name,
    faithfulness: Number(((run.metrics.faithfulness ?? 0) * 100).toFixed(1)),
    'precision@k': Number(((run.metrics.precision_at_k ?? 0) * 100).toFixed(1)),
    'recall@k': Number(((run.metrics.recall_at_k ?? 0) * 100).toFixed(1)),
    verdict: run.verdict,
  }));

  return (
    <Card
      title="Every run this session"
      subtitle="This is the picture a single evaluation cannot give you"
      actions={<Swords className="h-4 w-4 text-forge-500" />}
    >
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ left: -18, right: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1c2544" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: '#8b99c4', fontSize: 10 }} />
          <YAxis domain={[0, 100]} tick={{ fill: '#5b6a99', fontSize: 10 }} />
          <ReTooltip
            cursor={{ fill: '#141b33' }}
            contentStyle={{
              background: '#0b1020',
              border: '1px solid #273154',
              borderRadius: 8,
              fontSize: 11,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="faithfulness" radius={[3, 3, 0, 0]}>
            {data.map((entry, index) => (
              <Cell
                key={index}
                fill={entry.verdict === 'rollback' ? '#f43f5e' : entry.verdict === 'ship' ? '#34d399' : '#fbbf24'}
              />
            ))}
          </Bar>
          <Bar dataKey="precision@k" fill="#22d3ee" radius={[3, 3, 0, 0]} />
          <Bar dataKey="recall@k" fill="#a78bfa" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </Card>
  );
}

function PerCaseTable({ run }: { run: EvalRunResponse }) {
  return (
    <Card
      title="Per case"
      subtitle="A mean of 0.8 hides the difference between uniformly decent and one catastrophic fabrication"
      padded={false}
    >
      <div className="divide-y divide-forge-800/70">
        {run.per_case.map((result, index) => (
          <motion.div
            key={result.question}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.05, ...quick }}
            className="px-4 py-3"
          >
            <div className="flex items-start gap-3">
              <span
                className={cn(
                  'mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-bold',
                  result.passed
                    ? 'bg-signal-success/20 text-signal-success'
                    : 'bg-signal-danger/20 text-signal-danger',
                )}
              >
                {result.passed ? '✓' : '✕'}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-forge-200">{result.question}</p>
                <p className="mt-1 text-[11px] leading-relaxed text-forge-400">{result.answer}</p>

                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                  {Object.entries(result.metrics)
                    .filter(([key]) => METRIC_HELP[key])
                    .map(([key, value]) => (
                      <span
                        key={key}
                        title={METRIC_HELP[key]}
                        className="font-mono text-[10px] text-forge-500"
                      >
                        {key.replace(/_at_k$/, '@k')}={' '}
                        <span
                          className={cn(
                            'tabular-nums',
                            value >= 0.8
                              ? 'text-signal-success'
                              : value >= 0.5
                                ? 'text-signal-warn'
                                : 'text-signal-danger',
                          )}
                        >
                          {value.toFixed(2)}
                        </span>
                      </span>
                    ))}
                </div>

                {result.retrieved_titles.length > 0 && (
                  <p className="mt-1.5 truncate font-mono text-[10px] text-forge-600">
                    retrieved: {result.retrieved_titles.join(' · ')}
                  </p>
                )}

                {result.unsupported_claims.length > 0 && (
                  <div className="mt-2 rounded-lg border border-signal-danger/30 bg-signal-danger/[0.06] px-2.5 py-1.5">
                    <div className="text-[10px] uppercase tracking-wide text-signal-danger">
                      Claims with no support in the retrieved context
                    </div>
                    <ul className="mt-1 space-y-0.5">
                      {result.unsupported_claims.map((claim) => (
                        <li key={claim} className="text-[11px] leading-snug text-forge-300">
                          • {claim}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </Card>
  );
}
