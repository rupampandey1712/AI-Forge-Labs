/**
 * The RAG Tuning Bench.
 *
 * THE LESSON THIS PAGE EXISTS TO TEACH: when a RAG system gives a wrong answer,
 * the instinct is to rewrite the prompt. That is almost always the wrong layer.
 * The bench makes the actual failure point visible by showing, for one question:
 * what was chunked, what was retrieved, at what score, in what order, and what
 * the model was finally handed.
 *
 * So the layout is the pipeline, top to bottom, in execution order —
 * chunk → retrieve → rerank → build context → generate — with timings on each
 * stage. A player who runs one question at k=2 and again at k=5 sees precision
 * fall while recall rises, in numbers, on their own question. That trade-off
 * survives being told once; it does not survive being read once.
 *
 * The chunk previewer is deliberately a separate, instant panel: it needs no
 * embedding, so it can update live while you drag, and watching boundaries slide
 * through a sentence is what makes "chunk_size is a semantic decision, not a
 * memory one" land.
 */

import { useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Braces,
  ChevronDown,
  Database,
  FileText,
  Play,
  Scissors,
  Search,
  Trophy,
} from 'lucide-react';
import { api } from '@/lib/api';
import { Button, Card, Chip, EmptyState, LoadingPanel, Tab, TabList, TabPanel, Tabs } from '@/components/ui';
import { Insight, Readout, Slider, Stale, Toggle } from '@/components/labs/controls';
import { fadeUp, pageTransition, quick, spring, stagger } from '@/lib/motion';
import { cn } from '@/lib/utils';
import type { RAGConfig, RAGQueryResponse, RetrievedChunk } from '@/types/labs';

const SAMPLE_TEXT = `# Password Reset Policy

A password reset link is valid for exactly 15 minutes from the moment it is issued. After that window the token is rejected and the user must request a new one.

Reset tokens are single-use. Once a token has been redeemed it is marked consumed, so a link forwarded to a third party cannot be replayed.

## Refresh Token Rotation

Every refresh issues a new token and revokes the old one. If a previously-rotated token is presented again, that is treated as theft rather than as a mistake: every session belonging to that user is revoked immediately.`;

const STAGE_COLORS: Record<string, string> = {
  embed_query: '#a78bfa',
  vector_search: '#22d3ee',
  keyword_search: '#34d399',
  fusion: '#67e8f9',
  rerank: '#fbbf24',
  build_context: '#5b6a99',
  generate: '#f43f5e',
};

export default function RagLab() {
  return (
    <motion.div
      variants={pageTransition}
      initial="hidden"
      animate="show"
      className="mx-auto max-w-7xl space-y-5"
    >
      <header>
        <div className="flex items-center gap-2.5">
          <Braces className="h-6 w-6 text-accent" />
          <h1 className="font-display text-2xl font-semibold tracking-tight">RAG Tuning Bench</h1>
        </div>
        <p className="mt-1.5 max-w-3xl text-sm text-forge-400">
          When RAG gives a wrong answer, the instinct is to rewrite the prompt. It is almost always
          the wrong layer. This bench shows you the whole pipeline — what was chunked, what was
          retrieved, at what score, and what the model was actually handed — so you can find the
          layer that failed instead of guessing at it.
        </p>
      </header>

      <Tabs defaultValue="query">
        <TabList>
          <Tab value="query" icon={<Search className="h-3.5 w-3.5" />}>
            Query bench
          </Tab>
          <Tab value="chunking" icon={<Scissors className="h-3.5 w-3.5" />}>
            Chunking
          </Tab>
          <Tab value="experiments" icon={<Trophy className="h-3.5 w-3.5" />}>
            Experiments
          </Tab>
          <Tab value="corpus" icon={<Database className="h-3.5 w-3.5" />}>
            Corpus
          </Tab>
        </TabList>
        <TabPanel value="query">
          <QueryBench />
        </TabPanel>
        <TabPanel value="chunking">
          <ChunkBench />
        </TabPanel>
        <TabPanel value="experiments">
          <ExperimentsPanel />
        </TabPanel>
        <TabPanel value="corpus">
          <CorpusPanel />
        </TabPanel>
      </Tabs>
    </motion.div>
  );
}

// ── Query bench ─────────────────────────────────────────────────────────────
function QueryBench() {
  const queryClient = useQueryClient();
  const { data: golden } = useQuery({ queryKey: ['labs', 'golden'], queryFn: api.labs.goldenSet });

  const [question, setQuestion] = useState('How long is a password reset link valid?');
  const [expected, setExpected] = useState('The reset link expires after 15 minutes.');
  const [relevant, setRelevant] = useState<string[]>(['forge-security-policy']);
  const [config, setConfig] = useState<RAGConfig>({
    top_k: 4,
    chunk_size: 400,
    chunk_overlap: 50,
    use_hybrid: false,
    use_reranker: false,
    temperature: 0.1,
    min_score: 0,
  });
  const [result, setResult] = useState<RAGQueryResponse | null>(null);
  const [dirty, setDirty] = useState(false);

  const run = useMutation({
    mutationFn: () =>
      api.labs.ragQuery({
        question,
        config,
        expected_answer: expected,
        relevant_doc_ids: relevant,
        save_experiment: true,
      }),
    onSuccess: (data) => {
      setResult(data);
      setDirty(false);
      void queryClient.invalidateQueries({ queryKey: ['labs', 'experiments'] });
    },
  });

  const patch = (next: Partial<RAGConfig>) => {
    setConfig((previous) => ({ ...previous, ...next }));
    setDirty(true);
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
      <div className="space-y-4">
        <Card title="Question" subtitle="Pick a golden case, or ask your own">
          <div className="space-y-3">
            <textarea
              value={question}
              rows={2}
              onChange={(e) => {
                setQuestion(e.target.value);
                setDirty(true);
              }}
              className="w-full resize-none rounded-lg border border-forge-700 bg-forge-900/70 px-3 py-2 text-xs text-forge-100 outline-none focus:border-accent"
            />
            <div className="space-y-1">
              {golden?.map((testCase) => (
                <button
                  key={testCase.question}
                  type="button"
                  onClick={() => {
                    setQuestion(testCase.question);
                    setExpected(testCase.expected);
                    setRelevant(testCase.relevant);
                    setDirty(true);
                  }}
                  className={cn(
                    'block w-full truncate rounded border px-2 py-1 text-left text-[11px] transition-colors',
                    testCase.question === question
                      ? 'border-accent/50 bg-accent/10 text-accent'
                      : 'border-forge-700/70 text-forge-400 hover:text-forge-200',
                  )}
                  title={testCase.relevant.length ? `Relevant: ${testCase.relevant.join(', ')}` : 'Unanswerable — the correct behaviour is to refuse'}
                >
                  {testCase.relevant.length === 0 && '⚠ '}
                  {testCase.question}
                </button>
              ))}
            </div>
            <p className="text-[11px] leading-snug text-forge-500">
              The ⚠ case is unanswerable from the corpus. A system that answers it confidently is
              failing in the most dangerous way available to it.
            </p>
          </div>
        </Card>

        <Card title="Pipeline configuration">
          <div className="space-y-4">
            <Slider
              label="top_k"
              value={config.top_k ?? 4}
              min={1}
              max={12}
              onChange={(value) => patch({ top_k: value })}
              hint="More chunks means higher recall and lower precision. Past a point you are paying for tokens that dilute the answer."
            />
            <Slider
              label="chunk_size"
              value={config.chunk_size ?? 400}
              min={100}
              max={1600}
              step={50}
              suffix=" chars"
              onChange={(value) => patch({ chunk_size: value })}
              hint="Small chunks retrieve precisely but lose the context that makes the passage meaningful. Large chunks keep context and dilute the embedding."
            />
            <Slider
              label="chunk_overlap"
              value={config.chunk_overlap ?? 50}
              min={0}
              max={400}
              step={10}
              suffix=" chars"
              onChange={(value) => patch({ chunk_overlap: value })}
              hint="Insurance against a fact being split across a boundary. You pay for it in duplicated storage and duplicated retrieval hits."
            />
            <Slider
              label="temperature"
              value={config.temperature ?? 0.1}
              min={0}
              max={1}
              step={0.05}
              onChange={(value) => patch({ temperature: value })}
              hint="For grounded answering, low. Creativity here shows up as invented citations."
            />
            <div className="space-y-3 border-t border-forge-700/60 pt-3.5">
              <Toggle
                label="Hybrid search (BM25 + vectors)"
                checked={config.use_hybrid ?? false}
                onChange={(value) => patch({ use_hybrid: value })}
                hint="Vectors miss exact identifiers — error codes, flag names, version numbers. BM25 catches them. Fused with reciprocal rank fusion."
              />
              <Toggle
                label="Reranker"
                checked={config.use_reranker ?? false}
                onChange={(value) => patch({ use_reranker: value })}
                hint="Retrieve broadly, then rescore the shortlist against the question directly. Watch the rank deltas — that movement is the reranker's entire value."
              />
            </div>
            <Button
              variant="primary"
              className="w-full"
              loading={run.isPending}
              icon={<Play className="h-4 w-4" />}
              onClick={() => run.mutate()}
            >
              Run pipeline
            </Button>
          </div>
        </Card>
      </div>

      <div className="space-y-4">
        {!result ? (
          <Card>
            <EmptyState
              icon={<Search className="h-8 w-8" />}
              title="Run the pipeline"
              description="Then change one setting and run it again. The bench is built for comparison — a single run tells you almost nothing."
            />
          </Card>
        ) : (
          <Stale stale={dirty}>
            <div className="space-y-4">
              <StageTimeline stages={result.stages} totalMs={result.total_ms} />

              <Card
                title="Answer"
                subtitle={`${result.total_ms.toFixed(0)}ms · ${result.token_usage.total ?? 0} tokens · $${result.cost_usd.toFixed(6)}`}
                actions={
                  result.simulated ? <Chip className="border-accent/30 bg-accent/10 text-accent">offline model</Chip> : null
                }
              >
                <motion.p
                  key={result.answer}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={spring}
                  className="text-sm leading-relaxed text-forge-200"
                >
                  {result.answer}
                </motion.p>
              </Card>

              {Object.keys(result.metrics).length > 0 && <MetricsRow metrics={result.metrics} />}

              {result.diagnosis.length > 0 && (
                <Card title="Diagnosis" subtitle="Which layer failed — read this before touching the prompt">
                  <ul className="space-y-2">
                    {result.diagnosis.map((note, index) => (
                      <motion.li
                        key={note}
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: index * 0.06, ...quick }}
                        className="flex gap-2 text-xs leading-relaxed text-forge-300"
                      >
                        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-signal-warn" />
                        <span>{note}</span>
                      </motion.li>
                    ))}
                  </ul>
                </Card>
              )}

              <RetrievedList chunks={result.retrieved} relevant={relevant} />

              <PromptPanel prompt={result.prompt} />
            </div>
          </Stale>
        )}
      </div>
    </div>
  );
}

/** The pipeline, as a proportional bar. Where the time actually goes. */
function StageTimeline({
  stages,
  totalMs,
}: {
  stages: { name: string; duration_ms: number; detail: Record<string, unknown> }[];
  totalMs: number;
}) {
  const sum = stages.reduce((a, s) => a + s.duration_ms, 0) || 1;
  return (
    <Card title="Pipeline stages" subtitle={`${totalMs.toFixed(1)}ms end to end`}>
      <div className="flex h-9 w-full overflow-hidden rounded-lg border border-forge-700">
        {stages.map((stage, index) => (
          <motion.div
            key={stage.name}
            initial={{ width: 0 }}
            animate={{ width: `${(stage.duration_ms / sum) * 100}%` }}
            transition={{ ...spring, delay: index * 0.06 }}
            title={`${stage.name}: ${stage.duration_ms.toFixed(2)}ms\n${JSON.stringify(stage.detail, null, 2)}`}
            className="group relative min-w-[3px] border-r border-forge-950 last:border-0"
            style={{ backgroundColor: `${STAGE_COLORS[stage.name] ?? '#273154'}cc` }}
          >
            <span className="absolute inset-0 flex items-center justify-center truncate px-1 font-mono text-[9px] text-forge-950 opacity-0 transition-opacity group-hover:opacity-100">
              {stage.duration_ms.toFixed(1)}
            </span>
          </motion.div>
        ))}
      </div>
      <motion.div variants={stagger(0.03)} initial="hidden" animate="show" className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {stages.map((stage) => (
          <motion.span
            key={stage.name}
            variants={fadeUp}
            className="inline-flex items-center gap-1.5 text-[11px] text-forge-400"
          >
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: STAGE_COLORS[stage.name] ?? '#273154' }}
            />
            <span className="font-mono">{stage.name}</span>
            <span className="tabular-nums text-forge-500">{stage.duration_ms.toFixed(1)}ms</span>
          </motion.span>
        ))}
      </motion.div>
    </Card>
  );
}

function MetricsRow({ metrics }: { metrics: Record<string, number> }) {
  const shown: [string, string, 'up' | 'down', string][] = [
    ['precision_at_k', 'Precision@k', 'up', 'Of what you retrieved, how much was relevant. Falls as k rises.'],
    ['recall_at_k', 'Recall@k', 'up', 'Of what was relevant, how much you retrieved. Rises as k rises.'],
    ['mrr', 'MRR', 'up', 'How high the first relevant hit landed. 1.0 means it was first.'],
    ['ndcg_at_k', 'nDCG@k', 'up', 'Ranking quality — rewards putting the best chunk first, not just including it.'],
    ['faithfulness', 'Faithfulness', 'up', 'How much of the answer is actually supported by the retrieved context. The hallucination metric.'],
    ['answer_relevance', 'Relevance', 'up', 'Whether the answer addresses the question that was asked.'],
    ['groundedness', 'Groundedness', 'up', 'Whether claims trace back to sources.'],
    ['answer_similarity', 'vs expected', 'up', 'Overlap with the golden answer.'],
  ];
  return (
    <motion.div
      variants={stagger(0.03)}
      initial="hidden"
      animate="show"
      className="grid grid-cols-2 gap-3 md:grid-cols-4"
    >
      {shown.map(([key, label, good, hint]) => {
        const value = metrics[key];
        if (value === undefined) return null;
        return (
          <motion.div key={key} variants={fadeUp}>
            <Readout label={label} value={value.toFixed(3)} good={good} hint={hint} />
          </motion.div>
        );
      })}
    </motion.div>
  );
}

function RetrievedList({ chunks, relevant }: { chunks: RetrievedChunk[]; relevant: string[] }) {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <Card
      title={`Retrieved ${chunks.length} chunks`}
      subtitle="Rank movement is the reranker's whole contribution — if nothing moves, it bought you nothing"
    >
      <div className="space-y-2">
        {chunks.map((chunk, index) => {
          const isRelevant = relevant.includes(chunk.doc_slug);
          const moved = chunk.original_rank !== null && chunk.original_rank !== index;
          const expanded = open === index;
          return (
            <motion.div
              key={`${chunk.doc_slug}-${chunk.chunk_index}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.05, ...spring }}
              className={cn(
                'overflow-hidden rounded-lg border',
                isRelevant ? 'border-signal-success/40 bg-signal-success/[0.05]' : 'border-forge-700 bg-forge-900/40',
              )}
            >
              <button
                type="button"
                onClick={() => setOpen(expanded ? null : index)}
                className="flex w-full items-center gap-3 px-3 py-2.5 text-left"
              >
                <span
                  className={cn(
                    'grid h-6 w-6 shrink-0 place-items-center rounded font-mono text-[11px] font-semibold',
                    isRelevant ? 'bg-signal-success/20 text-signal-success' : 'bg-forge-800 text-forge-400',
                  )}
                >
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium text-forge-100">{chunk.title}</span>
                  <span className="block truncate font-mono text-[10px] text-forge-500">
                    {chunk.doc_slug} · chunk {chunk.chunk_index}
                  </span>
                </span>
                {moved && (
                  <Chip
                    className={cn(
                      'font-mono',
                      (chunk.original_rank ?? 0) > index
                        ? 'border-signal-success/40 bg-signal-success/10 text-signal-success'
                        : 'border-signal-danger/40 bg-signal-danger/10 text-signal-danger',
                    )}
                    title={`Reranker moved this from position ${(chunk.original_rank ?? 0) + 1}`}
                  >
                    {(chunk.original_rank ?? 0) > index ? '↑' : '↓'}
                    {Math.abs((chunk.original_rank ?? 0) - index)}
                  </Chip>
                )}
                <span className="shrink-0 font-mono text-xs tabular-nums text-accent">
                  {(chunk.rerank_score ?? chunk.score).toFixed(3)}
                </span>
                <ChevronDown
                  className={cn('h-4 w-4 shrink-0 text-forge-500 transition-transform', expanded && 'rotate-180')}
                />
              </button>
              <AnimatePresence initial={false}>
                {expanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={quick}
                  >
                    <div className="border-t border-forge-700/60 px-3 py-2.5">
                      <p className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-forge-300">
                        {chunk.text}
                      </p>
                      {chunk.rerank_score !== null && (
                        <p className="mt-2 text-[10px] text-forge-500">
                          Vector score {chunk.score.toFixed(4)} → rerank {chunk.rerank_score.toFixed(4)}
                        </p>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          );
        })}
      </div>
    </Card>
  );
}

function PromptPanel({ prompt }: { prompt: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Card
      title="The prompt the model actually received"
      subtitle="Every RAG bug you cannot explain is visible here"
      actions={
        <Button size="sm" variant="ghost" onClick={() => setOpen((v) => !v)}>
          {open ? 'Hide' : 'Show'}
        </Button>
      }
    >
      <AnimatePresence initial={false}>
        {open ? (
          <motion.pre
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-forge-950/70 p-3 font-mono text-[11px] leading-relaxed text-forge-300"
          >
            {prompt}
          </motion.pre>
        ) : (
          <p className="text-xs text-forge-500">
            {prompt.length.toLocaleString()} characters of assembled context. Open it before
            concluding the model is at fault — more often than not the fact simply is not in here.
          </p>
        )}
      </AnimatePresence>
    </Card>
  );
}

// ── Chunking ────────────────────────────────────────────────────────────────
function ChunkBench() {
  const [text, setText] = useState(SAMPLE_TEXT);
  const [size, setSize] = useState(300);
  const [overlap, setOverlap] = useState(50);
  const [structure, setStructure] = useState(true);

  const body = { text, chunk_size: size, chunk_overlap: overlap, respect_structure: structure };
  const { data } = useQuery({
    queryKey: ['labs', 'chunk', body],
    queryFn: () => api.labs.chunkPreview(body),
    enabled: text.trim().length > 0,
    placeholderData: (previous) => previous,
  });

  // Colour-band the source text by which chunk each character lands in, so the
  // boundaries are visible *in the document* rather than as a separate list.
  const bands = useMemo(() => {
    if (!data) return null;
    return data.chunks.map((chunk, index) => ({
      ...chunk,
      hue: ['#22d3ee', '#a78bfa', '#34d399', '#fbbf24', '#f43f5e'][index % 5],
    }));
  }, [data]);

  return (
    <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
      <Card title="Chunking" subtitle="No embedding runs here — it updates while you drag">
        <div className="space-y-4">
          <Slider
            label="chunk_size"
            value={size}
            min={100}
            max={1200}
            step={25}
            suffix=" chars"
            onChange={setSize}
            hint="This is a semantic decision, not a memory one. The question is whether one chunk still means something on its own."
          />
          <Slider
            label="chunk_overlap"
            value={overlap}
            min={0}
            max={Math.max(50, Math.floor(size / 2))}
            step={10}
            suffix=" chars"
            onChange={setOverlap}
            hint="Overlap stops a fact being cut in half. It costs duplicated storage, and it lets one document occupy several top-k slots."
          />
          <Toggle
            label="Respect structure"
            checked={structure}
            onChange={setStructure}
            hint="Split on paragraphs first, then sentences, then words. Off, it cuts at exactly N characters — usually mid-sentence, sometimes mid-word."
          />
          <textarea
            value={text}
            rows={9}
            onChange={(e) => setText(e.target.value)}
            className="w-full resize-y rounded-lg border border-forge-700 bg-forge-900/70 px-3 py-2 font-mono text-[11px] leading-relaxed text-forge-100 outline-none focus:border-accent"
          />
        </div>
      </Card>

      <div className="space-y-4">
        {data && (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Readout label="Chunks" value={data.total_chunks} hint="How many vectors this document becomes" />
              <Readout label="Avg chars" value={data.avg_chars.toFixed(0)} />
              <Readout label="Avg tokens" value={data.avg_tokens.toFixed(0)} hint="Roughly what each retrieval hit costs you in context" />
              <Readout
                label="Overlap waste"
                value={`${data.overlap_waste_chars}`}
                good="down"
                hint="Characters stored more than once. The price of the insurance."
              />
            </div>

            <Insight tone={data.overlap_waste_chars > text.length * 0.35 ? 'warn' : 'info'}>
              {data.insight}
            </Insight>

            <Card title="Boundaries" subtitle="Each colour is one chunk; where they meet is where a fact can be cut in half">
              <div className="space-y-2">
                {bands?.map((chunk, index) => (
                  <motion.div
                    key={chunk.index}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: index * 0.03, ...quick }}
                    className="rounded-lg border-l-[3px] bg-forge-900/40 py-2 pl-3 pr-3"
                    style={{ borderLeftColor: chunk.hue }}
                  >
                    <div className="mb-1 flex items-center gap-2 font-mono text-[10px] text-forge-500">
                      <span style={{ color: chunk.hue }}>#{chunk.index}</span>
                      <span>
                        [{chunk.start_char}–{chunk.end_char}]
                      </span>
                      <span>{chunk.chars} chars</span>
                      <span>~{chunk.tokens} tokens</span>
                    </div>
                    <p className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-forge-300">
                      {chunk.text}
                    </p>
                  </motion.div>
                ))}
              </div>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}

// ── Experiments ─────────────────────────────────────────────────────────────
function ExperimentsPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ['labs', 'experiments'],
    queryFn: () => api.labs.experiments(20),
  });

  if (isLoading) return <LoadingPanel rows={6} />;
  if (!data?.experiments.length) {
    return (
      <Card>
        <EmptyState
          icon={<Trophy className="h-8 w-8" />}
          title="No experiments yet"
          description="Run a query on the bench. Every run is recorded here with its configuration, so you can compare two settings instead of trusting your memory of the last one."
        />
      </Card>
    );
  }

  const verdictTone =
    data.verdict === 'ship' ? 'success' : data.verdict === 'rollback' ? 'danger' : 'warn';

  return (
    <div className="space-y-4">
      <Card
        title="Latest vs previous"
        subtitle="The comparison that decides whether a change is real"
        actions={
          <Chip
            className={cn(
              'font-semibold uppercase',
              data.verdict === 'ship'
                ? 'border-signal-success/50 bg-signal-success/15 text-signal-success'
                : data.verdict === 'rollback'
                  ? 'border-signal-danger/50 bg-signal-danger/15 text-signal-danger'
                  : 'border-signal-warn/50 bg-signal-warn/15 text-signal-warn',
            )}
          >
            {data.verdict}
          </Chip>
        }
      >
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {Object.entries(data.delta)
            .filter(([key]) => !['k', 'relevant_found', 'relevant_total'].includes(key))
            .slice(0, 8)
            .map(([key, value]) => (
              <Readout
                key={key}
                label={key.replace(/_/g, ' ')}
                value={value > 0 ? `+${value.toFixed(3)}` : value.toFixed(3)}
                good={key.includes('latency') || key.includes('ms') ? 'down' : 'up'}
              />
            ))}
        </div>
        {data.reasons.length > 0 && (
          <div className="mt-4 space-y-2">
            {data.reasons.map((reason) => (
              <Insight key={reason} tone={verdictTone}>
                {reason}
              </Insight>
            ))}
          </div>
        )}
      </Card>

      <Card title="Run history" padded={false}>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-forge-700 text-left text-forge-500">
                <th className="px-4 py-2.5 font-medium">Question</th>
                <th className="px-2 py-2.5 text-right font-medium">k</th>
                <th className="px-2 py-2.5 text-right font-medium">chunk</th>
                <th className="px-2 py-2.5 text-center font-medium">hybrid</th>
                <th className="px-2 py-2.5 text-center font-medium">rerank</th>
                <th className="px-2 py-2.5 text-right font-medium">P@k</th>
                <th className="px-2 py-2.5 text-right font-medium">faith</th>
                <th className="px-4 py-2.5 text-right font-medium">ms</th>
              </tr>
            </thead>
            <tbody>
              {data.experiments.map((experiment, index) => (
                <motion.tr
                  key={experiment.id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(0.4, index * 0.03), ...quick }}
                  className={cn(
                    'border-b border-forge-800/70 last:border-0',
                    index === 0 && 'bg-accent/[0.04]',
                  )}
                >
                  <td className="max-w-[240px] truncate px-4 py-2 text-forge-300" title={experiment.question}>
                    {experiment.question}
                  </td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-forge-400">{experiment.top_k}</td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-forge-400">
                    {experiment.chunk_size}/{experiment.chunk_overlap}
                  </td>
                  <td className="px-2 py-2 text-center">{experiment.use_hybrid ? '●' : '○'}</td>
                  <td className="px-2 py-2 text-center">{experiment.use_reranker ? '●' : '○'}</td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-forge-200">
                    {experiment.metrics.precision_at_k?.toFixed(2) ?? '—'}
                  </td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-forge-200">
                    {experiment.metrics.faithfulness?.toFixed(2) ?? '—'}
                  </td>
                  <td className="px-4 py-2 text-right font-mono tabular-nums text-forge-500">
                    {experiment.latency_ms.toFixed(0)}
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ── Corpus ──────────────────────────────────────────────────────────────────
function CorpusPanel() {
  const { data, isLoading } = useQuery({ queryKey: ['labs', 'corpora'], queryFn: api.labs.corpora });

  if (isLoading) return <LoadingPanel rows={4} />;

  return (
    <motion.div variants={stagger()} initial="hidden" animate="show" className="space-y-4">
      {data?.map((corpus) => (
        <motion.div key={corpus.corpus} variants={fadeUp}>
          <Card
            title={corpus.corpus}
            subtitle={`${corpus.documents} documents · ${corpus.chunks} chunks · ${corpus.total_tokens.toLocaleString()} tokens`}
            actions={
              corpus.embedding_model ? (
                <Chip className="font-mono">{corpus.embedding_model}</Chip>
              ) : null
            }
          >
            <ul className="grid gap-1.5 sm:grid-cols-2">
              {corpus.titles.map((title) => (
                <li key={title} className="flex items-center gap-2 text-xs text-forge-300">
                  <FileText className="h-3.5 w-3.5 shrink-0 text-forge-500" />
                  <span className="truncate">{title}</span>
                </li>
              ))}
            </ul>
          </Card>
        </motion.div>
      ))}
      <Insight>
        This corpus is the game's own documentation — the security policy, the sandbox design, the
        retention model. That is deliberate: you can verify the retrieved answer against something
        you are able to read, which is exactly what you cannot do when evaluating RAG over a corpus
        you do not know.
      </Insight>
    </motion.div>
  );
}
