import { motion } from 'framer-motion';
import {
  Activity,
  ArrowRight,
  Bug,
  Brain,
  Mic,
  Search,
  ShieldCheck,
  Swords,
  Workflow,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui';

const PILLARS = [
  {
    icon: Activity,
    title: 'Knowledge decays. So does the game.',
    body: 'A forgetting curve tracks every concept you touch. Stop practising generators and your mastery visibly falls — then the game sends you a repair mission. This is why it is still worth opening in six months.',
  },
  {
    icon: Bug,
    title: 'Broken systems, real evidence',
    body: 'Logs, metrics, stack traces, query plans. You are not asked what an N+1 is; you are given a service doing 5,000 queries per request and asked why.',
  },
  {
    icon: Mic,
    title: 'An interviewer that follows up',
    body: 'Answer well and it goes deeper. Answer badly and it reframes. Scored across seven dimensions, with a debrief that shows exactly what a Staff answer would have added.',
  },
  {
    icon: Brain,
    title: 'Ten tiers per concept',
    body: '"What is a decorator?" is tier 1. "This decorator-heavy framework is unmaintainable — do you keep it?" is tier 9. The same concept, and the game does not stop at the first one.',
  },
  {
    icon: Search,
    title: 'AI systems you can break',
    body: 'Build a RAG pipeline, then debug why it retrieves the wrong document. Tune chunk size against a golden set. Watch an agent loop forever and add the guard yourself.',
  },
  {
    icon: ShieldCheck,
    title: 'Your code runs in a sandbox',
    body: 'Isolated process or container, no network, scrubbed environment, hard timeouts. The game server never executes your code in-process — because that is the correct architecture, and the game teaches why.',
  },
];

const LADDER = [
  'Python Apprentice',
  'Python Developer',
  'Backend Engineer',
  'Senior Python Engineer',
  'ML Engineer',
  'Deep Learning Engineer',
  'AI Engineer',
  'LLM Engineer',
  'AI Platform Engineer',
  'Staff AI Engineer',
  'Principal AI Engineer',
];

export default function Landing() {
  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-signal-xp">
            <span className="font-display text-sm font-bold text-forge-950">AF</span>
          </div>
          <span className="font-display font-semibold">AI Forge Labs</span>
        </div>
        <Link to="/login">
          <Button variant="ghost" size="sm">
            Sign in
          </Button>
        </Link>
      </header>

      {/* ── Hero ──────────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-4xl px-6 pb-16 pt-12 text-center">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <span className="chip border-accent/40 bg-accent/10 text-accent">
            Python · Backend · Data · ML · LLM · RAG · Agents
          </span>
          <h1 className="mt-6 text-balance font-display text-4xl font-bold leading-tight tracking-tight sm:text-6xl">
            Learn it. Build it. <span className="text-accent">Break it.</span>
            <br />
            Debug it. Explain it. Master it.
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-balance text-lg leading-relaxed text-forge-300">
            An engineering simulator, not a tutorial. You join{' '}
            <strong className="text-forge-100">AI Forge Labs</strong> as a Python Apprentice and
            work your way to Principal — through production incidents, broken pipelines,
            architecture reviews and interviews that do not accept a memorised answer.
          </p>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Link to="/login?mode=register">
              <Button variant="primary" size="lg" icon={<ArrowRight className="h-4 w-4" />}>
                Start as an Apprentice
              </Button>
            </Link>
            <Link to="/login">
              <Button variant="secondary" size="lg">
                I have an account
              </Button>
            </Link>
          </div>
        </motion.div>
      </section>

      {/* ── The decay pitch — the actual differentiator ────────────────── */}
      <section className="mx-auto max-w-4xl px-6 pb-20">
        <motion.div
          initial={{ opacity: 0, scale: 0.97 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.45 }}
          className="panel overflow-hidden"
        >
          <div className="border-b border-signal-decay/30 bg-signal-decay/10 px-5 py-3">
            <span className="font-mono text-xs font-semibold uppercase tracking-widest text-signal-decay">
              ⚠ Generator knowledge decay detected
            </span>
          </div>
          <div className="p-6">
            <p className="text-forge-200">
              Your <strong className="text-forge-100">generator</strong> mastery dropped from{' '}
              <span className="font-mono text-signal-success">91%</span> →{' '}
              <span className="font-mono text-signal-decay">68%</span>. Four concepts including
              &ldquo;Generators&rdquo; have not been practised for 32 days.
            </p>
            <div className="mt-4 flex items-center gap-3 rounded-lg border border-forge-700 bg-forge-950/60 px-4 py-3">
              <Swords className="h-4 w-4 shrink-0 text-accent" aria-hidden />
              <div className="text-sm">
                <div className="font-medium text-forge-100">Repair the Data Pipeline</div>
                <div className="text-xs text-forge-400">
                  Emergency mission · requires generators · ~18 min
                </div>
              </div>
            </div>
            <p className="mt-5 text-sm leading-relaxed text-forge-400">
              This is the point. Most learning apps let you finish a course and forget it. This one
              models what you are losing and drags it back before it is gone — which is the only
              reason a training tool is still useful a year later.
            </p>
          </div>
        </motion.div>
      </section>

      {/* ── Pillars ───────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 pb-20">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {PILLARS.map((pillar, i) => (
            <motion.div
              key={pillar.title}
              initial={{ opacity: 0, y: 14 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.35, delay: i * 0.05 }}
              className="panel panel-hover p-5"
            >
              <pillar.icon className="h-5 w-5 text-accent" aria-hidden />
              <h3 className="mt-3 font-display text-base font-semibold text-forge-100">
                {pillar.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-forge-400">{pillar.body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ── Career ladder ─────────────────────────────────────────────── */}
      <section className="mx-auto max-w-4xl px-6 pb-20">
        <h2 className="text-center font-display text-2xl font-semibold">The ladder</h2>
        <p className="mx-auto mt-2 max-w-2xl text-center text-sm text-forge-400">
          Eleven ranks across 100 levels. The game simulates the problems an engineer at each band
          is expected to solve — it does not claim to hand you the years.
        </p>
        <ol className="mt-8 space-y-1.5">
          {LADDER.map((rank, i) => (
            <motion.li
              key={rank}
              initial={{ opacity: 0, x: -12 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.3, delay: i * 0.035 }}
              className="flex items-center gap-4 rounded-lg border border-forge-800 bg-forge-900/50 px-4 py-2.5"
            >
              <span className="w-6 shrink-0 text-right font-mono text-xs text-forge-600">
                {i + 1}
              </span>
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ backgroundColor: `hsl(${190 + i * 12} 75% 58%)` }}
              />
              <span className="text-sm text-forge-200">{rank}</span>
              {i === LADDER.length - 1 && (
                <span className="chip ml-auto border-signal-warn/40 bg-signal-warn/10 text-signal-warn">
                  Capstone
                </span>
              )}
            </motion.li>
          ))}
        </ol>
      </section>

      {/* ── Closing ───────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-3xl px-6 pb-24 text-center">
        <Workflow className="mx-auto h-6 w-6 text-forge-600" aria-hidden />
        <blockquote className="mt-5 text-balance font-display text-xl leading-relaxed text-forge-200">
          &ldquo;I don&rsquo;t just remember Python syntax. I understand how Python works. I can
          debug production systems, design architectures, build RAG, evaluate AI systems — and
          defend every decision in an interview.&rdquo;
        </blockquote>
        <p className="mt-4 text-sm text-forge-500">— what the game is actually for</p>
        <Link to="/login?mode=register" className="mt-8 inline-block">
          <Button variant="primary" size="lg" icon={<ArrowRight className="h-4 w-4" />}>
            Enter the Forge
          </Button>
        </Link>
      </section>

      <footer className="border-t border-forge-800 py-6 text-center text-xs text-forge-600">
        AI Forge Labs — a fictional company, a real curriculum.
      </footer>
    </div>
  );
}
