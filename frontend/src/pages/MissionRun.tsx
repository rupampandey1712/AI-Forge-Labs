/**
 * Running a mission: briefing → evidence → steps → debrief → journal.
 *
 * The evidence panel is what turns a "debugging mission" into an investigation.
 * Logs, metrics, a deploy history and a stack trace are given to the player the
 * way an on-call engineer receives them — unlabelled, and with the answer not
 * highlighted.
 */

import { AnimatePresence, motion } from 'framer-motion';
import { ArrowLeft, CheckCircle2, FileText, Send, Swords, XCircle } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiRequestError } from '@/lib/api';
import { Button, Card, LoadingPanel, Modal } from '@/components/ui';
import { KindChip, TierChip } from '@/components/game/bits';
import { useRewards } from '@/stores/game';
import { cn, titleCase } from '@/lib/utils';
import type { Grade, MissionCompletion, MissionStep } from '@/types/api';

export default function MissionRun() {
  const { slug = '' } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const celebrate = useRewards((s) => s.celebrate);

  const [started, setStarted] = useState(false);
  const [results, setResults] = useState<Record<number, Grade>>({});
  const [completion, setCompletion] = useState<MissionCompletion | null>(null);
  const [journalOpen, setJournalOpen] = useState(false);

  const mission = useQuery({
    queryKey: ['mission', slug],
    queryFn: () => api.missions.get(slug),
    enabled: !!slug,
  });

  const start = useMutation({
    mutationFn: () => api.missions.start(slug),
    onSuccess: () => {
      setStarted(true);
      queryClient.invalidateQueries({ queryKey: ['mission', slug] });
    },
  });

  const complete = useMutation({
    mutationFn: () => api.missions.complete(slug),
    onSuccess: (result) => {
      setCompletion(result);
      celebrate(result.progression);
      queryClient.invalidateQueries({ queryKey: ['profile'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['missions'] });
      setJournalOpen(true);
    },
  });

  if (mission.isLoading) return <LoadingPanel rows={8} className="mx-auto max-w-4xl" />;

  if (mission.isError) {
    const locked = mission.error instanceof ApiRequestError && mission.error.isLocked;
    return (
      <Card title={locked ? 'Not unlocked yet' : 'Mission unavailable'}>
        <p className="text-sm text-forge-400">
          {mission.error instanceof ApiRequestError ? mission.error.message : 'Unknown error.'}
        </p>
        <Button className="mt-4" onClick={() => navigate('/app/missions')}>
          Back to missions
        </Button>
      </Card>
    );
  }

  const data = mission.data!;
  const isRunning = started || !!data.attempt_id;
  const requiredDone = data.steps
    .filter((s) => s.required)
    .every((s) => results[s.position] || s.status !== 'pending');

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div>
        <Link to="/app/missions" className="mb-1 inline-flex items-center gap-1 text-xs text-forge-400 hover:text-forge-200">
          <ArrowLeft className="h-3 w-3" /> Missions
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <KindChip kind={data.kind} />
          <TierChip tier={data.tier} showLabel />
          {data.is_boss && (
            <span className="chip border-signal-warn/50 bg-signal-warn/10 text-signal-warn">Boss</span>
          )}
        </div>
        <h1 className="mt-2 font-display text-2xl font-semibold tracking-tight">{data.title}</h1>
      </div>

      <Card title="Briefing" accent={data.is_boss ? '#fbbf24' : undefined}>
        <div className="prose-forge whitespace-pre-wrap text-sm">{data.briefing.trim()}</div>
        {data.success_criteria.length > 0 && (
          <div className="mt-4 rounded-lg border border-forge-700 bg-forge-950/50 p-3">
            <div className="stat-label mb-2">Success criteria</div>
            <ul className="space-y-1 text-sm text-forge-300">
              {data.success_criteria.map((criterion, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-forge-600">▸</span>
                  {criterion}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      {Object.keys(data.artifacts).length > 0 && <EvidencePanel artifacts={data.artifacts} />}

      {!isRunning ? (
        <Button
          variant="primary"
          size="lg"
          className="w-full"
          loading={start.isPending}
          onClick={() => start.mutate()}
          icon={<Swords className="h-4 w-4" />}
        >
          Accept the mission
        </Button>
      ) : (
        <div className="space-y-4">
          {data.steps.map((step) => (
            <StepCard
              key={step.position}
              slug={slug}
              step={step}
              result={results[step.position]}
              onResult={(grade) => setResults((prev) => ({ ...prev, [step.position]: grade }))}
            />
          ))}

          <Button
            variant="primary"
            size="lg"
            className="w-full"
            disabled={!requiredDone}
            loading={complete.isPending}
            onClick={() => complete.mutate()}
          >
            {requiredDone ? 'Complete mission' : 'Finish the required steps first'}
          </Button>
          {complete.isError && (
            <p className="text-center text-sm text-signal-danger">
              {complete.error instanceof ApiRequestError ? complete.error.message : 'Could not complete.'}
            </p>
          )}
        </div>
      )}

      <AnimatePresence>
        {completion && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <Card
              title={completion.passed ? '✅ Mission complete' : 'Mission closed'}
              subtitle={`Score ${(completion.score * 100).toFixed(0)}% · +${completion.progression.xp_gained} XP`}
              accent={completion.passed ? '#34d399' : '#fbbf24'}
            >
              <div className="prose-forge whitespace-pre-wrap text-sm">{completion.debrief.trim()}</div>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>

      <JournalModal
        open={journalOpen}
        onClose={() => setJournalOpen(false)}
        contextSlug={slug}
        concepts={data.concept_slugs}
        prompts={completion?.journal_prompt ?? {}}
      />
    </div>
  );
}

function EvidencePanel({ artifacts }: { artifacts: Record<string, unknown> }) {
  return (
    <Card title="Evidence" subtitle="What you would actually have at 3am" accent="#f43f5e">
      <div className="space-y-3">
        {Object.entries(artifacts).map(([key, value]) => (
          <div key={key}>
            <div className="stat-label mb-1.5">{key.replace(/_/g, ' ')}</div>
            {Array.isArray(value) ? (
              <pre className="overflow-x-auto rounded-lg border border-forge-700 bg-forge-950 p-3 font-mono text-[11px] leading-relaxed text-forge-300">
                {value.map(String).join('\n')}
              </pre>
            ) : typeof value === 'string' ? (
              <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg border border-forge-700 bg-forge-950 p-3 font-mono text-[11px] leading-relaxed text-forge-300">
                {value}
              </pre>
            ) : (
              <pre className="overflow-x-auto rounded-lg border border-forge-700 bg-forge-950 p-3 font-mono text-[11px] text-forge-300">
                {JSON.stringify(value, null, 2)}
              </pre>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

function StepCard({
  slug,
  step,
  result,
  onResult,
}: {
  slug: string;
  step: MissionStep;
  result?: Grade;
  onResult: (grade: Grade) => void;
}) {
  const [text, setText] = useState('');
  const [selected, setSelected] = useState<string[]>([]);

  const question = useQuery({
    queryKey: ['question', step.question_slug],
    queryFn: () => api.questions.get(step.question_slug!),
    enabled: step.step_type === 'question' && !!step.question_slug,
  });

  const submit = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = { position: step.position };
      if (step.step_type === 'question') {
        payload.question = { answer_text: text, selected_option_ids: selected };
      } else {
        payload.free_text = text;
      }
      return api.missions.submitStep(slug, payload);
    },
    onSuccess: onResult,
  });

  const done = result ?? (step.status !== 'pending' ? undefined : undefined);
  const passed = result?.passed ?? step.status === 'passed';

  // A challenge step hands off to the full workbench — a cramped editor inside
  // a mission card would be strictly worse than the dedicated screen.
  if (step.step_type === 'challenge' && step.challenge_slug) {
    return (
      <Card
        title={
          <span className="flex items-center gap-2">
            {passed ? (
              <CheckCircle2 className="h-4 w-4 text-signal-success" />
            ) : (
              <span className="font-mono text-xs text-forge-500">{step.position + 1}</span>
            )}
            {step.title || 'Code'}
          </span>
        }
        subtitle={step.prompt || undefined}
      >
        <Link to={`/app/challenge/${step.challenge_slug}`}>
          <Button variant={passed ? 'secondary' : 'primary'}>
            {passed ? 'Revisit the workbench' : 'Open the workbench'}
          </Button>
        </Link>
        {passed && (
          <p className="mt-2 text-xs text-signal-success">
            Cleared{result ? ` — ${(result.score * 100).toFixed(0)}%` : ''}
          </p>
        )}
      </Card>
    );
  }

  if (step.step_type === 'journal') return null;

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          {passed ? (
            <CheckCircle2 className="h-4 w-4 text-signal-success" />
          ) : done ? (
            <XCircle className="h-4 w-4 text-signal-warn" />
          ) : (
            <span className="font-mono text-xs text-forge-500">{step.position + 1}</span>
          )}
          {step.title || titleCase(step.step_type)}
        </span>
      }
      subtitle={!step.required ? 'Optional' : undefined}
    >
      {step.prompt && <p className="mb-3 text-sm leading-relaxed text-forge-200">{step.prompt}</p>}

      {question.data && (
        <>
          <p className="mb-3 whitespace-pre-wrap text-sm leading-relaxed text-forge-100">
            {question.data.prompt}
          </p>
          {question.data.context && (
            <pre className="mb-3 overflow-x-auto rounded-lg border border-forge-700 bg-forge-950 p-3 font-mono text-xs text-forge-300">
              {question.data.context}
            </pre>
          )}
          {question.data.options.length > 0 && (
            <ul className="mb-3 space-y-2">
              {question.data.options.map((option) => (
                <li key={option.id}>
                  <button
                    onClick={() =>
                      setSelected((prev) =>
                        prev.includes(option.id) ? prev.filter((id) => id !== option.id) : [...prev, option.id],
                      )
                    }
                    className={cn(
                      'w-full rounded-lg border p-2.5 text-left text-sm transition-colors',
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
          )}
        </>
      )}

      {(!question.data || question.data.options.length === 0) && (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={5}
          placeholder="Mechanism, trade-off, failure mode. Specifics beat vocabulary."
          className="mb-3 w-full rounded-lg border border-forge-700 bg-forge-950/70 px-3 py-2 text-sm
                     leading-relaxed text-forge-100 placeholder:text-forge-600 focus:border-accent"
        />
      )}

      <Button
        variant="primary"
        size="sm"
        loading={submit.isPending}
        disabled={!text.trim() && selected.length === 0}
        onClick={() => submit.mutate()}
        icon={<Send className="h-3.5 w-3.5" />}
      >
        Submit
      </Button>

      {result && (
        <div
          className={cn(
            'mt-3 rounded-lg border p-3',
            result.passed
              ? 'border-signal-success/30 bg-signal-success/5'
              : 'border-signal-warn/30 bg-signal-warn/5',
          )}
        >
          <div className="text-sm font-medium text-forge-100">{result.headline}</div>
          {result.what_happened && (
            <p className="mt-1 text-xs leading-relaxed text-forge-300">{result.what_happened}</p>
          )}
          {result.missing_points.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-xs text-forge-500">
              {result.missing_points.map((point, i) => (
                <li key={i}>missing: {point}</li>
              ))}
            </ul>
          )}
          {result.solution && !result.passed && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-accent">Model answer</summary>
              <p className="mt-1 text-xs leading-relaxed text-forge-300">{result.solution}</p>
            </details>
          )}
        </div>
      )}
    </Card>
  );
}

function JournalModal({
  open,
  onClose,
  contextSlug,
  concepts,
  prompts,
}: {
  open: boolean;
  onClose: () => void;
  contextSlug: string;
  concepts: string[];
  prompts: Record<string, string>;
}) {
  const [learned, setLearned] = useState('');
  const [mistake, setMistake] = useState('');
  const [differently, setDifferently] = useState('');

  const save = useMutation({
    mutationFn: () =>
      api.journal.add({
        what_i_learned: learned,
        mistake_made: mistake,
        would_do_differently: differently,
        context_slug: contextSlug,
        concept_slugs: concepts,
      }),
    onSuccess: onClose,
  });

  return (
    <Modal open={open} onClose={onClose} title="Engineering journal" size="md">
      <p className="mb-4 text-sm leading-relaxed text-forge-400">
        Three questions, thirty seconds. Months from now the game will replay this back to you next
        to a challenge on the same concept — which is when it becomes useful.
      </p>
      <div className="space-y-3">
        {(
          [
            ['what_i_learned', learned, setLearned],
            ['mistake_made', mistake, setMistake],
            ['would_do_differently', differently, setDifferently],
          ] as const
        ).map(([key, value, setter]) => (
          <div key={key}>
            <label className="mb-1 block text-xs text-forge-300">
              {prompts[key] ?? titleCase(key)}
            </label>
            <textarea
              value={value}
              onChange={(e) => setter(e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-forge-700 bg-forge-950/70 px-3 py-2 text-sm
                         text-forge-100 placeholder:text-forge-600 focus:border-accent"
            />
          </div>
        ))}
      </div>
      <div className="mt-4 flex gap-2">
        <Button
          variant="primary"
          loading={save.isPending}
          onClick={() => save.mutate()}
          icon={<FileText className="h-3.5 w-3.5" />}
        >
          Save entry
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Skip
        </Button>
      </div>
    </Modal>
  );
}
