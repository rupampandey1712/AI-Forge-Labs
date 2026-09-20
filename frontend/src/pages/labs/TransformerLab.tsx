/**
 * The Transformer Lab — attention, tokenization and sampling.
 *
 * DESIGN PRINCIPLE: every control here corresponds to a real term in the paper,
 * and flipping it changes real numbers. There is no "demo mode". The three
 * toggles are the whole pedagogy:
 *
 *   causal   — the upper triangle goes to exactly zero. That black wedge *is*
 *              "a decoder cannot see the future".
 *   scaled   — turn it off and softmax saturates: one cell goes to ~1.00 and the
 *              rest to ~0.00. That is what dividing by √d_k prevents, and it is
 *              far more convincing as a picture than as an argument about
 *              variance.
 *   positional — without it, "the cat the cat" produces two *identical* rows,
 *              because self-attention is permutation-equivariant. The lab
 *              detects and calls out that exact case.
 *
 * The tokenizer and sampling panels sit on the same page because they are the
 * two places transformer internals leak into engineering decisions people
 * actually make: what a prompt costs, and what temperature does to reliability.
 */

import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { Calculator, Coins, Eye, Layers, Thermometer, Wand2 } from 'lucide-react';
import { api } from '@/lib/api';
import { Card, Chip, LoadingPanel, Tab, TabList, TabPanel, Tabs } from '@/components/ui';
import { AttentionHeatmap } from '@/components/labs/AttentionHeatmap';
import { Insight, Readout, Segmented, Slider, Stale, Toggle } from '@/components/labs/controls';
import { barGrow, fadeUp, pageTransition, quick, spring, stagger } from '@/lib/motion';
import { cn } from '@/lib/utils';

const SAMPLE_TEXTS = [
  'The cat sat on the mat',
  'the cat the cat',
  'She poured water into the glass until it was full',
  'The trophy did not fit in the suitcase because it was too large',
];

export default function TransformerLab() {
  return (
    <motion.div
      variants={pageTransition}
      initial="hidden"
      animate="show"
      className="mx-auto max-w-6xl space-y-5"
    >
      <header>
        <div className="flex items-center gap-2.5">
          <Layers className="h-6 w-6 text-signal-xp" />
          <h1 className="font-display text-2xl font-semibold tracking-tight">Transformer Lab</h1>
        </div>
        <p className="mt-1.5 max-w-3xl text-sm text-forge-400">
          Every number below is really computed — real embeddings, real sinusoidal positions, real
          Q·Kᵀ/√d, real softmax. The projection matrices are seeded pseudo-random rather than
          trained, so the <em>mechanism</em> is genuine and the learned behaviour is not. That
          distinction is stated rather than hidden, because a visualiser that overclaims teaches the
          wrong thing.
        </p>
      </header>

      <Tabs defaultValue="attention">
        <TabList>
          <Tab value="attention" icon={<Eye className="h-3.5 w-3.5" />}>
            Attention
          </Tab>
          <Tab value="tokens" icon={<Coins className="h-3.5 w-3.5" />}>
            Tokenizer &amp; cost
          </Tab>
          <Tab value="sampling" icon={<Thermometer className="h-3.5 w-3.5" />}>
            Sampling
          </Tab>
        </TabList>
        <TabPanel value="attention">
          <AttentionPanel />
        </TabPanel>
        <TabPanel value="tokens">
          <TokenizerPanel />
        </TabPanel>
        <TabPanel value="sampling">
          <SamplingPanel />
        </TabPanel>
      </Tabs>
    </motion.div>
  );
}

// ── Attention ───────────────────────────────────────────────────────────────
function AttentionPanel() {
  const [text, setText] = useState(SAMPLE_TEXTS[0]);
  const [nHeads, setNHeads] = useState(4);
  const [causal, setCausal] = useState(false);
  const [scaled, setScaled] = useState(true);
  const [positional, setPositional] = useState(true);
  const [head, setHead] = useState(0);
  const [showRaw, setShowRaw] = useState(false);

  const params = { text, n_heads: nHeads, causal, scaled, use_positional: positional };
  const { data, isFetching, isError } = useQuery({
    queryKey: ['labs', 'attention', params],
    queryFn: () => api.labs.attention(params),
    // Keeps the previous matrix on screen while the next one computes, so the
    // heatmap morphs rather than flashing empty on every toggle.
    placeholderData: (previous) => previous,
  });

  const activeHead = data?.heads[Math.min(head, data.heads.length - 1)];

  return (
    <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
      <Card title="Controls" subtitle="Every toggle is a real term in the paper">
        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-forge-200">Input text</label>
            <textarea
              value={text}
              maxLength={400}
              rows={2}
              onChange={(e) => setText(e.target.value)}
              className="w-full resize-none rounded-lg border border-forge-700 bg-forge-900/70 px-3 py-2 font-mono text-xs text-forge-100 outline-none focus:border-accent"
            />
            <div className="mt-1.5 flex flex-wrap gap-1">
              {SAMPLE_TEXTS.map((sample) => (
                <button
                  key={sample}
                  type="button"
                  onClick={() => setText(sample)}
                  className={cn(
                    'rounded border px-1.5 py-0.5 text-[10px] transition-colors',
                    sample === text
                      ? 'border-accent/50 bg-accent/10 text-accent'
                      : 'border-forge-700 text-forge-400 hover:text-forge-200',
                  )}
                >
                  {sample.length > 22 ? `${sample.slice(0, 21)}…` : sample}
                </button>
              ))}
            </div>
          </div>

          <Slider
            label="Heads"
            value={nHeads}
            min={1}
            max={8}
            onChange={(value) => {
              setNHeads(value);
              setHead(0);
            }}
            hint="d_model stays at 64, so more heads means each one sees fewer dimensions. Eight heads of 8 dims each is a different model from one head of 64."
          />

          <div className="space-y-3 border-t border-forge-700/60 pt-3.5">
            <Toggle
              label="Causal mask"
              checked={causal}
              onChange={setCausal}
              hint="Zero out everything above the diagonal. This is the only difference between a BERT-style encoder and a GPT-style decoder."
            />
            <Toggle
              label="Scale by √d_k"
              checked={scaled}
              onChange={setScaled}
              hint="Turn this off and watch softmax saturate. Large d_k makes dot products large, which pushes softmax into a one-hot corner where gradients vanish."
            />
            <Toggle
              label="Positional encoding"
              checked={positional}
              onChange={setPositional}
              hint='Off, "the cat the cat" produces two identical rows — self-attention alone is permutation-equivariant and cannot tell position 0 from position 2.'
            />
            <Toggle
              label="Show raw scores"
              checked={showRaw}
              onChange={setShowRaw}
              hint="Pre-softmax Q·Kᵀ. This is where scaling is visible as a change in magnitude rather than a change in shape."
            />
          </div>
        </div>
      </Card>

      <div className="space-y-4">
        {isError ? (
          <Card>
            <p className="text-sm text-signal-danger">Could not compute attention for that input.</p>
          </Card>
        ) : !data ? (
          <LoadingPanel rows={8} />
        ) : (
          <>
            <Card
              title={`Head ${head + 1} of ${data.n_heads}`}
              subtitle={`d_model ${data.d_model} · d_head ${data.d_head} · ${data.tokens.length} tokens`}
              actions={
                <div className="flex items-center gap-2">
                  {causal && <Chip className="border-signal-warn/40 bg-signal-warn/10 text-signal-warn">causal</Chip>}
                  {!scaled && <Chip className="border-signal-danger/40 bg-signal-danger/10 text-signal-danger">unscaled</Chip>}
                  {!positional && <Chip className="border-forge-600">no PE</Chip>}
                </div>
              }
            >
              {data.n_heads > 1 && (
                <div className="mb-4 flex flex-wrap gap-1.5">
                  {data.heads.map((h, index) => (
                    <button
                      key={h.head}
                      type="button"
                      onClick={() => setHead(index)}
                      className={cn(
                        'relative rounded-md border px-2.5 py-1 text-xs transition-colors',
                        index === head
                          ? 'border-accent/60 text-accent'
                          : 'border-forge-700 text-forge-400 hover:text-forge-200',
                      )}
                    >
                      {index === head && (
                        <motion.span
                          layoutId="head-pill"
                          className="absolute inset-0 rounded-md bg-accent/12"
                          transition={spring}
                        />
                      )}
                      <span className="relative">H{index + 1}</span>
                    </button>
                  ))}
                </div>
              )}

              <Stale stale={isFetching}>
                {activeHead && (
                  <AttentionHeatmap
                    key={`${head}-${showRaw}-${causal}-${scaled}-${positional}-${text}`}
                    head={activeHead}
                    tokens={data.tokens}
                    causal={data.causal}
                    showRaw={showRaw}
                  />
                )}
              </Stale>
            </Card>

            <Insight tone={!scaled ? 'warn' : !positional ? 'warn' : 'info'}>{data.insight}</Insight>

            {activeHead && (
              <motion.div
                variants={stagger()}
                initial="hidden"
                animate="show"
                className="grid grid-cols-2 gap-3 md:grid-cols-4"
              >
                <motion.div variants={fadeUp}>
                  <Readout
                    label="Max weight"
                    value={Math.max(...activeHead.weights.flat()).toFixed(3)}
                    hint="Near 1.0 means this head has collapsed onto a single token — usually a sign of saturation."
                  />
                </motion.div>
                <motion.div variants={fadeUp}>
                  <Readout
                    label="Mean entropy"
                    value={(
                      activeHead.entropy.reduce((a, b) => a + b, 0) / activeHead.entropy.length
                    ).toFixed(3)}
                    hint="Low = focused head, high = diffuse head. Both exist in real models and do different jobs."
                  />
                </motion.div>
                <motion.div variants={fadeUp}>
                  <Readout
                    label="Row sum"
                    value={activeHead.weights[0]
                      ?.reduce((a, b) => a + b, 0)
                      .toFixed(3)}
                    hint="Must be 1.000 — every row is a probability distribution over which tokens to look at."
                  />
                </motion.div>
                <motion.div variants={fadeUp}>
                  <Readout
                    label="Masked cells"
                    value={
                      data.causal ? (data.tokens.length * (data.tokens.length - 1)) / 2 : 0
                    }
                    hint="Positions a token is forbidden from attending to."
                  />
                </motion.div>
              </motion.div>
            )}

            {data.vectors && (
              <Card
                title="Token vectors"
                subtitle={`First ${data.vectors.shown_dimensions} of ${data.d_model} dimensions — embedding, position, and their sum`}
              >
                <VectorStrips vectors={data.vectors} tokens={data.tokens.map((t) => t.text)} />
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** Embedding / positional / combined as three colour strips per token. */
function VectorStrips({
  vectors,
  tokens,
}: {
  vectors: {
    embedding: number[][];
    positional: number[][] | null;
    combined: number[][];
    shown_dimensions: number;
  };
  tokens: string[];
}) {
  const rows = [
    { label: 'embedding', data: vectors.embedding, hue: '167 139 250' },
    ...(vectors.positional ? [{ label: 'position', data: vectors.positional, hue: '251 191 36' }] : []),
    { label: 'combined', data: vectors.combined, hue: '34 211 238' },
  ];

  return (
    <div className="space-y-4 overflow-x-auto">
      {rows.map((row) => (
        <div key={row.label}>
          <div className="mb-1 text-[11px] font-medium text-forge-300">{row.label}</div>
          <div className="space-y-0.5">
            {row.data.map((values, index) => {
              const max = Math.max(...values.map(Math.abs), 1e-9);
              return (
                <div key={index} className="flex items-center gap-2">
                  <span className="w-16 shrink-0 truncate text-right font-mono text-[10px] text-forge-500">
                    {tokens[index]}
                  </span>
                  <div className="flex gap-px">
                    {values.map((value, dim) => (
                      <motion.span
                        key={dim}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: dim * 0.004, ...quick }}
                        title={`dim ${dim} = ${value.toFixed(3)}`}
                        className="h-3.5 w-2.5 rounded-[1px]"
                        style={{
                          backgroundColor: `rgb(${row.hue} / ${(Math.abs(value) / max) * 0.9 + 0.06})`,
                        }}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
      <p className="text-[11px] leading-relaxed text-forge-500">
        Compare the <span className="text-forge-300">embedding</span> rows for any repeated word:
        they are identical, because an embedding is a property of the token alone. The{' '}
        <span className="text-forge-300">combined</span> rows differ — that difference is the only
        thing telling the model which occurrence is which.
      </p>
    </div>
  );
}

// ── Tokenizer ───────────────────────────────────────────────────────────────
function TokenizerPanel() {
  const [text, setText] = useState(
    'Implement a retry decorator that preserves function metadata using functools.wraps and only retries on TransientError.',
  );
  const { data, isFetching } = useQuery({
    queryKey: ['labs', 'tokenize', text],
    queryFn: () => api.labs.tokenize(text),
    enabled: text.trim().length > 0,
    placeholderData: (previous) => previous,
  });

  return (
    <div className="space-y-4">
      <Card title="Tokenizer" subtitle="Paste a real prompt — the interesting numbers only show up at real length">
        <textarea
          value={text}
          rows={5}
          maxLength={20000}
          onChange={(e) => setText(e.target.value)}
          className="w-full resize-y rounded-lg border border-forge-700 bg-forge-900/70 px-3 py-2 font-mono text-xs leading-relaxed text-forge-100 outline-none focus:border-accent"
        />
      </Card>

      {data && (
        <Stale stale={isFetching}>
          <div className="space-y-4">
            <motion.div
              variants={stagger()}
              initial="hidden"
              animate="show"
              className="grid grid-cols-2 gap-3 md:grid-cols-5"
            >
              {[
                ['Tokens', data.stats.tokens, 'What you are billed for'],
                ['Words', data.stats.words, 'What you think you wrote'],
                ['Tokens / word', data.stats.tokens_per_word, 'English averages ~1.3; code and rare words go far higher'],
                ['Chars / token', data.stats.chars_per_token, 'A useful back-of-envelope: ~4 for English prose'],
                ['Subword splits', data.stats.subword_splits, 'Words the vocabulary did not contain whole'],
              ].map(([label, value, hint]) => (
                <motion.div key={String(label)} variants={fadeUp}>
                  <Readout label={String(label)} value={String(value)} hint={String(hint)} />
                </motion.div>
              ))}
            </motion.div>

            <Card title="Token stream" subtitle="Subword splits are tinted — those are the words the vocabulary lacked">
              <div className="flex flex-wrap gap-1">
                {data.tokens.slice(0, 400).map((token, index) => (
                  <motion.span
                    key={index}
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: Math.min(0.6, index * 0.004), ...quick }}
                    title={`#${token.index}  id=${token.id}${token.is_subword ? `  (part of "${token.of_word}")` : ''}`}
                    className={cn(
                      'rounded border px-1.5 py-0.5 font-mono text-[11px]',
                      token.is_subword
                        ? 'border-signal-xp/40 bg-signal-xp/10 text-signal-xp'
                        : 'border-forge-700 bg-forge-800/60 text-forge-300',
                    )}
                  >
                    {token.text}
                  </motion.span>
                ))}
                {data.tokens.length > 400 && (
                  <span className="px-1.5 py-0.5 text-[11px] text-forge-500">
                    +{data.tokens.length - 400} more
                  </span>
                )}
              </div>
            </Card>

            <Card
              title="What this prompt costs"
              subtitle="Per request, and per million requests — because per-request pennies are exactly why token bloat goes unnoticed"
            >
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-forge-700 text-left text-forge-500">
                      <th className="pb-2 font-medium">Model</th>
                      <th className="pb-2 text-right font-medium">This prompt, once</th>
                      <th className="pb-2 text-right font-medium">Per 1M requests</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.cost_estimates.map((estimate, index) => (
                      <motion.tr
                        key={estimate.model}
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: index * 0.03, ...quick }}
                        className="border-b border-forge-800/70 last:border-0"
                      >
                        <td className="py-1.5 font-mono text-forge-200">{estimate.model}</td>
                        <td className="py-1.5 text-right font-mono tabular-nums text-forge-400">
                          ${estimate.cost_per_request.toFixed(6)}
                        </td>
                        <td className="py-1.5 text-right font-mono tabular-nums font-semibold text-signal-warn">
                          ${estimate.input_cost_per_1m_requests.toLocaleString(undefined, {
                            maximumFractionDigits: 0,
                          })}
                        </td>
                      </motion.tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Insight tone="warn">
                <Calculator className="mr-1.5 inline h-3.5 w-3.5" />
                The rightmost column is the one that matters at scale. Trimming a system prompt by
                200 tokens looks like nothing per call and is a five-figure line item at a million
                calls a day. This is why prompt length is an engineering concern and not a writing
                one.
              </Insight>
            </Card>
          </div>
        </Stale>
      )}
    </div>
  );
}

// ── Sampling ────────────────────────────────────────────────────────────────
function SamplingPanel() {
  const [temperature, setTemperature] = useState(1.0);
  const [mode, setMode] = useState<'none' | 'top_k' | 'top_p'>('none');
  const [topK, setTopK] = useState(3);
  const [topP, setTopP] = useState(0.9);

  const body = {
    temperature,
    top_k: mode === 'top_k' ? topK : null,
    top_p: mode === 'top_p' ? topP : null,
  };
  const { data, isFetching } = useQuery({
    queryKey: ['labs', 'sampling', body],
    queryFn: () => api.labs.sampling(body),
    placeholderData: (previous) => previous,
  });

  return (
    <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
      <Card title="Decoding parameters" subtitle="The same logits, decoded three ways">
        <div className="space-y-4">
          <Slider
            label="Temperature"
            value={temperature}
            min={0.05}
            max={2}
            step={0.05}
            onChange={setTemperature}
            hint="Divides the logits before softmax. Below 1 sharpens (more deterministic), above 1 flattens (more varied). It does not add knowledge — it only redistributes confidence."
          />
          <Segmented
            label="Truncation"
            value={mode}
            onChange={setMode}
            options={[
              { value: 'none', label: 'None', hint: 'Sample from the full distribution' },
              { value: 'top_k', label: 'Top-k', hint: 'Keep a fixed number of tokens' },
              { value: 'top_p', label: 'Top-p', hint: 'Keep a fixed amount of probability mass' },
            ]}
          />
          <AnimatePresence mode="wait">
            {mode === 'top_k' && (
              <motion.div key="k" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
                <Slider
                  label="k"
                  value={topK}
                  min={1}
                  max={8}
                  onChange={setTopK}
                  hint="A fixed cut. When the model is genuinely certain, k=50 lets in 49 bad options; when it is uncertain, k=1 throws away the right answer."
                />
              </motion.div>
            )}
            {mode === 'top_p' && (
              <motion.div key="p" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
                <Slider
                  label="p"
                  value={topP}
                  min={0.1}
                  max={1}
                  step={0.05}
                  onChange={setTopP}
                  hint="Adaptive: keeps however many tokens it takes to cover p of the mass. On a confident step that is one token; on an uncertain step it is many. This is why it usually beats top-k."
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </Card>

      <div className="space-y-4">
        {!data ? (
          <LoadingPanel rows={6} />
        ) : (
          <Stale stale={isFetching}>
            <div className="space-y-4">
              <Card
                title='Next token after "The cat sat on the"'
                subtitle={data.truncation}
                actions={<Chip className="font-mono">T = {data.temperature}</Chip>}
              >
                <div className="flex h-56 items-end gap-2">
                  {data.labels.map((label, index) => {
                    const probability = data.final_probabilities[index];
                    const before = data.probabilities[index];
                    const kept = data.kept[index];
                    return (
                      <div key={label} className="flex min-w-0 flex-1 flex-col items-center gap-1.5">
                        <span
                          className={cn(
                            'font-mono text-[10px] tabular-nums',
                            kept ? 'text-forge-200' : 'text-forge-600',
                          )}
                        >
                          {(probability * 100).toFixed(1)}%
                        </span>
                        <div className="relative flex h-40 w-full items-end justify-center">
                          {/* Ghost bar = the distribution before truncation. The
                              gap between ghost and solid is exactly what
                              top-k/top-p threw away and redistributed. */}
                          <motion.div
                            className="absolute bottom-0 w-full rounded-t border border-dashed border-forge-600"
                            initial={{ height: 0 }}
                            animate={{ height: `${before * 100}%` }}
                            transition={spring}
                          />
                          <motion.div
                            variants={barGrow(index * 0.03)}
                            initial="hidden"
                            animate="show"
                            className={cn(
                              'relative w-full origin-bottom rounded-t',
                              kept ? 'bg-accent' : 'bg-forge-700',
                            )}
                            style={{ height: `${Math.max(probability * 100, 0.4)}%` }}
                          />
                        </div>
                        <span
                          className={cn(
                            'w-full truncate text-center font-mono text-[10px]',
                            label === data.argmax ? 'text-accent' : kept ? 'text-forge-300' : 'text-forge-600 line-through',
                          )}
                        >
                          {label}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-forge-500">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block h-2.5 w-2.5 rounded-sm bg-accent" /> after truncation
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block h-2.5 w-2.5 rounded-sm border border-dashed border-forge-600" />{' '}
                    before truncation
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block h-2.5 w-2.5 rounded-sm bg-forge-700" /> discarded
                  </span>
                </div>
              </Card>

              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Readout
                  label="Entropy"
                  value={data.entropy.toFixed(3)}
                  hint="0 = fully deterministic. Rising entropy is exactly what 'more creative' means — and also what 'less reliable' means. They are the same number."
                />
                <Readout label="Tokens kept" value={data.tokens_kept} hint="How many candidates survived truncation" />
                <Readout label="Argmax" value={data.argmax} mono hint="What greedy decoding (T→0) would always pick" />
                <Readout
                  label="Top prob"
                  value={`${(Math.max(...data.final_probabilities) * 100).toFixed(1)}%`}
                  hint="The winner's share after renormalisation"
                />
              </div>

              <Insight tone={data.entropy > 1.6 ? 'warn' : 'info'}>{data.insight}</Insight>

              <Card title="Why this matters in production" padded>
                <ul className="space-y-2 text-xs leading-relaxed text-forge-400">
                  <li className="flex gap-2">
                    <Wand2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
                    <span>
                      <strong className="text-forge-200">Structured output wants T≈0.</strong> If the
                      response must parse as JSON, every point of entropy is a chance to emit a
                      trailing comma. Creativity is not a feature of a parser.
                    </span>
                  </li>
                  <li className="flex gap-2">
                    <Wand2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-signal-warn" />
                    <span>
                      <strong className="text-forge-200">T=0 is not reproducible either.</strong>{' '}
                      Batched GPU inference reorders floating-point reductions, so two identical
                      requests can still diverge. Pin the seed <em>and</em> the model version, and
                      treat determinism as best-effort.
                    </span>
                  </li>
                  <li className="flex gap-2">
                    <Wand2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-signal-danger" />
                    <span>
                      <strong className="text-forge-200">Temperature cannot fix retrieval.</strong>{' '}
                      If the right document was never retrieved, no decoding setting recovers it —
                      the probability mass for the correct answer is not in the distribution at all.
                    </span>
                  </li>
                </ul>
              </Card>
            </div>
          </Stale>
        )}
      </div>
    </div>
  );
}
