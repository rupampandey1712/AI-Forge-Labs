/**
 * The AI Mentor & Content Agent lab.
 *
 * TWO AGENTS, ONE PAGE, because they are two halves of the same idea: an agent
 * that decides *how much* to tell you, and an agent that decides *what to ask*
 * you next.
 *
 * THE MENTOR'S ESCALATION LADDER is the design that matters. A tutor that
 * answers your question is a tutor that removes the struggle, and the struggle
 * is the thing that forms the memory. So help is rationed against effort:
 *
 *     nudge → hint → concept → partial → full
 *
 * You cannot skip to `full` by asking nicely; you reach it by having attempted
 * the problem. The page shows the ladder explicitly with your current rung
 * lit — the mechanism is not hidden, because a player who understands the rule
 * engages with it instead of fighting it.
 *
 * THE CONTENT AGENT is shown *including its failures*. Generated questions are
 * run through the same validator as hand-authored ones, and rejected questions
 * are rendered with their rejection reasons rather than quietly dropped. That is
 * the honest demonstration: a model that writes a rubric its own ideal answer
 * cannot pass has produced an unscoreable question, and no amount of prompt
 * engineering downstream repairs it.
 */

import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  Bot,
  Check,
  HelpCircle,
  Lightbulb,
  Sparkles,
  ThumbsDown,
  Wand2,
  X,
} from 'lucide-react';
import { api } from '@/lib/api';
import { Button, Card, Chip, EmptyState, LoadingPanel, Tab, TabList, TabPanel, Tabs } from '@/components/ui';
import { Insight, Slider } from '@/components/labs/controls';
import { TierChip } from '@/components/game/bits';
import { fadeUp, pageTransition, quick, spring, stagger } from '@/lib/motion';
import { cn } from '@/lib/utils';
import type { GeneratedQuestion, MentorLevel } from '@/types/labs';

const LADDER: { level: MentorLevel; label: string; gives: string }[] = [
  { level: 'nudge', label: 'Nudge', gives: 'A direction to look in. No content.' },
  { level: 'hint', label: 'Hint', gives: 'The specific thing to check, still not the fix.' },
  { level: 'concept', label: 'Concept', gives: 'The underlying idea, applied to your case.' },
  { level: 'partial', label: 'Partial', gives: 'Most of the way. You assemble the last step.' },
  { level: 'full', label: 'Full', gives: 'The whole answer — earned by having tried.' },
];

export default function MentorLab() {
  return (
    <motion.div
      variants={pageTransition}
      initial="hidden"
      animate="show"
      className="mx-auto max-w-6xl space-y-5"
    >
      <header>
        <div className="flex items-center gap-2.5">
          <Bot className="h-6 w-6 text-signal-danger" />
          <h1 className="font-display text-2xl font-semibold tracking-tight">
            AI Mentor &amp; Content Agent
          </h1>
        </div>
        <p className="mt-1.5 max-w-3xl text-sm text-forge-400">
          A tutor that answers your question removes the struggle, and the struggle is what forms
          the memory. So this one rations help against effort, and shows you the rule it is using.
          The content agent below writes new questions — and gets rejected when its own rubric does
          not hold.
        </p>
      </header>

      <Tabs defaultValue="mentor">
        <TabList>
          <Tab value="mentor" icon={<Lightbulb className="h-3.5 w-3.5" />}>
            Mentor
          </Tab>
          <Tab value="socratic" icon={<HelpCircle className="h-3.5 w-3.5" />}>
            Socratic probe
          </Tab>
          <Tab value="generate" icon={<Wand2 className="h-3.5 w-3.5" />}>
            Content agent
          </Tab>
        </TabList>
        <TabPanel value="mentor">
          <MentorPanel />
        </TabPanel>
        <TabPanel value="socratic">
          <SocraticPanel />
        </TabPanel>
        <TabPanel value="generate">
          <GeneratePanel />
        </TabPanel>
      </Tabs>
    </motion.div>
  );
}

// ── Mentor ──────────────────────────────────────────────────────────────────
function MentorPanel() {
  const [question, setQuestion] = useState(
    'My decorator broke FastAPI — the endpoint stopped validating its request model.',
  );
  const [code, setCode] = useState(
    'def retry(fn):\n    def wrapper(*args, **kwargs):\n        for _ in range(3):\n            try:\n                return fn(*args, **kwargs)\n            except Exception:\n                pass\n    return wrapper',
  );
  const [attempts, setAttempts] = useState(0);
  const [hintsUsed, setHintsUsed] = useState(0);
  const [tier, setTier] = useState(6);

  const ask = useMutation({
    mutationFn: () =>
      api.labs.mentorAsk({
        question,
        code: code || null,
        tier,
        attempts,
        hints_used: hintsUsed,
      }),
  });

  const currentIndex = ask.data ? LADDER.findIndex((rung) => rung.level === ask.data.level) : -1;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <div className="space-y-4">
        <Card title="Escalation ladder" subtitle="Help is rationed against effort — this is the rule, stated">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-stretch">
            {LADDER.map((rung, index) => {
              const reached = currentIndex >= index;
              const active = currentIndex === index;
              return (
                <motion.div
                  key={rung.level}
                  animate={{
                    opacity: currentIndex === -1 ? 0.55 : reached ? 1 : 0.35,
                    scale: active ? 1.03 : 1,
                  }}
                  transition={spring}
                  className={cn(
                    'relative flex-1 rounded-lg border px-2.5 py-2',
                    active
                      ? 'border-accent bg-accent/10 shadow-glow'
                      : reached
                        ? 'border-forge-500 bg-forge-800/60'
                        : 'border-forge-700/60 bg-forge-900/40',
                  )}
                >
                  <div className="flex items-center gap-1.5">
                    <span
                      className={cn(
                        'grid h-4 w-4 place-items-center rounded-full text-[9px] font-bold',
                        active ? 'bg-accent text-forge-950' : reached ? 'bg-forge-500 text-forge-100' : 'bg-forge-800 text-forge-500',
                      )}
                    >
                      {index + 1}
                    </span>
                    <span className={cn('text-xs font-semibold', active ? 'text-accent' : 'text-forge-200')}>
                      {rung.label}
                    </span>
                  </div>
                  <p className="mt-1 text-[10px] leading-snug text-forge-500">{rung.gives}</p>
                </motion.div>
              );
            })}
          </div>
        </Card>

        <Card title="Ask the mentor">
          <div className="space-y-3">
            <textarea
              value={question}
              rows={2}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="What are you stuck on?"
              className="w-full resize-none rounded-lg border border-forge-700 bg-forge-900/70 px-3 py-2 text-xs text-forge-100 outline-none focus:border-accent"
            />
            <div>
              <label className="mb-1.5 block text-[11px] font-medium text-forge-300">
                Your code (optional — the mentor reads it)
              </label>
              <textarea
                value={code}
                rows={7}
                onChange={(e) => setCode(e.target.value)}
                spellCheck={false}
                className="w-full resize-y rounded-lg border border-forge-700 bg-forge-950/70 px-3 py-2 font-mono text-[11px] leading-relaxed text-forge-200 outline-none focus:border-accent"
              />
            </div>
            <Button
              variant="primary"
              className="w-full"
              loading={ask.isPending}
              icon={<Sparkles className="h-4 w-4" />}
              onClick={() => ask.mutate()}
            >
              Ask
            </Button>
          </div>
        </Card>

        <AnimatePresence mode="wait">
          {ask.data && (
            <motion.div
              key={`${ask.data.level}-${ask.data.message.slice(0, 20)}`}
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={spring}
            >
              <Card
                accent={ask.data.reveals_answer ? '#fbbf24' : '#22d3ee'}
                title={
                  <span className="flex items-center gap-2">
                    Mentor · {ask.data.level}
                    {ask.data.reveals_answer && (
                      <Chip className="border-signal-warn/40 bg-signal-warn/10 text-signal-warn">
                        reveals the answer
                      </Chip>
                    )}
                  </span>
                }
                subtitle={
                  ask.data.next_level
                    ? `Next rung: ${ask.data.next_level} — reached by attempting, not by asking again`
                    : 'Top of the ladder'
                }
              >
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-forge-200">
                  {ask.data.message}
                </p>
                {ask.data.question_back && (
                  <div className="mt-3 rounded-lg border border-accent/30 bg-accent/[0.06] px-3 py-2.5">
                    <div className="text-[10px] uppercase tracking-wide text-accent">
                      Back to you
                    </div>
                    <p className="mt-1 text-sm text-forge-200">{ask.data.question_back}</p>
                  </div>
                )}
                {ask.data.trace.length > 0 && (
                  <div className="mt-3 border-t border-forge-700/60 pt-3">
                    <div className="mb-1.5 text-[10px] uppercase tracking-wide text-forge-500">
                      The mentor is itself a graph — here is its own trace
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {ask.data.trace.map((entry, index) => (
                        <motion.span
                          key={index}
                          initial={{ opacity: 0, scale: 0.85 }}
                          animate={{ opacity: 1, scale: 1 }}
                          transition={{ delay: index * 0.07, ...quick }}
                          className="rounded bg-forge-800 px-2 py-0.5 font-mono text-[10px] text-forge-300"
                        >
                          {String(entry.node)}
                        </motion.span>
                      ))}
                    </div>
                  </div>
                )}
              </Card>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="space-y-4">
        <Card title="Your effort so far" subtitle="These inputs decide which rung you get">
          <div className="space-y-4">
            <Slider
              label="Attempts made"
              value={attempts}
              min={0}
              max={10}
              onChange={setAttempts}
              hint="Zero attempts gets a nudge no matter how the question is worded. Move this to 6 and ask the same thing — the answer changes."
            />
            <Slider
              label="Hints already used"
              value={hintsUsed}
              min={0}
              max={6}
              onChange={setHintsUsed}
              hint="Hints consumed on the challenge itself count toward escalation. Help is one budget, not several."
            />
            <Slider
              label="Difficulty tier"
              value={tier}
              min={1}
              max={10}
              onChange={setTier}
              hint="Higher tiers get answers pitched at a senior level — trade-offs and failure modes rather than syntax."
            />
            <div className="pt-1">
              <TierChip tier={tier} showLabel />
            </div>
          </div>
        </Card>

        <Insight>
          Try it: ask the same question at 0 attempts and again at 8. The mentor's job is not to be
          helpful on demand — it is to be helpful at the point where help still teaches something.
        </Insight>

        {ask.data && (
          <Card title="Call cost" padded>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <div className="text-[10px] uppercase tracking-wide text-forge-500">Tokens</div>
                <div className="mt-0.5 font-mono text-forge-200">{ask.data.tokens}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wide text-forge-500">Cost</div>
                <div className="mt-0.5 font-mono text-forge-200">
                  ${ask.data.cost_usd.toFixed(6)}
                </div>
              </div>
            </div>
            {ask.data.simulated && (
              <p className="mt-2 text-[11px] text-forge-500">
                Offline model — deterministic, seeded by a hash of the prompt.
              </p>
            )}
          </Card>
        )}
      </div>
    </div>
  );
}

// ── Socratic ────────────────────────────────────────────────────────────────
function SocraticPanel() {
  const { data: concepts } = useQuery({
    queryKey: ['concepts', 'for-labs'],
    queryFn: () => api.concepts.list({ page_size: 60 }),
  });
  const [slug, setSlug] = useState('');
  const [answer, setAnswer] = useState(
    'Generators are lazy — they use yield to produce values one at a time instead of building the whole list in memory.',
  );
  const [tier, setTier] = useState(5);

  const effectiveSlug = slug || concepts?.items[0]?.slug || '';
  const probe = useMutation({
    mutationFn: () =>
      api.labs.socratic({ concept_slug: effectiveSlug, player_answer: answer, tier }),
  });

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <div className="space-y-4">
        <Insight>
          The mentor helps you <em>finish</em>. This agent checks whether you{' '}
          <em>understood</em> — which is why it runs after a pass, not after a failure. A correct
          answer arrived at by pattern-matching looks identical to one arrived at by understanding,
          right up until the follow-up question.
        </Insight>

        <Card title="Your explanation" subtitle="Write it the way you would say it in an interview">
          <textarea
            value={answer}
            rows={6}
            onChange={(e) => setAnswer(e.target.value)}
            className="w-full resize-y rounded-lg border border-forge-700 bg-forge-900/70 px-3 py-2 text-xs leading-relaxed text-forge-100 outline-none focus:border-accent"
          />
          <Button
            variant="primary"
            className="mt-3 w-full"
            loading={probe.isPending}
            disabled={!effectiveSlug}
            icon={<HelpCircle className="h-4 w-4" />}
            onClick={() => probe.mutate()}
          >
            Probe my understanding
          </Button>
        </Card>

        <AnimatePresence>
          {probe.data && (
            <motion.div
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={spring}
            >
              <Card accent="#a78bfa" title="Follow-up">
                <p className="text-base leading-relaxed text-forge-100">{probe.data.question}</p>
                {probe.data.targets_misconception && (
                  <div className="mt-3 rounded-lg border border-signal-warn/30 bg-signal-warn/[0.06] px-3 py-2">
                    <div className="text-[10px] uppercase tracking-wide text-signal-warn">
                      The misconception this targets
                    </div>
                    <p className="mt-1 text-xs text-forge-300">{probe.data.targets_misconception}</p>
                  </div>
                )}
                {probe.data.good_answer_contains.length > 0 && (
                  <div className="mt-3">
                    <div className="mb-1.5 text-[10px] uppercase tracking-wide text-forge-500">
                      A good answer touches
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {probe.data.good_answer_contains.map((item, index) => (
                        <motion.span
                          key={item}
                          initial={{ opacity: 0, scale: 0.9 }}
                          animate={{ opacity: 1, scale: 1 }}
                          transition={{ delay: index * 0.06, ...quick }}
                        >
                          <Chip>{item}</Chip>
                        </motion.span>
                      ))}
                    </div>
                  </div>
                )}
              </Card>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <Card title="Concept">
        <div className="space-y-3">
          <select
            value={effectiveSlug}
            onChange={(e) => setSlug(e.target.value)}
            className="w-full rounded-lg border border-forge-700 bg-forge-900/70 px-3 py-2 text-xs text-forge-100 outline-none focus:border-accent"
          >
            {concepts?.items.map((concept) => (
              <option key={concept.slug} value={concept.slug}>
                {concept.title}
              </option>
            ))}
          </select>
          <Slider
            label="Tier"
            value={tier}
            min={1}
            max={10}
            onChange={setTier}
            hint="The probe comes back one tier above where you answered — understanding is checked slightly above the level demonstrated."
          />
        </div>
      </Card>
    </div>
  );
}

// ── Content agent ───────────────────────────────────────────────────────────
function GeneratePanel() {
  const { data: concepts } = useQuery({
    queryKey: ['concepts', 'for-labs'],
    queryFn: () => api.concepts.list({ page_size: 60 }),
  });
  const [slug, setSlug] = useState('');
  const [tier, setTier] = useState(5);
  const [kind, setKind] = useState('explain');
  const [count, setCount] = useState(2);

  const effectiveSlug = slug || concepts?.items[0]?.slug || '';
  const generate = useMutation({
    mutationFn: () =>
      api.labs.generate({ concept_slug: effectiveSlug, tier, kind, count }),
  });

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <div className="space-y-4">
        <Card title="Generate questions">
          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-forge-200">Concept</label>
              <select
                value={effectiveSlug}
                onChange={(e) => setSlug(e.target.value)}
                className="w-full rounded-lg border border-forge-700 bg-forge-900/70 px-3 py-2 text-xs text-forge-100 outline-none focus:border-accent"
              >
                {concepts?.items.map((concept) => (
                  <option key={concept.slug} value={concept.slug}>
                    {concept.title}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-forge-200">Kind</label>
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                className="w-full rounded-lg border border-forge-700 bg-forge-900/70 px-3 py-2 text-xs text-forge-100 outline-none focus:border-accent"
              >
                <option value="explain">Explain</option>
                <option value="mcq">Multiple choice</option>
                <option value="debug">Debug</option>
                <option value="tradeoff">Trade-off</option>
                <option value="design">Design</option>
              </select>
            </div>
            <Slider label="Tier" value={tier} min={1} max={10} onChange={setTier} />
            <Slider label="How many" value={count} min={1} max={5} onChange={setCount} />
            <Button
              variant="primary"
              className="w-full"
              loading={generate.isPending}
              disabled={!effectiveSlug}
              icon={<Wand2 className="h-4 w-4" />}
              onClick={() => generate.mutate()}
            >
              Generate
            </Button>
          </div>
        </Card>

        {generate.data && (
          <Card padded>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1.5">
                <Check className="h-4 w-4 text-signal-success" />
                <span className="font-mono text-lg text-signal-success">
                  {generate.data.accepted}
                </span>
                <span className="text-xs text-forge-500">accepted</span>
              </div>
              <div className="flex items-center gap-1.5">
                <X className="h-4 w-4 text-signal-danger" />
                <span className="font-mono text-lg text-signal-danger">
                  {generate.data.rejected}
                </span>
                <span className="text-xs text-forge-500">rejected</span>
              </div>
            </div>
            <p className="mt-3 text-[11px] leading-relaxed text-forge-400">
              {generate.data.validation_note}
            </p>
          </Card>
        )}
      </div>

      <div className="space-y-4">
        {!generate.data ? (
          <Card>
            <EmptyState
              icon={<Wand2 className="h-8 w-8" />}
              title="Let the agent write you a question"
              description="Then read what it produced critically. Rejected questions are shown with their reasons — that is the most instructive part of this panel."
            />
          </Card>
        ) : generate.isPending ? (
          <LoadingPanel rows={6} />
        ) : (
          <motion.div variants={stagger(0.08)} initial="hidden" animate="show" className="space-y-4">
            {generate.data.generated.map((question, index) => (
              <motion.div key={index} variants={fadeUp}>
                <GeneratedCard question={question} />
              </motion.div>
            ))}
          </motion.div>
        )}
      </div>
    </div>
  );
}

function GeneratedCard({ question }: { question: GeneratedQuestion }) {
  return (
    <Card
      accent={question.is_usable ? '#34d399' : '#f43f5e'}
      title={
        <span className="flex items-center gap-2">
          {question.is_usable ? (
            <Check className="h-4 w-4 text-signal-success" />
          ) : (
            <ThumbsDown className="h-4 w-4 text-signal-danger" />
          )}
          {question.is_usable ? 'Accepted' : 'Rejected'}
        </span>
      }
      subtitle={`${question.kind} · tier ${question.tier}`}
    >
      {question.issues.length > 0 && (
        <div className="mb-3 space-y-1.5">
          {question.issues.map((issue) => (
            <div
              key={issue}
              className="flex gap-2 rounded-lg border border-signal-danger/30 bg-signal-danger/[0.07] px-3 py-1.5"
            >
              <X className="mt-0.5 h-3.5 w-3.5 shrink-0 text-signal-danger" />
              <span className="text-[11px] leading-snug text-forge-300">{issue}</span>
            </div>
          ))}
        </div>
      )}

      {question.context && (
        <pre className="mb-3 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-forge-950/70 p-3 font-mono text-[11px] leading-relaxed text-forge-300">
          {question.context}
        </pre>
      )}

      <p className="text-sm leading-relaxed text-forge-100">{question.prompt}</p>

      {question.options.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {question.options.map((option, index) => (
            <li
              key={index}
              className={cn(
                'rounded-lg border px-3 py-2 text-xs',
                option.correct
                  ? 'border-signal-success/40 bg-signal-success/[0.06] text-forge-200'
                  : 'border-forge-700 text-forge-400',
              )}
            >
              <span>{option.text}</span>
              {option.why && (
                <p className="mt-1 text-[11px] italic text-forge-500">{option.why}</p>
              )}
            </li>
          ))}
        </ul>
      )}

      {question.rubric.length > 0 && (
        <div className="mt-3 border-t border-forge-700/60 pt-3">
          <div className="mb-1.5 text-[10px] uppercase tracking-wide text-forge-500">
            Rubric it would be graded against
          </div>
          <div className="space-y-1">
            {question.rubric.map((point, index) => (
              <div key={index} className="flex items-baseline gap-2 text-[11px]">
                <span className="font-mono text-accent">×{point.weight}</span>
                <span className="text-forge-300">{point.point}</span>
                <span className="truncate font-mono text-[10px] text-forge-600">
                  {point.keywords.join(', ')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {question.ideal_senior_answer && (
        <details className="mt-3">
          <summary className="cursor-pointer text-[11px] text-forge-500 hover:text-forge-300">
            Ideal answer the agent proposed
          </summary>
          <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-forge-300">
            {question.ideal_senior_answer}
          </p>
        </details>
      )}
    </Card>
  );
}
