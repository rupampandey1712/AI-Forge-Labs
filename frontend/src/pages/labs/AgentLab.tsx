/**
 * The Agent Factory — inspect a graph, then watch it execute over itself.
 *
 * WHY INSPECT BEFORE RUN: the single most common failure in agent work is
 * debugging a stack trace when you should be debugging a diagram. So the
 * topology loads first, with its cycles already marked, and only then do you get
 * a Run button. By the time execution starts you have already seen where the
 * loops are.
 *
 * THE REPLAY is the heart of the page. Execution history is a list of steps,
 * each with the state diff that step produced; scrubbing through it moves the
 * highlight across the same graph you were just reading and shows exactly which
 * key changed and to what. That is the mental model needed to debug real agents,
 * and it is almost never taught because most tutorials only show the final
 * answer.
 *
 * THE BROKEN GRAPH is the point of the whole lab. `runaway_agent` has a cycle
 * with no counter, so it halts on the recursion limit every time. Its visit
 * counts sit next to `reflection_agent`'s, which loops the same way but
 * increments a budget. Comparing the two is what teaches that the fix is a
 * termination condition, not a bigger limit.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  GitBranch,
  Hand,
  Pause,
  Play,
  RotateCcw,
  Zap,
} from 'lucide-react';
import { api } from '@/lib/api';
import { Button, Card, Chip, EmptyState, LoadingPanel } from '@/components/ui';
import { GraphCanvas } from '@/components/labs/GraphCanvas';
import { Insight, Readout, Slider } from '@/components/labs/controls';
import { fadeUp, pageTransition, quick, spring, stagger } from '@/lib/motion';
import { cn } from '@/lib/utils';
import type { AgentRunResponse } from '@/types/labs';

export default function AgentLab() {
  const { data: graphs, isLoading } = useQuery({
    queryKey: ['labs', 'graphs'],
    queryFn: api.labs.graphs,
  });
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!selected && graphs?.length) setSelected(graphs[0].slug);
  }, [graphs, selected]);

  return (
    <motion.div
      variants={pageTransition}
      initial="hidden"
      animate="show"
      className="mx-auto max-w-7xl space-y-5"
    >
      <header>
        <div className="flex items-center gap-2.5">
          <GitBranch className="h-6 w-6 text-signal-success" />
          <h1 className="font-display text-2xl font-semibold tracking-tight">Agent Factory</h1>
        </div>
        <p className="mt-1.5 max-w-3xl text-sm text-forge-400">
          An agent is a graph with state, and the interesting question is never "what did it answer"
          — it is "why did it take that path, and what stops it". Inspect the topology first, then
          replay execution over the same diagram, one step and one state diff at a time.
        </p>
      </header>

      {isLoading ? (
        <LoadingPanel rows={4} />
      ) : (
        <motion.div
          variants={stagger(0.05)}
          initial="hidden"
          animate="show"
          className="grid gap-3 md:grid-cols-2 xl:grid-cols-4"
        >
          {graphs?.map((graph) => (
            <motion.button
              key={graph.slug}
              variants={fadeUp}
              type="button"
              onClick={() => setSelected(graph.slug)}
              whileHover={{ y: -3 }}
              className={cn(
                'rounded-xl border p-3.5 text-left transition-colors',
                selected === graph.slug
                  ? 'border-accent/60 bg-accent/[0.06] shadow-glow'
                  : graph.broken
                    ? 'border-signal-danger/40 bg-signal-danger/[0.04] hover:border-signal-danger/60'
                    : 'border-forge-700 bg-forge-900/40 hover:border-forge-500',
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="text-sm font-semibold text-forge-100">{graph.title}</span>
                {graph.broken && <Ban className="h-4 w-4 shrink-0 text-signal-danger" />}
              </div>
              <p className="mt-1 text-[11px] leading-snug text-forge-400">{graph.teaches}</p>
              <div className="mt-2.5 flex flex-wrap gap-1.5 font-mono text-[10px] text-forge-500">
                <span>{graph.nodes} nodes</span>
                <span>·</span>
                <span>{graph.edges} edges</span>
                {graph.cycles > 0 && (
                  <>
                    <span>·</span>
                    <span className="text-signal-warn">{graph.cycles} cycle{graph.cycles > 1 ? 's' : ''}</span>
                  </>
                )}
              </div>
            </motion.button>
          ))}
        </motion.div>
      )}

      <AnimatePresence mode="wait">
        {selected && (
          <motion.div
            key={selected}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={spring}
          >
            <GraphWorkspace
              slug={selected}
              info={graphs?.find((graph) => graph.slug === selected)}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function GraphWorkspace({
  slug,
  info,
}: {
  slug: string;
  info?: { title: string; teaches: string; watch_for: string; broken: boolean };
}) {
  const { data: diagram, isLoading } = useQuery({
    queryKey: ['labs', 'graph', slug],
    queryFn: () => api.labs.graph(slug),
  });

  const [question, setQuestion] = useState('I was charged twice for my subscription');
  const [limit, setLimit] = useState(25);
  const [run, setRun] = useState<AgentRunResponse | null>(null);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);

  const execute = useMutation({
    mutationFn: () =>
      api.labs.runAgent({ graph: slug, question, recursion_limit: limit, save_run: true }),
    onSuccess: (data) => {
      setRun(data);
      setCursor(0);
      setPlaying(data.history.length > 1);
    },
  });

  const resume = useMutation({
    mutationFn: (approved: boolean) =>
      api.labs.resumeAgent({
        run_id: run!.run_id!,
        approved,
        note: approved ? 'Approved by player' : 'Rejected by player',
      }),
    onSuccess: (data) => {
      setRun(data);
      setCursor(Math.max(0, data.history.length - 1));
    },
  });

  // Auto-advance the replay. The interval is deliberately slow (620ms): the
  // point is to read each state diff, not to watch an animation finish.
  const timer = useRef<number | null>(null);
  useEffect(() => {
    if (!playing || !run) return;
    timer.current = window.setInterval(() => {
      setCursor((current) => {
        if (current >= run.history.length - 1) {
          setPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, 620);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [playing, run]);

  // Reset when the graph changes — showing one graph's trace over another's
  // topology would be actively misleading.
  useEffect(() => {
    setRun(null);
    setCursor(0);
    setPlaying(false);
  }, [slug]);

  const step = run?.history[cursor];
  const path = useMemo(
    () => run?.history.slice(0, cursor + 1).map((s) => s.node) ?? [],
    [run, cursor],
  );
  const visitsSoFar = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const node of path) counts[node] = (counts[node] ?? 0) + 1;
    return counts;
  }, [path]);

  if (isLoading || !diagram) return <LoadingPanel rows={8} />;

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_400px]">
      <div className="space-y-4">
        <Card
          title={info?.title ?? diagram.name}
          subtitle={info?.teaches}
          accent={info?.broken ? '#f43f5e' : '#34d399'}
          actions={
            run && (
              <Chip
                className={cn(
                  'font-mono uppercase',
                  run.status === 'completed'
                    ? 'border-signal-success/50 bg-signal-success/15 text-signal-success'
                    : run.status === 'halted'
                      ? 'border-signal-danger/50 bg-signal-danger/15 text-signal-danger'
                      : 'border-signal-warn/50 bg-signal-warn/15 text-signal-warn',
                )}
              >
                {run.status}
              </Chip>
            )
          }
        >
          <GraphCanvas
            diagram={diagram}
            activeNode={step?.node ?? null}
            visitedPath={path}
            visits={visitsSoFar}
          />
        </Card>

        {info?.watch_for && (
          <Insight tone={info.broken ? 'danger' : 'info'}>
            <strong className="text-forge-100">Watch for:</strong> {info.watch_for}
          </Insight>
        )}

        {diagram.cycles.length > 0 && (
          <Card title={`${diagram.cycles.length} cycle${diagram.cycles.length > 1 ? 's' : ''}`} subtitle="A cycle is not a bug — but every one needs a termination argument">
            <div className="space-y-2">
              {diagram.cycles.map((cycle, index) => (
                <div
                  key={index}
                  className="flex flex-wrap items-center gap-1.5 rounded-lg border border-signal-warn/30 bg-signal-warn/[0.05] px-3 py-2"
                >
                  {cycle.map((node, position) => (
                    <span key={`${node}-${position}`} className="flex items-center gap-1.5">
                      <span className="font-mono text-[11px] text-signal-warn">{node}</span>
                      {position < cycle.length - 1 && <ChevronRight className="h-3 w-3 text-forge-600" />}
                    </span>
                  ))}
                  <RotateCcw className="ml-1 h-3 w-3 text-signal-warn" />
                </div>
              ))}
            </div>
          </Card>
        )}

        {run && <ReplayPanel run={run} cursor={cursor} />}
      </div>

      <div className="space-y-4">
        <Card title="Run it">
          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-forge-200">Input</label>
              <textarea
                value={question}
                rows={3}
                onChange={(e) => setQuestion(e.target.value)}
                className="w-full resize-none rounded-lg border border-forge-700 bg-forge-900/70 px-3 py-2 text-xs text-forge-100 outline-none focus:border-accent"
              />
            </div>
            <Slider
              label="recursion_limit"
              value={limit}
              min={3}
              max={60}
              onChange={setLimit}
              hint="The safety net, not the fix. On the runaway graph, raising this just burns more tokens before failing in the same place."
            />
            <Button
              variant="primary"
              className="w-full"
              loading={execute.isPending}
              icon={<Zap className="h-4 w-4" />}
              onClick={() => execute.mutate()}
            >
              Execute graph
            </Button>
          </div>
        </Card>

        {run && (
          <>
            <Card
              title="Replay"
              subtitle={`Step ${cursor + 1} of ${run.history.length}`}
              actions={
                <div className="flex items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setCursor((c) => Math.max(0, c - 1))}
                    disabled={cursor === 0}
                    aria-label="Previous step"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setPlaying((p) => !p)}
                    aria-label={playing ? 'Pause' : 'Play'}
                  >
                    {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setCursor((c) => Math.min(run.history.length - 1, c + 1))}
                    disabled={cursor >= run.history.length - 1}
                    aria-label="Next step"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              }
            >
              <input
                type="range"
                min={0}
                max={Math.max(0, run.history.length - 1)}
                value={cursor}
                onChange={(e) => {
                  setPlaying(false);
                  setCursor(Number(e.target.value));
                }}
                className="lab-range h-5 w-full cursor-pointer appearance-none rounded-full bg-forge-800"
                aria-label="Execution step"
              />

              <AnimatePresence mode="wait">
                {step && (
                  <motion.div
                    key={cursor}
                    initial={{ opacity: 0, x: 12 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -12 }}
                    transition={quick}
                    className="mt-3 space-y-3"
                  >
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-accent/15 px-2 py-0.5 font-mono text-xs font-semibold text-accent">
                        {step.node}
                      </span>
                      <span className="font-mono text-[11px] text-forge-500">
                        {step.duration_ms.toFixed(1)}ms
                      </span>
                      {step.status !== 'ok' && (
                        <Chip className="border-signal-danger/40 bg-signal-danger/10 text-signal-danger">
                          {step.status}
                        </Chip>
                      )}
                    </div>

                    {step.edge_taken && (
                      <div className="rounded-lg border border-forge-700/70 bg-forge-900/50 px-3 py-2">
                        <div className="text-[10px] uppercase tracking-wide text-forge-500">
                          Router decision
                        </div>
                        <div className="mt-1 font-mono text-xs text-forge-200">
                          → {step.edge_taken}
                        </div>
                        {step.edge_reason && (
                          <p className="mt-1 text-[11px] leading-snug text-forge-400">
                            {step.edge_reason}
                          </p>
                        )}
                      </div>
                    )}

                    <div>
                      <div className="mb-1.5 text-[10px] uppercase tracking-wide text-forge-500">
                        State diff — what this node changed
                      </div>
                      {Object.keys(step.state_diff).length === 0 ? (
                        <p className="text-[11px] italic text-forge-500">
                          Nothing. A node that changes no state is either a pure router or a bug.
                        </p>
                      ) : (
                        <div className="space-y-1.5">
                          {Object.entries(step.state_diff).map(([key, value]) => (
                            <motion.div
                              key={key}
                              initial={{ opacity: 0, x: -6 }}
                              animate={{ opacity: 1, x: 0 }}
                              className="rounded border border-signal-success/25 bg-signal-success/[0.06] px-2.5 py-1.5"
                            >
                              <span className="font-mono text-[11px] font-semibold text-signal-success">
                                {key}
                              </span>
                              <pre className="mt-0.5 max-h-24 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-forge-300">
                                {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
                              </pre>
                            </motion.div>
                          ))}
                        </div>
                      )}
                    </div>

                    {step.error && (
                      <div className="rounded-lg border border-signal-danger/40 bg-signal-danger/10 px-3 py-2">
                        <p className="font-mono text-[11px] text-signal-danger">{step.error}</p>
                      </div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </Card>

            {run.status === 'interrupted' && run.run_id && (
              <Card accent="#f43f5e" title="Waiting for a human" subtitle={`Paused before: ${run.interrupted_at}`}>
                <p className="text-xs leading-relaxed text-forge-300">
                  This node is marked <code className="font-mono text-forge-100">interrupt_before</code>.
                  The graph stopped and persisted its state rather than acting. Any agent that can
                  spend money, send mail or delete data needs one of these, and "the model is usually
                  right" is not an argument against it.
                </p>
                <div className="mt-3 flex gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    icon={<CheckCircle2 className="h-4 w-4" />}
                    loading={resume.isPending}
                    onClick={() => resume.mutate(true)}
                  >
                    Approve
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    icon={<Hand className="h-4 w-4" />}
                    loading={resume.isPending}
                    onClick={() => resume.mutate(false)}
                  >
                    Reject
                  </Button>
                </div>
              </Card>
            )}

            <div className="grid grid-cols-2 gap-3">
              <Readout label="Steps" value={run.steps} />
              <Readout label="Total" value={`${run.total_ms.toFixed(0)}ms`} good="down" />
            </div>

            {Object.keys(run.node_visits).length > 0 && <VisitChart visits={run.node_visits} looped={run.looped} />}

            {run.diagnosis.length > 0 && (
              <Card title="Diagnosis">
                <div className="space-y-2">
                  {run.diagnosis.map((note, index) => (
                    <motion.div
                      key={note}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: index * 0.07, ...quick }}
                      className="flex gap-2 text-xs leading-relaxed text-forge-300"
                    >
                      <AlertTriangle
                        className={cn(
                          'mt-0.5 h-3.5 w-3.5 shrink-0',
                          run.status === 'halted' ? 'text-signal-danger' : 'text-signal-warn',
                        )}
                      />
                      <span>{note}</span>
                    </motion.div>
                  ))}
                </div>
              </Card>
            )}
          </>
        )}

        {!run && (
          <Card>
            <EmptyState
              icon={<GitBranch className="h-8 w-8" />}
              title="Read the graph first"
              description="Find the cycles and the interrupt before you run anything. Debugging the diagram is cheaper than debugging the trace."
            />
          </Card>
        )}
      </div>
    </div>
  );
}

/** Visit counts. On a looping graph these two numbers *are* the diagnosis. */
function VisitChart({ visits, looped }: { visits: Record<string, number>; looped: boolean }) {
  const entries = Object.entries(visits).sort((a, b) => b[1] - a[1]);
  const max = Math.max(...entries.map(([, count]) => count), 1);
  return (
    <Card
      title="Node visits"
      subtitle={looped ? 'A node visited repeatedly is where the budget went' : 'Each node ran once — no loop'}
    >
      <div className="space-y-2">
        {entries.map(([node, count], index) => (
          <div key={node} className="flex items-center gap-2">
            <span className="w-20 shrink-0 truncate font-mono text-[11px] text-forge-300">{node}</span>
            <div className="h-4 flex-1 overflow-hidden rounded bg-forge-800">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${(count / max) * 100}%` }}
                transition={{ ...spring, delay: index * 0.05 }}
                className={cn('h-full rounded', count > 2 ? 'bg-signal-warn' : 'bg-accent')}
              />
            </div>
            <span className="w-7 shrink-0 text-right font-mono text-[11px] tabular-nums text-forge-400">
              ×{count}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

/** The full trace as a scannable list, for when scrubbing is too slow. */
function ReplayPanel({ run, cursor }: { run: AgentRunResponse; cursor: number }) {
  return (
    <Card title="Execution trace" padded={false}>
      <div className="max-h-72 overflow-y-auto">
        {run.history.map((step, index) => (
          <div
            key={step.step}
            className={cn(
              'flex items-center gap-3 border-b border-forge-800/60 px-4 py-2 last:border-0 transition-colors',
              index === cursor && 'bg-accent/[0.07]',
              index > cursor && 'opacity-40',
            )}
          >
            <span className="w-5 shrink-0 text-right font-mono text-[10px] text-forge-600">
              {step.step}
            </span>
            <span
              className={cn(
                'w-24 shrink-0 truncate font-mono text-[11px]',
                index === cursor ? 'text-accent' : 'text-forge-300',
              )}
            >
              {step.node}
            </span>
            <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-forge-500">
              {Object.keys(step.state_diff).join(', ') || '—'}
            </span>
            {step.edge_taken && (
              <span className="shrink-0 font-mono text-[10px] text-signal-warn">
                →{step.edge_taken}
              </span>
            )}
            <span className="w-12 shrink-0 text-right font-mono text-[10px] tabular-nums text-forge-600">
              {step.duration_ms.toFixed(0)}ms
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}
