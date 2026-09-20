/**
 * The Labs hub.
 *
 * The rest of the game asks you questions. The labs hand you the instrument and
 * let you break things — which is the other half of how engineers actually
 * learn. Each card states what its lab *teaches* rather than what it contains,
 * because "attention visualiser" tells you nothing about why you would open it.
 *
 * The status strip at the top is deliberately prominent: every lab works with
 * no API key, and a player who assumes otherwise never opens them.
 */

import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Bot,
  Braces,
  FlaskConical,
  GitBranch,
  Layers,
  MessageSquareCode,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { api } from '@/lib/api';
import { Card, Chip, LoadingPanel } from '@/components/ui';
import { Insight } from '@/components/labs/controls';
import { fadeUp, hoverLift, pageTransition, stagger } from '@/lib/motion';

const LABS = [
  {
    to: 'transformer',
    icon: Layers,
    title: 'Transformer Lab',
    teaches: 'Why attention is a weighted average, and what temperature really changes',
    detail:
      'Real Q·Kᵀ/√d on your own sentence. Toggle the causal mask and watch the upper triangle go black; turn off scaling and watch softmax saturate into a one-hot row.',
    accent: '#a78bfa',
    questions: ['Why divide by √d_k?', 'What does a low-entropy head mean?', 'Why is top-p usually better than top-k?'],
  },
  {
    to: 'rag',
    icon: Braces,
    title: 'RAG Tuning Bench',
    teaches: 'That retrieval quality, not prompt wording, is what breaks RAG',
    detail:
      'Drag chunk size and watch boundaries move. Run the same question at k=2 and k=5, with and without hybrid search and reranking, and read the precision/recall trade in the numbers.',
    accent: '#22d3ee',
    questions: ['Where did the answer actually fail — retrieval or generation?', 'Does more context always help?'],
  },
  {
    to: 'agents',
    icon: GitBranch,
    title: 'Agent Factory',
    teaches: 'How agent graphs terminate — and how they fail to',
    detail:
      'Inspect the topology before you run it, then replay execution step by step over the same diagram. One graph ships deliberately broken; debugging it teaches more than reading a correct one.',
    accent: '#34d399',
    questions: ['Why does this agent loop forever?', 'Why is raising the recursion limit the wrong fix?'],
  },
  {
    to: 'evals',
    icon: ShieldCheck,
    title: 'Evaluation Lab',
    teaches: 'How to decide whether a change is safe to ship',
    detail:
      'Run a golden set against two configurations, compare them, and get a ship / hold / rollback verdict with the reasoning attached. This is the discipline that separates a demo from a system.',
    accent: '#fbbf24',
    questions: ['Which metric regressed?', 'Is a 3% faithfulness drop worth a 40ms latency win?'],
  },
  {
    to: 'mentor',
    icon: Bot,
    title: 'AI Mentor & Content Agent',
    teaches: 'How to get help without getting the answer',
    detail:
      'An agent that escalates from a nudge to a full explanation only as you earn it — and a content agent that writes new questions about your weakest concepts, then gets rejected when its own rubric does not hold.',
    accent: '#f43f5e',
    questions: ['What am I actually missing here?', 'Can a model write a question worth answering?'],
  },
] as const;

export default function Labs() {
  const { data: status, isLoading } = useQuery({
    queryKey: ['labs', 'status'],
    queryFn: api.labs.status,
    staleTime: 5 * 60_000,
  });

  return (
    <motion.div
      variants={pageTransition}
      initial="hidden"
      animate="show"
      className="mx-auto max-w-6xl space-y-5"
    >
      <div>
        <div className="flex items-center gap-2.5">
          <FlaskConical className="h-6 w-6 text-accent" />
          <h1 className="font-display text-2xl font-semibold tracking-tight">AI Forge Labs</h1>
        </div>
        <p className="mt-1.5 max-w-3xl text-sm text-forge-400">
          Instruments, not tutorials. Every lab computes the real thing and shows you every
          intermediate value, because the difference between knowing that attention is a weighted
          average and <em>seeing the weights</em> is the difference between reciting and
          understanding.
        </p>
      </div>

      {isLoading ? (
        <LoadingPanel rows={2} />
      ) : status ? (
        <Insight tone={status.llm.simulated ? 'info' : 'success'}>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <Sparkles className="h-3.5 w-3.5 shrink-0 text-accent" />
            <span>
              LLM: <span className="font-mono text-forge-100">{status.llm.provider}</span>
              {status.llm.simulated && (
                <Chip className="ml-1.5 border-accent/30 bg-accent/10 text-accent">offline</Chip>
              )}
            </span>
            <span className="text-forge-600">·</span>
            <span>
              Embeddings: <span className="font-mono text-forge-100">{status.embeddings.model}</span>
            </span>
          </div>
          <p className="mt-1.5">{status.note}</p>
        </Insight>
      ) : null}

      <motion.div
        variants={stagger(0.07)}
        initial="hidden"
        animate="show"
        className="grid gap-4 md:grid-cols-2"
      >
        {LABS.map((lab) => {
          const Icon = lab.icon;
          return (
            <motion.div key={lab.to} variants={fadeUp} {...hoverLift}>
              <Link to={lab.to} className="block h-full focus:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-xl">
                <Card accent={lab.accent} className="h-full transition-shadow hover:shadow-glow">
                  <div className="flex items-start gap-3.5">
                    <span
                      className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border"
                      style={{
                        borderColor: `${lab.accent}55`,
                        backgroundColor: `${lab.accent}14`,
                        color: lab.accent,
                      }}
                    >
                      <Icon className="h-5 w-5" />
                    </span>
                    <div className="min-w-0">
                      <h2 className="font-display text-base font-semibold text-forge-100">
                        {lab.title}
                      </h2>
                      <p className="mt-0.5 text-xs font-medium" style={{ color: lab.accent }}>
                        {lab.teaches}
                      </p>
                      <p className="mt-2.5 text-sm leading-relaxed text-forge-400">{lab.detail}</p>
                      <ul className="mt-3 space-y-1">
                        {lab.questions.map((question) => (
                          <li
                            key={question}
                            className="flex items-start gap-1.5 text-[11px] text-forge-500"
                          >
                            <MessageSquareCode className="mt-0.5 h-3 w-3 shrink-0" />
                            <span>{question}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </Card>
              </Link>
            </motion.div>
          );
        })}
      </motion.div>
    </motion.div>
  );
}
