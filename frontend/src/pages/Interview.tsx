/**
 * The Interview Arena.
 *
 * What makes this an interview rather than a quiz, in UI terms:
 *
 * - The interviewer *reacts* before the next question. That single line of
 *   dialogue is what creates the sense of a person on the other side.
 * - Follow-ups are visually marked as part of the same thread, so the player
 *   feels the questioning going deeper rather than moving on.
 * - The debrief shows what a Staff answer would have added. A score alone
 *   teaches nothing; the gap is the lesson.
 * - Pressure mode shows a per-question clock, because real interviews have one.
 */

import { AnimatePresence, motion } from 'framer-motion';
import { ArrowRight, CornerDownRight, Mic, Send, Timer, TrendingUp } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from 'recharts';
import { api } from '@/lib/api';
import { Button, Card, Chip, LoadingPanel, Stat } from '@/components/ui';
import { TierChip } from '@/components/game/bits';
import { useRewards } from '@/stores/game';
import { cn, duration, titleCase, VERDICT_LABELS } from '@/lib/utils';
import type { InterviewFeedback, InterviewTurn } from '@/types/api';

const LEVELS = ['junior', 'mid', 'senior', 'staff', 'principal'] as const;

export default function Interview() {
  const { sessionId } = useParams();
  return sessionId ? <InterviewRun sessionId={sessionId} /> : <InterviewLobby />;
}

// ── Lobby ───────────────────────────────────────────────────────────────────
function InterviewLobby() {
  const navigate = useNavigate();
  const [level, setLevel] = useState<(typeof LEVELS)[number]>('mid');
  const [mode, setMode] = useState<'standard' | 'pressure'>('standard');
  const [count, setCount] = useState(6);

  const readiness = useQuery({ queryKey: ['readiness'], queryFn: api.analytics.readiness });

  const start = useMutation({
    mutationFn: () =>
      api.interview.start({ level, mode, question_count: count }),
    onSuccess: (session) => navigate(`/app/interview/${session.id}`),
  });

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">Interview Arena</h1>
        <p className="mt-1 text-sm text-forge-400">
          An interviewer that follows up. Answer well and it goes deeper; answer badly and it
          reframes. Scored across seven dimensions.
        </p>
      </div>

      {readiness.data && (
        <Card title="Interview readiness" subtitle="Weighted from your mastery and your actual answers">
          <div className="grid gap-4 sm:grid-cols-[auto_1fr]">
            <div className="flex items-center gap-4">
              {LEVELS.map((lvl) => (
                <div key={lvl} className="text-center">
                  <div className="font-display text-lg tabular-nums text-accent">
                    {Math.round((readiness.data.by_level[lvl] ?? 0) * 100)}
                  </div>
                  <div className="text-[10px] uppercase tracking-wide text-forge-500">{lvl}</div>
                </div>
              ))}
            </div>
            <div>
              <div className="stat-label mb-2">Biggest gaps</div>
              <ul className="space-y-1.5">
                {readiness.data.blocking_gaps.slice(0, 3).map((gap) => (
                  <li key={gap.slug} className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="truncate text-forge-300">{gap.name}</span>
                    <span className="shrink-0 font-mono text-xs text-forge-500">
                      {Math.round(gap.value * 100)}% · weight {Math.round(gap.weight * 100)}%
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Card>
      )}

      <Card title="Configure the session">
        <div className="space-y-5">
          <div>
            <div className="stat-label mb-2">Level</div>
            <div className="flex flex-wrap gap-2">
              {LEVELS.map((lvl) => (
                <button
                  key={lvl}
                  onClick={() => setLevel(lvl)}
                  className={cn(
                    'rounded-lg border px-3 py-1.5 text-sm capitalize transition-colors',
                    level === lvl
                      ? 'border-accent bg-accent/10 text-accent'
                      : 'border-forge-700 text-forge-300 hover:border-forge-600',
                  )}
                >
                  {lvl}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="stat-label mb-2">Mode</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {(
                [
                  ['standard', 'Standard', 'Think as long as you need.'],
                  ['pressure', 'Pressure', 'A clock per question, and it escalates regardless.'],
                ] as const
              ).map(([value, label, hint]) => (
                <button
                  key={value}
                  onClick={() => setMode(value)}
                  className={cn(
                    'rounded-lg border p-3 text-left transition-colors',
                    mode === value
                      ? 'border-accent bg-accent/10'
                      : 'border-forge-700 hover:border-forge-600',
                  )}
                >
                  <div className={cn('text-sm font-medium', mode === value ? 'text-accent' : 'text-forge-200')}>
                    {label}
                  </div>
                  <div className="mt-0.5 text-xs text-forge-500">{hint}</div>
                </button>
              ))}
            </div>
          </div>

          <div>
            <label htmlFor="qcount" className="stat-label mb-2 block">
              Questions: {count}
            </label>
            <input
              id="qcount"
              type="range"
              min={3}
              max={15}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              className="w-full accent-accent"
            />
          </div>

          <Button
            variant="primary"
            size="lg"
            className="w-full"
            loading={start.isPending}
            onClick={() => start.mutate()}
            icon={<Mic className="h-4 w-4" />}
          >
            Begin the interview
          </Button>
        </div>
      </Card>
    </div>
  );
}

// ── Live session ────────────────────────────────────────────────────────────
function InterviewRun({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient();
  const celebrate = useRewards((s) => s.celebrate);

  const [answer, setAnswer] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [confidence, setConfidence] = useState(0.6);
  const [feedback, setFeedback] = useState<InterviewFeedback | null>(null);
  const [turn, setTurn] = useState<InterviewTurn | null>(null);
  const [complete, setComplete] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const turnStarted = useRef(Date.now());

  const session = useQuery({
    queryKey: ['interview', sessionId],
    queryFn: () => api.interview.get(sessionId),
  });

  useEffect(() => {
    if (session.data && !turn && !complete) {
      setTurn(session.data.current_turn);
      turnStarted.current = Date.now();
      if (session.data.status !== 'in_progress') setComplete(true);
    }
  }, [session.data, turn, complete]);

  useEffect(() => {
    const timer = setInterval(() => setElapsed((Date.now() - turnStarted.current) / 1000), 1000);
    return () => clearInterval(timer);
  }, [turn]);

  const answerMutation = useMutation({
    mutationFn: () =>
      api.interview.answer(sessionId, {
        position: turn!.position,
        answer_text: answer,
        selected_option_ids: selected,
        elapsed_seconds: Math.round(elapsed),
        confidence,
      }),
    onSuccess: (response) => {
      setFeedback(response.feedback);
      celebrate(response.progression);
      queryClient.invalidateQueries({ queryKey: ['profile'] });
      if (response.session_complete) {
        setComplete(true);
        setTurn(null);
      } else if (response.next_turn) {
        // Hold the feedback on screen; the player advances deliberately.
        setTurn(response.next_turn);
      }
    },
  });

  function advance() {
    setFeedback(null);
    setAnswer('');
    setSelected([]);
    turnStarted.current = Date.now();
    setElapsed(0);
  }

  if (session.isLoading) return <LoadingPanel rows={8} className="mx-auto max-w-3xl" />;
  if (complete && !feedback) return <Report sessionId={sessionId} />;

  const pressure = session.data?.mode === 'pressure';
  const limit = turn?.time_limit_seconds ?? null;
  const overtime = limit !== null && elapsed > limit;

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Chip className="capitalize">{session.data?.level}</Chip>
          {pressure && (
            <span className="chip border-signal-danger/40 bg-signal-danger/10 text-signal-danger">
              Pressure
            </span>
          )}
          <span className="text-xs text-forge-500">
            Question {(turn?.position ?? 0) + 1} of ~{session.data?.planned_questions}
          </span>
        </div>
        {limit !== null && (
          <span
            className={cn(
              'flex items-center gap-1.5 font-mono text-sm tabular-nums',
              overtime ? 'animate-glitch text-signal-danger' : 'text-forge-300',
            )}
          >
            <Timer className="h-3.5 w-3.5" />
            {duration(Math.max(0, limit - elapsed))}
          </span>
        )}
      </div>

      <AnimatePresence mode="wait">
        {turn && !feedback && (
          <motion.div
            key={turn.position}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
          >
            <Card
              title={
                turn.is_followup ? (
                  <span className="flex items-center gap-2 text-signal-warn">
                    <CornerDownRight className="h-4 w-4" />
                    Follow-up
                  </span>
                ) : (
                  'Interviewer'
                )
              }
              subtitle={turn.category ? titleCase(turn.category) : undefined}
              actions={<TierChip tier={turn.tier} />}
            >
              <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-forge-100">
                {turn.prompt}
              </p>

              {turn.context && (
                <pre className="mt-3 overflow-x-auto rounded-lg border border-forge-700 bg-forge-950 p-3 font-mono text-xs text-forge-300">
                  {turn.context}
                </pre>
              )}

              {turn.options.length > 0 ? (
                <ul className="mt-4 space-y-2">
                  {turn.options.map((option) => (
                    <li key={option.id}>
                      <button
                        onClick={() =>
                          setSelected((prev) =>
                            prev.includes(option.id)
                              ? prev.filter((id) => id !== option.id)
                              : [...prev, option.id],
                          )
                        }
                        className={cn(
                          'w-full rounded-lg border p-3 text-left text-sm transition-colors',
                          selected.includes(option.id)
                            ? 'border-accent bg-accent/10 text-forge-100'
                            : 'border-forge-700 text-forge-300 hover:border-forge-600',
                        )}
                      >
                        <span className="mr-2 font-mono text-xs text-forge-500">{option.id}.</span>
                        {option.text}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <>
                  <textarea
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    rows={7}
                    autoFocus
                    placeholder="Structure it: what is the mechanism, what is the trade-off, and what breaks in production?"
                    className="mt-4 w-full rounded-lg border border-forge-700 bg-forge-950/70 px-3 py-2.5
                               text-sm leading-relaxed text-forge-100 placeholder:text-forge-600 focus:border-accent"
                  />
                  <div className="mt-2 flex items-center justify-between text-[11px] text-forge-600">
                    <span>{answer.trim().split(/\s+/).filter(Boolean).length} words</span>
                    <span>Naming the mechanism beats naming the pattern</span>
                  </div>
                </>
              )}

              <div className="mt-4 flex flex-wrap items-end gap-4">
                <div className="min-w-[180px] flex-1">
                  <label htmlFor="conf" className="mb-1 block text-xs text-forge-400">
                    Confidence ({Math.round(confidence * 100)}%)
                  </label>
                  <input
                    id="conf"
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
                  loading={answerMutation.isPending}
                  disabled={!answer.trim() && selected.length === 0}
                  onClick={() => answerMutation.mutate()}
                  icon={<Send className="h-3.5 w-3.5" />}
                >
                  Answer
                </Button>
              </div>
            </Card>
          </motion.div>
        )}

        {feedback && (
          <motion.div
            key="feedback"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <FeedbackCard
              feedback={feedback}
              onNext={complete ? undefined : advance}
              complete={complete}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function FeedbackCard({
  feedback,
  onNext,
  complete,
}: {
  feedback: InterviewFeedback;
  onNext?: () => void;
  complete: boolean;
}) {
  const scoreTone =
    feedback.score >= 7 ? 'text-signal-success' : feedback.score >= 5 ? 'text-signal-warn' : 'text-signal-danger';

  return (
    <Card
      title="Interviewer's read"
      actions={
        <span className={cn('font-display text-lg tabular-nums', scoreTone)}>
          {feedback.score.toFixed(1)}
          <span className="text-sm text-forge-500">/10</span>
        </span>
      }
    >
      <p className="text-[15px] italic leading-relaxed text-forge-200">
        &ldquo;{feedback.interviewer_reaction}&rdquo;
      </p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <div className="stat-label mb-2">Dimensions</div>
          <ul className="space-y-1.5">
            {Object.entries(feedback.dimension_scores).map(([dimension, value]) => (
              <li key={dimension} className="flex items-center gap-2">
                <span className="w-32 shrink-0 truncate text-xs text-forge-400">
                  {titleCase(dimension)}
                </span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-forge-800">
                  <motion.div
                    className="h-full rounded-full bg-accent"
                    initial={{ width: 0 }}
                    animate={{ width: `${value * 100}%` }}
                  />
                </div>
                <span className="w-8 shrink-0 text-right font-mono text-[11px] text-forge-500">
                  {Math.round(value * 100)}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-3">
          {feedback.missing_points.length > 0 && (
            <div>
              <div className="stat-label mb-1.5">What was missing</div>
              <ul className="space-y-1 text-xs text-forge-400">
                {feedback.missing_points.slice(0, 5).map((point, i) => (
                  <li key={i}>· {point}</li>
                ))}
              </ul>
            </div>
          )}
          {Object.entries(feedback.level_gap).map(([level, text]) => (
            <div
              key={level}
              className="rounded-lg border border-signal-xp/25 bg-signal-xp/5 px-3 py-2"
            >
              <div className="text-[10px] font-semibold uppercase tracking-widest text-signal-xp">
                A {level} answer
              </div>
              <p className="mt-0.5 text-xs leading-relaxed text-forge-300">{text}</p>
            </div>
          ))}
        </div>
      </div>

      {feedback.ideal_answer && (
        <details className="mt-4">
          <summary className="cursor-pointer text-xs text-accent hover:underline">
            Show the model answer
          </summary>
          <p className="mt-2 rounded-lg border border-forge-700 bg-forge-950/60 p-3 text-sm leading-relaxed text-forge-300">
            {feedback.ideal_answer}
          </p>
          {feedback.common_wrong_answer && (
            <p className="mt-2 text-xs text-forge-500">
              <strong className="text-forge-400">Common wrong answer:</strong>{' '}
              {feedback.common_wrong_answer}
            </p>
          )}
        </details>
      )}

      <div className="mt-5">
        {onNext ? (
          <Button variant="primary" onClick={onNext} icon={<ArrowRight className="h-4 w-4" />}>
            Next question
          </Button>
        ) : complete ? (
          <Button variant="primary" onClick={() => window.location.reload()}>
            See the debrief
          </Button>
        ) : null}
      </div>
    </Card>
  );
}

// ── Debrief ─────────────────────────────────────────────────────────────────
function Report({ sessionId }: { sessionId: string }) {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ['interview-report', sessionId],
    queryFn: () => api.interview.report(sessionId),
  });

  if (isLoading || !data) return <LoadingPanel rows={8} className="mx-auto max-w-3xl" />;

  const verdict = VERDICT_LABELS[data.verdict] ?? { label: data.verdict, className: 'text-forge-300' };
  const radar = Object.entries(data.dimension_scores).map(([dimension, value]) => ({
    dimension: titleCase(dimension).split(' ')[0],
    score: Math.round(value * 100),
  }));

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div className="text-center">
        <div className="stat-label">Debrief</div>
        <div className={cn('mt-1 font-display text-4xl font-bold', verdict.className)}>
          {verdict.label}
        </div>
        <div className="mt-1 font-mono text-lg tabular-nums text-forge-300">
          {data.overall_score.toFixed(1)} / 10
        </div>
      </div>

      <Card>
        <p className="text-sm leading-relaxed text-forge-200">{data.summary}</p>
      </Card>

      <div className="grid gap-5 md:grid-cols-2">
        <Card title="Dimension profile" padded={false}>
          <div className="h-64 p-3">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radar} outerRadius="70%">
                <PolarGrid stroke="#273154" />
                <PolarAngleAxis dataKey="dimension" tick={{ fill: '#8b99c4', fontSize: 10 }} />
                <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                <Radar dataKey="score" stroke="#22d3ee" fill="#22d3ee" fillOpacity={0.35} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <div className="space-y-4">
          <Card title="Strengths">
            {data.strengths.length ? (
              <ul className="space-y-1 text-sm text-signal-success">
                {data.strengths.map((s) => (
                  <li key={s}>· {s}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-forge-500">Nothing stood out yet.</p>
            )}
          </Card>
          <Card title="Gaps" subtitle="Where the next session should focus">
            <ul className="space-y-1 text-sm text-signal-warn">
              {data.gaps.map((g) => (
                <li key={g}>· {g}</li>
              ))}
            </ul>
            {data.recommended_concepts.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {data.recommended_concepts.slice(0, 6).map((slug) => (
                  <Chip key={slug} className="normal-case">
                    {slug}
                  </Chip>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>

      <Card title="Question by question">
        <ul className="space-y-3">
          {data.per_question.map((q) => (
            <li key={q.position} className="rounded-lg border border-forge-700 bg-forge-900/50 p-3">
              <div className="flex flex-wrap items-center gap-2">
                {q.is_followup && <CornerDownRight className="h-3.5 w-3.5 text-signal-warn" />}
                <TierChip tier={q.tier} />
                {q.category && <Chip className="normal-case">{titleCase(q.category)}</Chip>}
                <span className="ml-auto font-mono text-xs tabular-nums text-forge-400">
                  {q.score?.toFixed(1) ?? '—'}/10 · {duration(q.elapsed_seconds)}
                </span>
              </div>
              <p className="mt-2 text-sm text-forge-200">{q.prompt}</p>
              {q.reaction && <p className="mt-1.5 text-xs italic text-forge-500">{q.reaction}</p>}
              {q.missing_points.length > 0 && (
                <ul className="mt-1.5 space-y-0.5 text-[11px] text-forge-500">
                  {q.missing_points.slice(0, 3).map((point, i) => (
                    <li key={i}>missing: {point}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </Card>

      <div className="flex justify-center gap-3">
        <Button variant="primary" onClick={() => navigate('/app/interview')} icon={<Mic className="h-4 w-4" />}>
          Another round
        </Button>
        <Button variant="secondary" onClick={() => navigate('/app/analytics')} icon={<TrendingUp className="h-4 w-4" />}>
          See analytics
        </Button>
      </div>

      <Stat
        label="Interview readiness after this session"
        value={`${Math.round(data.interview_readiness * 100)}%`}
      />
    </div>
  );
}
