import { BookOpen, Search } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Card, Chip, EmptyState, LoadingPanel } from '@/components/ui';
import { MasteryBar, Stagger, StaggerItem } from '@/components/game/bits';
import { cn, titleCase } from '@/lib/utils';

export default function Concepts() {
  const [search, setSearch] = useState('');
  const [skill, setSkill] = useState<string | undefined>();

  const concepts = useQuery({
    queryKey: ['concepts', search, skill],
    queryFn: () => api.concepts.list({ search: search || undefined, skill_slug: skill, page_size: 60 }),
  });
  const skills = useQuery({ queryKey: ['skills'], queryFn: api.player.skills });

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">Codex</h1>
        <p className="mt-1 text-sm text-forge-400">
          Every concept the game tracks, with your current mastery and whether it is fading.
        </p>
      </div>

      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-forge-500" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search concepts…"
          className="w-full rounded-lg border border-forge-700 bg-forge-950/70 py-2.5 pl-9 pr-3 text-sm
                     text-forge-100 placeholder:text-forge-600 focus:border-accent"
        />
      </div>

      <div className="flex flex-wrap gap-1.5">
        <button onClick={() => setSkill(undefined)} className="focus:outline-none">
          <span
            className={cn(
              'chip normal-case tracking-normal',
              !skill ? 'border-accent bg-accent/10 text-accent' : 'border-forge-600 bg-forge-800 text-forge-300',
            )}
          >
            All skills
          </span>
        </button>
        {(skills.data ?? [])
          .filter((s) => s.concepts_total > 0)
          .map((s) => (
            <button key={s.skill_slug} onClick={() => setSkill(s.skill_slug)} className="focus:outline-none">
              <span
                className={cn(
                  'chip normal-case tracking-normal',
                  skill === s.skill_slug
                    ? 'border-accent bg-accent/10 text-accent'
                    : 'border-forge-600 bg-forge-800 text-forge-300',
                )}
              >
                {s.name}
                <span className="text-forge-500">{s.concepts_total}</span>
              </span>
            </button>
          ))}
      </div>

      {concepts.isLoading ? (
        <LoadingPanel rows={6} />
      ) : concepts.data?.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<BookOpen className="h-8 w-8" />}
            title="Nothing found"
            description="Try a different search, or seed more content packs."
          />
        </Card>
      ) : (
        <Stagger as="ul" className="grid list-none gap-3 md:grid-cols-2">
          {concepts.data?.items.map((concept) => (
            <StaggerItem as="li" key={concept.slug} interactive>
            <Link
              to={`/app/concepts/${concept.slug}`}
              className={cn(
                'panel panel-hover p-4',
                concept.decayed && 'border-signal-decay/40',
              )}
            >
              <div className="flex flex-wrap items-center gap-2">
                <Chip className="normal-case tracking-normal">{titleCase(concept.category)}</Chip>
                <span className="chip border-forge-600 bg-forge-800 text-forge-400">
                  d{concept.base_difficulty}
                </span>
                {concept.decayed && (
                  <span className="chip border-signal-decay/40 bg-signal-decay/10 text-signal-decay">
                    Fading
                  </span>
                )}
                {concept.due && !concept.decayed && (
                  <span className="chip border-signal-warn/40 bg-signal-warn/10 text-signal-warn">
                    Due
                  </span>
                )}
                <span className="ml-auto text-[11px] text-forge-500">
                  {concept.estimated_minutes}m
                </span>
              </div>

              <h3 className="mt-2 font-display text-base font-semibold text-forge-100">
                {concept.title}
              </h3>
              <p className="mt-1 line-clamp-2 text-sm leading-relaxed text-forge-400">
                {concept.summary}
              </p>

              {concept.mastery > 0 && (
                <MasteryBar
                  className="mt-3"
                  mastery={concept.mastery}
                  effective={concept.effective_mastery}
                />
              )}
            </Link>
            </StaggerItem>
          ))}
        </Stagger>
      )}
    </div>
  );
}
