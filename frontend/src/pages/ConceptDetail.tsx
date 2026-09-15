/**
 * A concept page.
 *
 * Follows the spec §53 teaching order: concept → example → common mistakes →
 * real-world usage → the graph it sits in → what to do about it. The knowledge
 * graph panel matters most: seeing that `generators` requires `iterators` and
 * leads to `context managers` is what turns a list of topics into a map.
 */

import { ArrowLeft, ArrowRight, BookOpen, Lightbulb, Link2, Zap } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button, Card, Chip, LoadingPanel } from '@/components/ui';
import { MasteryBar, SeverityChip } from '@/components/game/bits';
import { cn, titleCase } from '@/lib/utils';
import type { ConceptSummary } from '@/types/api';

export default function ConceptDetail() {
  const { slug = '' } = useParams();
  const { data, isLoading, isError } = useQuery({
    queryKey: ['concept', slug],
    queryFn: () => api.concepts.get(slug),
    enabled: !!slug,
  });

  if (isLoading) return <LoadingPanel rows={10} className="mx-auto max-w-4xl" />;
  if (isError || !data) {
    return (
      <Card title="Concept not found">
        <Link to="/app/concepts">
          <Button className="mt-2">Back to the codex</Button>
        </Link>
      </Card>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div>
        <Link
          to="/app/concepts"
          className="mb-1 inline-flex items-center gap-1 text-xs text-forge-400 hover:text-forge-200"
        >
          <ArrowLeft className="h-3 w-3" /> Codex
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <Chip className="normal-case tracking-normal">{titleCase(data.category)}</Chip>
          <span className="chip border-forge-600 bg-forge-800 text-forge-400">
            difficulty {data.base_difficulty}
          </span>
          {data.decayed && (
            <span className="chip border-signal-decay/40 bg-signal-decay/10 text-signal-decay">
              Fading
            </span>
          )}
          <span className="text-[11px] text-forge-500">{data.estimated_minutes} min read</span>
        </div>
        <h1 className="mt-2 font-display text-2xl font-semibold tracking-tight">{data.title}</h1>
        <p className="mt-1.5 text-[15px] leading-relaxed text-forge-300">{data.summary}</p>
      </div>

      {data.mastery > 0 && (
        <Card>
          <MasteryBar
            label="Your mastery"
            mastery={data.mastery}
            effective={data.effective_mastery}
          />
          {data.decayed && (
            <p className="mt-2 text-xs text-signal-decay">
              This has decayed since you last practised it. A review now is worth far more than a
              first read.
            </p>
          )}
        </Card>
      )}

      <Card title="The mechanism">
        <div className="prose-forge whitespace-pre-wrap">{data.explanation}</div>
      </Card>

      {data.examples.length > 0 && (
        <Card title="Worked examples">
          <div className="space-y-4">
            {data.examples.map((example, i) => (
              <div key={i}>
                <h3 className="mb-1.5 font-display text-sm font-semibold text-forge-100">
                  {example.title}
                </h3>
                <pre className="overflow-x-auto rounded-lg border border-forge-700 bg-forge-950 p-3.5 font-mono text-[13px] leading-relaxed text-forge-200">
                  {example.code}
                </pre>
                {example.output && (
                  <pre className="mt-1.5 overflow-x-auto rounded-lg border border-forge-700/60 bg-forge-900/60 p-2.5 font-mono text-[12px] text-signal-success">
                    {example.output}
                  </pre>
                )}
                {example.note && (
                  <p className="mt-1.5 flex gap-2 text-xs leading-relaxed text-forge-400">
                    <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-signal-warn" />
                    {example.note}
                  </p>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {data.common_mistakes.length > 0 && (
        <Card title="Common mistakes" subtitle="Half the lesson is knowing how this goes wrong">
          <ul className="space-y-3">
            {data.common_mistakes.map((mistake, i) => (
              <li key={i} className="rounded-lg border border-forge-700 bg-forge-900/50 p-3.5">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityChip severity={mistake.severity} />
                  <span className="text-sm font-medium text-forge-100">{mistake.mistake}</span>
                </div>
                <p className="mt-1.5 text-sm leading-relaxed text-forge-400">{mistake.why}</p>
                <p className="mt-1.5 text-sm leading-relaxed text-signal-success">
                  → {mistake.fix}
                </p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {data.real_world_usage.length > 0 && (
        <Card title="Where this bites in production">
          <ul className="space-y-1.5 text-sm text-forge-300">
            {data.real_world_usage.map((usage, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-forge-600">▸</span>
                {usage}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {(data.prerequisites.length > 0 || data.leads_to.length > 0 || data.related.length > 0) && (
        <Card
          title="Knowledge graph"
          subtitle="What this needs, and what it opens up"
          actions={<Link2 className="h-4 w-4 text-forge-500" />}
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <GraphColumn title="Requires" concepts={data.prerequisites} tone="text-signal-warn" />
            <GraphColumn title="Leads to" concepts={data.leads_to} tone="text-accent" />
            <GraphColumn title="Related" concepts={data.related} tone="text-forge-300" />
          </div>
        </Card>
      )}

      {data.challenge_slugs.length > 0 && (
        <Card title="Practise it" subtitle="Reading is not learning">
          <div className="flex flex-wrap gap-2">
            {data.challenge_slugs.slice(0, 8).map((challengeSlug) => (
              <Link key={challengeSlug} to={`/app/challenge/${challengeSlug}`}>
                <Button size="sm" variant="secondary" icon={<Zap className="h-3.5 w-3.5" />}>
                  {challengeSlug.replace(/^py-/, '').replace(/-/g, ' ')}
                </Button>
              </Link>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function GraphColumn({
  title,
  concepts,
  tone,
}: {
  title: string;
  concepts: ConceptSummary[];
  tone: string;
}) {
  return (
    <div>
      <div className={cn('stat-label mb-2', tone)}>{title}</div>
      {concepts.length === 0 ? (
        <p className="text-xs text-forge-600">—</p>
      ) : (
        <ul className="space-y-1.5">
          {concepts.map((concept) => (
            <li key={concept.slug}>
              <Link
                to={`/app/concepts/${concept.slug}`}
                className="group flex items-center gap-1.5 text-sm text-forge-300 hover:text-accent"
              >
                <BookOpen className="h-3 w-3 shrink-0 opacity-60" />
                <span className="truncate">{concept.title}</span>
                <ArrowRight className="h-3 w-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-60" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
