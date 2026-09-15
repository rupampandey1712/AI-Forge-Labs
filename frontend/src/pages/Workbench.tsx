/**
 * The coding workbench — Monaco editor, test results, explanation, grading.
 *
 * The screen enforces spec §41: passing tests does not finish the challenge.
 * The Explain panel unlocks only once the tests are green, and it is where the
 * real XP is. That ordering is the pedagogy: solve it, then articulate *why*
 * it works, because the second is what survives.
 *
 * Failure is presented as a postmortem card (§64) — headline, what happened,
 * root cause, next hint — never as the word "Wrong".
 */

import Editor, { type OnMount } from '@monaco-editor/react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  ArrowLeft,
  CheckCircle2,
  Eye,
  Gauge as GaugeIcon,
  Lightbulb,
  Play,
  RotateCcw,
  Send,
  Terminal,
  XCircle,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiRequestError } from '@/lib/api';
import { Button, Card, Chip, LoadingPanel, Modal, Spinner, Tooltip } from '@/components/ui';
import { SeverityChip, TierChip } from '@/components/game/bits';
import { useRewards, useUI } from '@/stores/game';
import { cn, duration, titleCase } from '@/lib/utils';
import type { Grade, TestResult } from '@/types/api';

const MONACO_OPTIONS = {
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  automaticLayout: true,
  tabSize: 4,
  insertSpaces: true,
  renderWhitespace: 'selection' as const,
  padding: { top: 14, bottom: 14 },
  smoothScrolling: true,
  cursorBlinking: 'smooth' as const,
  bracketPairColorization: { enabled: true },
  fixedOverflowWidgets: true,
};

export default function Workbench() {
  const { slug = '' } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const celebrate = useRewards((s) => s.celebrate);
  const { editorFontSize, setEditorFontSize } = useUI();

  const [code, setCode] = useState('');
  const [explanation, setExplanation] = useState('');
  const [complexity, setComplexity] = useState('');
  const [confidence, setConfidence] = useState(0.6);
  const [grade, setGrade] = useState<Grade | null>(null);
  const [runOutput, setRunOutput] = useState<Grade | null>(null);
  const [hints, setHints] = useState<string[]>([]);
  const [showSolution, setShowSolution] = useState(false);
  const startedAt = useRef(Date.now());
  const [elapsed, setElapsed] = useState(0);

  const challenge = useQuery({
    queryKey: ['challenge', slug],
    queryFn: () => api.challenges.get(slug),
    enabled: !!slug,
  });

  // Seed the editor once, and never clobber what the player has typed on a
  // background refetch — losing in-progress work to a cache update is
  // unforgivable in an editor.
  const seeded = useRef(false);
  useEffect(() => {
    if (challenge.data && !seeded.current) {
      setCode(challenge.data.starter_code);
      seeded.current = true;
      startedAt.current = Date.now();
    }
  }, [challenge.data]);

  useEffect(() => {
    const timer = setInterval(() => setElapsed((Date.now() - startedAt.current) / 1000), 1000);
    return () => clearInterval(timer);
  }, []);

  const runMutation = useMutation({
    mutationFn: () => api.challenges.submit(slug, { code, run_only: true }),
    onSuccess: (result) => {
      setRunOutput(result);
      setGrade(null);
    },
  });

  const submitMutation = useMutation({
    mutationFn: () =>
      api.challenges.submit(slug, {
        code,
        elapsed_seconds: Math.round(elapsed),
        hints_used: hints.length,
        explanation: explanation || undefined,
        complexity: complexity || undefined,
        confidence,
      }),
    onSuccess: (result) => {
      setGrade(result);
      setRunOutput(null);
      celebrate(result.progression);
      // Progression touched the profile, the dashboard and the retention
      // numbers — invalidate them rather than hand-patching four caches.
      queryClient.invalidateQueries({ queryKey: ['profile'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['retention-summary'] });
      queryClient.invalidateQueries({ queryKey: ['challenge', slug] });
    },
  });

  const hintMutation = useMutation({
    mutationFn: () => api.challenges.hint(slug, hints.length),
    onSuccess: (result) => {
      setHints((prev) => [...prev, result.text]);
      queryClient.invalidateQueries({ queryKey: ['profile'] });
    },
  });

  const onEditorMount = useCallback<OnMount>((editor, monaco) => {
    monaco.editor.defineTheme('forge', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'comment', foreground: '5b6a99', fontStyle: 'italic' },
        { token: 'keyword', foreground: 'e879f9' },
        { token: 'string', foreground: '34d399' },
        { token: 'number', foreground: 'fbbf24' },
        { token: 'function', foreground: '22d3ee' },
      ],
      colors: {
        'editor.background': '#0b1020',
        'editor.lineHighlightBackground': '#141b3360',
        'editorLineNumber.foreground': '#3a4670',
        'editorCursor.foreground': '#22d3ee',
        'editor.selectionBackground': '#22d3ee30',
      },
    });
    monaco.editor.setTheme('forge');
    // Ctrl/Cmd+Enter submits — the muscle memory every code tool shares.
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
      document.getElementById('submit-challenge')?.click();
    });
  }, []);

  const result = grade ?? runOutput;
  const passed = grade?.passed ?? false;
  const canExplain = passed;

  const par = challenge.data?.par_seconds ?? 300;
  const paceTone = elapsed < par ? 'text-signal-success' : elapsed < par * 2 ? 'text-signal-warn' : 'text-signal-danger';

  if (challenge.isLoading) return <LoadingPanel rows={8} className="mx-auto max-w-6xl" />;
  if (challenge.isError || !challenge.data) {
    return (
      <Card title="Challenge not found">
        <p className="text-sm text-forge-400">
          {challenge.error instanceof ApiRequestError ? challenge.error.message : 'Unknown error.'}
        </p>
        <Button className="mt-4" onClick={() => navigate('/app/practice')}>
          Back to practice
        </Button>
      </Card>
    );
  }

  const c = challenge.data;

  return (
    <div className="mx-auto max-w-[1600px]">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to="/app/practice" className="mb-1 inline-flex items-center gap-1 text-xs text-forge-400 hover:text-forge-200">
            <ArrowLeft className="h-3 w-3" /> Practice
          </Link>
          <h1 className="font-display text-xl font-semibold tracking-tight">{c.title}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <TierChip tier={c.tier} showLabel />
            <Chip>{titleCase(c.category)}</Chip>
            {c.solved && (
              <span className="chip border-signal-success/40 bg-signal-success/10 text-signal-success">
                Solved
              </span>
            )}
            {c.expected_complexity && (
              <Chip className="font-mono normal-case">{c.expected_complexity}</Chip>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Tooltip label={`Par time ${duration(par)}`}>
            <span className={cn('font-mono text-sm tabular-nums', paceTone)}>{duration(elapsed)}</span>
          </Tooltip>
          <Tooltip label="Editor font size">
            <div className="flex items-center gap-1 rounded-lg border border-forge-700 px-1">
              <button
                onClick={() => setEditorFontSize(editorFontSize - 1)}
                className="px-1.5 text-forge-400 hover:text-forge-100"
                aria-label="Decrease font size"
              >
                −
              </button>
              <span className="font-mono text-xs text-forge-500">{editorFontSize}</span>
              <button
                onClick={() => setEditorFontSize(editorFontSize + 1)}
                className="px-1.5 text-forge-400 hover:text-forge-100"
                aria-label="Increase font size"
              >
                +
              </button>
            </div>
          </Tooltip>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        {/* ── Left: brief, tests, hints ─────────────────────────────────── */}
        <div className="space-y-4">
          <Card title="Brief">
            <div className="prose-forge whitespace-pre-wrap text-sm">{c.prompt.trim()}</div>
          </Card>

          <Card
            title="Visible tests"
            subtitle={
              c.hidden_test_count > 0
                ? `${c.visible_tests.length} shown · ${c.hidden_test_count} hidden`
                : `${c.visible_tests.length} checks`
            }
          >
            <ul className="space-y-1.5">
              {c.visible_tests.map((test) => (
                <li key={test.name} className="rounded-md border border-forge-700 bg-forge-950/60 px-3 py-2">
                  <div className="text-xs font-medium text-forge-200">{test.name}</div>
                  {test.call && (
                    <code className="mt-0.5 block font-mono text-[11px] text-accent-soft">
                      {test.call}
                      {test.expect !== undefined && test.expect !== null && (
                        <span className="text-forge-500"> → {JSON.stringify(test.expect)}</span>
                      )}
                    </code>
                  )}
                </li>
              ))}
            </ul>
            {c.hidden_test_count > 0 && (
              <p className="mt-3 text-xs leading-relaxed text-forge-500">
                {c.hidden_test_count} hidden test{c.hidden_test_count === 1 ? '' : 's'} run on submit.
                You cannot see them, exactly like the CI suite you will not be able to read either.
              </p>
            )}
          </Card>

          {/* Hints escalate, one at a time, and cost coins. */}
          <Card
            title="Mentor"
            subtitle={`${c.hints_available - hints.length} hint${c.hints_available - hints.length === 1 ? '' : 's'} left`}
            actions={
              hints.length < c.hints_available ? (
                <Button
                  size="sm"
                  variant="ghost"
                  loading={hintMutation.isPending}
                  onClick={() => hintMutation.mutate()}
                  icon={<Lightbulb className="h-3.5 w-3.5" />}
                >
                  Hint ({5 * (hints.length + 1)} coins)
                </Button>
              ) : undefined
            }
          >
            {hints.length === 0 ? (
              <p className="text-sm text-forge-500">
                Try it yourself first. Hints shorten your next review interval — the model knows
                you were helped.
              </p>
            ) : (
              <ol className="space-y-2">
                {hints.map((hint, i) => (
                  <motion.li
                    key={i}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="flex gap-2.5 rounded-lg border border-signal-warn/25 bg-signal-warn/5 p-3 text-sm text-forge-200"
                  >
                    <span className="font-mono text-xs text-signal-warn">{i + 1}</span>
                    {hint}
                  </motion.li>
                ))}
              </ol>
            )}
            {hintMutation.isError && (
              <p className="mt-2 text-xs text-signal-danger">
                {hintMutation.error instanceof ApiRequestError
                  ? hintMutation.error.message
                  : 'Could not fetch a hint.'}
              </p>
            )}
          </Card>
        </div>

        {/* ── Right: editor + results ───────────────────────────────────── */}
        <div className="space-y-4">
          <div className="panel overflow-hidden">
            <div className="flex items-center justify-between border-b border-forge-700 px-4 py-2">
              <span className="flex items-center gap-2 font-mono text-xs text-forge-400">
                <Terminal className="h-3.5 w-3.5" />
                solution.py
              </span>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<RotateCcw className="h-3.5 w-3.5" />}
                  onClick={() => setCode(c.starter_code)}
                >
                  Reset
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  loading={runMutation.isPending}
                  onClick={() => runMutation.mutate()}
                  icon={<Play className="h-3.5 w-3.5" />}
                >
                  Run
                </Button>
                <Button
                  id="submit-challenge"
                  size="sm"
                  variant="primary"
                  loading={submitMutation.isPending}
                  onClick={() => submitMutation.mutate()}
                  icon={<Send className="h-3.5 w-3.5" />}
                >
                  Submit
                </Button>
              </div>
            </div>
            <Editor
              height="440px"
              language="python"
              value={code}
              onChange={(value) => setCode(value ?? '')}
              onMount={onEditorMount}
              loading={<Spinner />}
              options={{ ...MONACO_OPTIONS, fontSize: editorFontSize }}
            />
            <div className="border-t border-forge-700 px-4 py-1.5 text-[11px] text-forge-600">
              Ctrl/⌘ + Enter to submit · runs in an isolated sandbox with a{' '}
              {c.time_limit_seconds}s limit and no network
            </div>
          </div>

          <AnimatePresence mode="wait">
            {result && (
              <motion.div
                key={grade ? 'grade' : 'run'}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
              >
                <ResultPanel result={result} isGrade={!!grade} onReveal={() => setShowSolution(true)} />
              </motion.div>
            )}
          </AnimatePresence>

          {/* ── Explain (spec §41) ─────────────────────────────────────── */}
          <Card
            title="Explain your solution"
            subtitle={canExplain ? 'This is where the real XP is' : 'Unlocks once the tests pass'}
            className={cn(!canExplain && 'opacity-60')}
          >
            {!canExplain ? (
              <p className="text-sm text-forge-500">
                Get the tests green first. Then tell me <em>why</em> it works — passing tests is not
                the same as understanding, and only one of the two survives six months.
              </p>
            ) : (
              <div className="space-y-3">
                {c.explanation_prompts.length > 0 && (
                  <ul className="space-y-1 text-xs text-forge-400">
                    {c.explanation_prompts.map((prompt, i) => (
                      <li key={i} className="flex gap-2">
                        <span className="text-forge-600">·</span>
                        {prompt}
                      </li>
                    ))}
                  </ul>
                )}
                <textarea
                  value={explanation}
                  onChange={(e) => setExplanation(e.target.value)}
                  rows={5}
                  placeholder="What is the complexity before and after? Why does it work? What would you do differently at 100x the data?"
                  className="w-full rounded-lg border border-forge-700 bg-forge-950/70 px-3 py-2 text-sm
                             text-forge-100 placeholder:text-forge-600 focus:border-accent"
                />
                <div className="flex flex-wrap items-end gap-3">
                  <div className="min-w-[140px]">
                    <label htmlFor="complexity" className="mb-1 block text-xs text-forge-400">
                      Complexity
                    </label>
                    <input
                      id="complexity"
                      value={complexity}
                      onChange={(e) => setComplexity(e.target.value)}
                      placeholder="O(n)"
                      className="w-full rounded-lg border border-forge-700 bg-forge-950/70 px-3 py-1.5
                                 font-mono text-sm text-forge-100 placeholder:text-forge-600 focus:border-accent"
                    />
                  </div>
                  <div className="min-w-[180px] flex-1">
                    <label htmlFor="confidence" className="mb-1 block text-xs text-forge-400">
                      How confident are you? ({(confidence * 100).toFixed(0)}%)
                    </label>
                    <input
                      id="confidence"
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={confidence}
                      onChange={(e) => setConfidence(Number(e.target.value))}
                      className="w-full accent-accent"
                    />
                  </div>
                  <Button
                    variant="primary"
                    loading={submitMutation.isPending}
                    onClick={() => submitMutation.mutate()}
                    icon={<Send className="h-3.5 w-3.5" />}
                  >
                    Submit explanation
                  </Button>
                </div>
                <p className="text-[11px] leading-relaxed text-forge-600">
                  Confidence is not vanity: the retention engine compares it against your actual
                  accuracy. Being sure and wrong schedules a much earlier review than being unsure
                  and wrong.
                </p>
              </div>
            )}
          </Card>
        </div>
      </div>

      <Modal open={showSolution} onClose={() => setShowSolution(false)} title="Reference solution" size="lg">
        <pre className="overflow-x-auto rounded-lg border border-forge-700 bg-forge-950 p-4 font-mono text-xs text-forge-200">
          {grade?.solution ?? '—'}
        </pre>
        {grade?.solution_explanation && (
          <p className="mt-4 text-sm leading-relaxed text-forge-300">{grade.solution_explanation}</p>
        )}
      </Modal>
    </div>
  );
}

// ── Result panel ────────────────────────────────────────────────────────────
function ResultPanel({
  result,
  isGrade,
  onReveal,
}: {
  result: Grade;
  isGrade: boolean;
  onReveal: () => void;
}) {
  const passed = result.passed;
  return (
    <Card
      className={cn(
        'border',
        passed ? 'border-signal-success/40' : 'border-signal-danger/40',
      )}
      title={
        <span className="flex items-center gap-2">
          {passed ? (
            <CheckCircle2 className="h-4 w-4 text-signal-success" />
          ) : (
            <XCircle className="h-4 w-4 text-signal-danger" />
          )}
          {result.headline}
        </span>
      }
      subtitle={
        result.tests_total > 0
          ? `${result.tests_passed} / ${result.tests_total} checks · ${result.runtime_ms.toFixed(0)}ms`
          : `${result.runtime_ms.toFixed(0)}ms`
      }
      actions={
        result.reveal_solution ? (
          <Button size="sm" variant="ghost" icon={<Eye className="h-3.5 w-3.5" />} onClick={onReveal}>
            Show solution
          </Button>
        ) : undefined
      }
    >
      {/* Failure as a postmortem, not a buzzer. */}
      {!passed && result.what_happened && (
        <div className="mb-3 rounded-lg border border-signal-danger/25 bg-signal-danger/5 p-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-signal-danger">
            What happened
          </div>
          <p className="mt-1 whitespace-pre-wrap font-mono text-xs leading-relaxed text-forge-200">
            {result.what_happened}
          </p>
          {result.root_cause && (
            <>
              <div className="mt-2.5 text-xs font-semibold uppercase tracking-wider text-signal-decay">
                Likely root cause
              </div>
              <p className="mt-1 font-mono text-xs text-forge-300">{result.root_cause}</p>
            </>
          )}
          {result.hint && (
            <div className="mt-2.5 flex gap-2 border-t border-signal-danger/20 pt-2.5 text-xs text-forge-300">
              <Lightbulb className="h-3.5 w-3.5 shrink-0 text-signal-warn" />
              {result.hint}
            </div>
          )}
        </div>
      )}

      {result.test_results.length > 0 && (
        <ul className="mb-3 space-y-1">
          {result.test_results.map((test, i) => (
            <TestRow key={`${test.name}-${i}`} test={test} />
          ))}
        </ul>
      )}

      {result.stdout && (
        <details className="mb-3" open={!result.test_results.length}>
          <summary className="cursor-pointer text-xs text-forge-400 hover:text-forge-200">
            stdout
          </summary>
          <pre className="mt-1.5 max-h-48 overflow-auto rounded-md border border-forge-700 bg-forge-950 p-2.5 font-mono text-[11px] text-forge-300">
            {result.stdout}
          </pre>
        </details>
      )}

      {result.stderr && (
        <pre className="mb-3 max-h-40 overflow-auto rounded-md border border-signal-danger/30 bg-signal-danger/5 p-2.5 font-mono text-[11px] text-signal-danger">
          {result.stderr}
        </pre>
      )}

      {result.speedup_factor && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-signal-success/30 bg-signal-success/5 px-3 py-2">
          <GaugeIcon className="h-4 w-4 text-signal-success" />
          <span className="text-sm text-forge-200">
            <strong className="font-mono text-signal-success">
              {result.speedup_factor.toFixed(1)}×
            </strong>{' '}
            faster than the baseline
          </span>
        </div>
      )}

      {result.detected_mistakes.length > 0 && (
        <div className="mb-3 space-y-2">
          <div className="text-xs font-semibold uppercase tracking-wider text-forge-400">
            Patterns detected in your code
          </div>
          {result.detected_mistakes.map((mistake) => (
            <div key={mistake.pattern} className="rounded-lg border border-forge-700 bg-forge-900/60 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <SeverityChip severity={mistake.severity} />
                <span className="text-sm font-medium text-forge-100">{mistake.title}</span>
                {mistake.line && (
                  <span className="font-mono text-[11px] text-forge-500">line {mistake.line}</span>
                )}
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-forge-400">{mistake.why_it_matters}</p>
              <p className="mt-1.5 text-xs leading-relaxed text-signal-success">
                → {mistake.correct_approach}
              </p>
            </div>
          ))}
        </div>
      )}

      {isGrade && result.explanation_feedback && (
        <div className="mb-3 rounded-lg border border-signal-xp/30 bg-signal-xp/5 p-3">
          <div className="flex items-baseline justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-signal-xp">
              Explanation
            </span>
            {result.explanation_score !== null && (
              <span className="font-mono text-xs text-signal-xp">
                {(result.explanation_score * 10).toFixed(1)}/10
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-forge-200">{result.explanation_feedback}</p>
          {result.missing_points.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-xs text-forge-400">
              {result.missing_points.map((point, i) => (
                <li key={i}>· {point}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {isGrade && result.mastery_delta && (
        <div className="rounded-lg border border-forge-700 bg-forge-900/60 p-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-forge-400">
            Memory updated
          </div>
          <ul className="mt-1.5 space-y-1">
            {Object.entries(result.mastery_delta).map(([slug, delta]) => (
              <li key={slug} className="flex items-baseline justify-between gap-3 text-xs">
                <span className="truncate text-forge-300">{slug}</span>
                <span className="shrink-0 font-mono tabular-nums">
                  <span className="text-forge-500">{(delta.before * 100).toFixed(0)}%</span>
                  <span className="mx-1 text-forge-600">→</span>
                  <span className="text-signal-success">{(delta.after * 100).toFixed(0)}%</span>
                  {delta.next_review_days !== undefined && (
                    <span className="ml-2 text-forge-600">
                      next in {delta.next_review_days.toFixed(0)}d
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function TestRow({ test }: { test: TestResult }) {
  const [open, setOpen] = useState(false);
  const hasDetail = !test.passed && (test.expected !== null || test.message);

  return (
    <li>
      <button
        onClick={() => hasDetail && setOpen((v) => !v)}
        className={cn(
          'flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs transition-colors',
          test.passed ? 'text-forge-400' : 'bg-signal-danger/5 text-forge-200',
          hasDetail && 'hover:bg-forge-800',
        )}
      >
        {test.passed ? (
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-signal-success" />
        ) : (
          <XCircle className="h-3.5 w-3.5 shrink-0 text-signal-danger" />
        )}
        <span className="truncate">{test.name}</span>
        {test.hidden && (
          <span className="ml-auto shrink-0 rounded bg-forge-700 px-1.5 text-[10px] text-forge-400">
            hidden
          </span>
        )}
      </button>
      {open && hasDetail && (
        <div className="ml-6 mt-1 space-y-1 rounded-md border border-forge-700 bg-forge-950 p-2.5 font-mono text-[11px]">
          {test.expected !== null && test.expected !== undefined && (
            <div>
              <span className="text-forge-500">expected </span>
              <span className="text-signal-success">{String(test.expected)}</span>
            </div>
          )}
          {test.actual !== null && test.actual !== undefined && (
            <div>
              <span className="text-forge-500">got      </span>
              <span className="text-signal-danger">{String(test.actual)}</span>
            </div>
          )}
          {test.message && <div className="text-forge-400">{test.message}</div>}
        </div>
      )}
    </li>
  );
}
