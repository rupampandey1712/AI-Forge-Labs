/**
 * Free practice: pick a challenge, or answer a random question.
 *
 * This is the "I have ten minutes" surface — no mission wrapper, no
 * commitment. It still feeds the retention engine, because a practice mode
 * that did not would quietly make the memory model wrong.
 */

import { CheckCircle2, Dices, Send, Zap } from 'lucide-react';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button, Card, Chip, EmptyState, LoadingPanel } from '@/components/ui';
import { Stagger, StaggerItem, TierChip } from '@/components/game/bits';
import { useRewards } from '@/stores/game';
import { cn, duration, titleCase } from '@/lib/utils';
import type { Grade, Question } from '@/types/api';

export default function Practice() {
  const [params] = useSearchParams();
  const [tier, setTier] = useState<number | undefined>();
  const [category, setCategory] = useState<string | undefined>();

  const challenges = useQuery({
    queryKey: ['challenges', category, tier],
    queryFn: () => api.challenges.list({ category, tier, page_size: 40 }),
  });
  const skills = useQuery({ queryKey: ['skills'], queryFn: api.player.skills });

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">Practice</h1>
        <p className="mt-1 text-sm text-forge-400">
          Everything here still updates your memory model — there is no off-the-record mode.
        </p>
      </div>

      <QuestionDrill initialSlug={params.get('question') ?? undefined} />

      <Card title="Coding challenges" subtitle={`${challenges.data?.total ?? 0} available`}>
        <div className="mb-3 flex flex-wrap gap-1.5">
          <FilterChip active={!tier} onClick={() => setTier(undefined)}>
            All tiers
          </FilterChip>
          {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((t) => (
            <FilterChip key={t} active={tier === t} onClick={() => setTier(t)}>
              T{t}
            </FilterChip>
          ))}
        </div>

        <div className="mb-4 flex flex-wrap gap-1.5">
          <FilterChip active={!category} onClick={() => setCategory(undefined)}>
            All areas
          </FilterChip>
          {[...new Set((skills.data ?? []).map((s) => s.skill_slug))].slice(0, 10).map((slug) => (
            <FilterChip key={slug} active={category === slug} onClick={() => setCategory(slug)}>
              {titleCase(slug)}
            </FilterChip>
          ))}
        </div>

        {challenges.isLoading ? (
          <LoadingPanel rows={4} className="border-0 bg-transparent p-0 shadow-none" />
        ) : challenges.data?.items.length === 0 ? (
          <EmptyState
            icon={<Zap className="h-7 w-7" />}
            title="No challenges match"
            description="Loosen the filters, or seed more content packs."
          />
        ) : (
          <Stagger as="ul" delay={0.03} className="grid list-none gap-2 sm:grid-cols-2">
            {challenges.data?.items.map((challenge) => (
              <StaggerItem as="li" key={challenge.slug} interactive>
                <Link
                  to={`/app/challenge/${challenge.slug}`}
                  className={cn(
                    'panel panel-hover flex items-start gap-3 p-3',
                    challenge.solved && 'border-signal-success/30',
                  )}
                >
                  <div className="mt-0.5 shrink-0">
                    {challenge.solved ? (
                      <CheckCircle2 className="h-4 w-4 text-signal-success" />
                    ) : (
                      <Zap className="h-4 w-4 text-forge-500" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-forge-100">
                      {challenge.title}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <TierChip tier={challenge.tier} />
                      <Chip className="normal-case tracking-normal">
                        {titleCase(challenge.category)}
                      </Chip>
                      <span className="text-[11px] text-forge-500">
                        par {duration(challenge.par_seconds)}
                      </span>
                    </div>
                  </div>
                </Link>
              </StaggerItem>
            ))}
          </Stagger>
        )}
      </Card>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button onClick={onClick} className="focus:outline-none">
      <span
        className={cn(
          'chip normal-case tracking-normal',
          active
            ? 'border-accent bg-accent/10 text-accent'
            : 'border-forge-600 bg-forge-800 text-forge-300 hover:text-forge-100',
        )}
      >
        {children}
      </span>
    </button>
  );
}

function QuestionDrill({ initialSlug }: { initialSlug?: string }) {
  const celebrate = useRewards((s) => s.celebrate);
  const [question, setQuestion] = useState<Question | null>(null);
  const [answer, setAnswer] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [grade, setGrade] = useState<Grade | null>(null);

  useQuery({
    queryKey: ['seed-question', initialSlug],
    queryFn: async () => {
      const seeded = await api.questions.get(initialSlug!);
      setQuestion(seeded);
      return seeded;
    },
    enabled: !!initialSlug && !question,
  });

  const draw = useMutation({
    mutationFn: () => api.questions.random({}),
    onSuccess: (next) => {
      setQuestion(next);
      setAnswer('');
      setSelected([]);
      setGrade(null);
    },
  });

  const submit = useMutation({
    mutationFn: () =>
      api.questions.submit(question!.slug, {
        answer_text: answer,
        selected_option_ids: selected,
      }),
    onSuccess: (result) => {
      setGrade(result);
      celebrate(result.progression);
    },
  });

  return (
    <Card
      title="Question drill"
      subtitle="Never repeats a question you answered in the last 45 days"
      actions={
        <Button
          size="sm"
          variant="secondary"
          loading={draw.isPending}
          onClick={() => draw.mutate()}
          icon={<Dices className="h-3.5 w-3.5" />}
        >
          {question ? 'Another' : 'Draw one'}
        </Button>
      }
    >
      {!question ? (
        <p className="text-sm text-forge-500">Draw a question to warm up.</p>
      ) : (
        <>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <TierChip tier={question.tier} showLabel />
            <Chip className="normal-case tracking-normal">{titleCase(question.category)}</Chip>
            <Chip className="capitalize">{question.interview_level}</Chip>
          </div>

          <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-forge-100">
            {question.prompt}
          </p>

          {question.context && (
            <pre className="mt-3 overflow-x-auto rounded-lg border border-forge-700 bg-forge-950 p-3 font-mono text-xs text-forge-300">
              {question.context}
            </pre>
          )}

          {question.options.length > 0 ? (
            <ul className="mt-3 space-y-2">
              {question.options.map((option) => (
                <li key={option.id}>
                  <button
                    disabled={!!grade}
                    onClick={() =>
                      setSelected((prev) =>
                        prev.includes(option.id)
                          ? prev.filter((id) => id !== option.id)
                          : [...prev, option.id],
                      )
                    }
                    className={cn(
                      'w-full rounded-lg border p-2.5 text-left text-sm transition-colors disabled:opacity-70',
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
            <textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              rows={5}
              disabled={!!grade}
              placeholder="Mechanism, trade-off, failure mode. Specifics beat vocabulary."
              className="mt-3 w-full rounded-lg border border-forge-700 bg-forge-950/70 px-3 py-2
                         text-sm leading-relaxed text-forge-100 placeholder:text-forge-600 focus:border-accent"
            />
          )}

          {!grade && (
            <Button
              className="mt-3"
              variant="primary"
              size="sm"
              loading={submit.isPending}
              disabled={!answer.trim() && selected.length === 0}
              onClick={() => submit.mutate()}
              icon={<Send className="h-3.5 w-3.5" />}
            >
              Answer
            </Button>
          )}

          {grade && (
            <div
              className={cn(
                'mt-3 rounded-lg border p-3',
                grade.passed
                  ? 'border-signal-success/30 bg-signal-success/5'
                  : 'border-signal-warn/30 bg-signal-warn/5',
              )}
            >
              <div className="text-sm font-medium text-forge-100">{grade.headline}</div>
              <p className="mt-1 text-sm leading-relaxed text-forge-300">{grade.what_happened}</p>
              {grade.missing_points.length > 0 && (
                <ul className="mt-2 space-y-0.5 text-xs text-forge-500">
                  {grade.missing_points.map((point, i) => (
                    <li key={i}>missing: {point}</li>
                  ))}
                </ul>
              )}
              {grade.solution && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-accent">
                    What a senior answer says
                  </summary>
                  <p className="mt-1 text-xs leading-relaxed text-forge-300">{grade.solution}</p>
                </details>
              )}
            </div>
          )}
        </>
      )}
    </Card>
  );
}
