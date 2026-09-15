/**
 * Skill trees.
 *
 * The tree is rendered as indented tiers rather than a force-directed graph:
 * a Python tree has 20 nodes with real dependency order, and a spring layout
 * would make that order *less* legible while looking more impressive. The
 * indentation IS the prerequisite chain.
 */

import { motion } from 'framer-motion';
import { ChevronRight, Lock } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Card, Chip, LoadingPanel, Stat } from '@/components/ui';
import { MasteryBar } from '@/components/game/bits';
import { cn, pct, relativeTime, TIER_LABELS, titleCase } from '@/lib/utils';
import type { SkillNode } from '@/types/api';

export default function Skills() {
  const { slug } = useParams();
  return slug ? <SkillTreeView slug={slug} /> : <SkillOverview />;
}

function SkillOverview() {
  const { data, isLoading } = useQuery({ queryKey: ['skills'], queryFn: api.player.skills });

  if (isLoading || !data) return <LoadingPanel rows={8} className="mx-auto max-w-5xl" />;

  const practised = data.filter((s) => s.attempts > 0);
  const untouched = data.filter((s) => s.attempts === 0);

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">Skill Trees</h1>
        <p className="mt-1 text-sm text-forge-400">
          Sixteen attributes, 113 nodes. The solid bar is where you are today; the ghost behind it
          is the peak you reached.
        </p>
      </div>

      {practised.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {practised
            .slice()
            .sort((a, b) => b.effective_mastery - a.effective_mastery)
            .map((skill) => (
              <Link key={skill.skill_slug} to={`/app/skills/${skill.skill_slug}`} className="panel panel-hover p-4">
                <div className="flex items-center gap-2">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: skill.color }}
                  />
                  <span className="font-display text-base font-semibold text-forge-100">
                    {skill.name}
                  </span>
                  <span className="ml-auto font-mono text-xs text-forge-500">
                    lvl {skill.level}
                  </span>
                </div>

                <MasteryBar
                  className="mt-3"
                  mastery={skill.mastery}
                  effective={skill.effective_mastery}
                />

                <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[11px] text-forge-500">
                  <span>
                    {skill.concepts_started}/{skill.concepts_total} concepts
                  </span>
                  <span>·</span>
                  <span>{pct(skill.accuracy)} accuracy</span>
                  <span>·</span>
                  <span>
                    deepest tier {skill.highest_tier_cleared}
                    {skill.highest_tier_cleared > 0 && (
                      <span className="text-forge-600"> ({TIER_LABELS[skill.highest_tier_cleared]})</span>
                    )}
                  </span>
                  {skill.concepts_due > 0 && (
                    <span className="ml-auto text-signal-warn">{skill.concepts_due} due</span>
                  )}
                </div>
              </Link>
            ))}
        </div>
      )}

      {untouched.length > 0 && (
        <Card title="Not started" subtitle="Unlocked by progressing through the world map">
          <div className="flex flex-wrap gap-2">
            {untouched.map((skill) => (
              <Link
                key={skill.skill_slug}
                to={`/app/skills/${skill.skill_slug}`}
                className="chip border-forge-600 bg-forge-800 text-forge-400 normal-case tracking-normal hover:text-forge-200"
              >
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ backgroundColor: skill.color }}
                />
                {skill.name}
                <span className="text-forge-600">{skill.concepts_total}</span>
              </Link>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function SkillTreeView({ slug }: { slug: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['skill-tree', slug],
    queryFn: () => api.player.skillTree(slug),
  });

  if (isLoading || !data) return <LoadingPanel rows={10} className="mx-auto max-w-4xl" />;

  // Depth = length of the parent chain, computed once.
  const byslug = new Map(data.nodes.map((n) => [n.slug, n]));
  const depthOf = (node: SkillNode): number => {
    let depth = 0;
    let current: SkillNode | undefined = node;
    while (current?.parent_slug) {
      current = byslug.get(current.parent_slug);
      depth += 1;
      if (depth > 8) break; // defensive: a cycle in content must not hang the UI
    }
    return depth;
  };

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div>
        <Link to="/app/skills" className="mb-1 inline-block text-xs text-forge-400 hover:text-forge-200">
          ← All skills
        </Link>
        <div className="flex items-center gap-2.5">
          <span className="h-3 w-3 rounded-full" style={{ backgroundColor: data.color }} />
          <h1 className="font-display text-2xl font-semibold tracking-tight">{data.name}</h1>
        </div>
        <p className="mt-1 text-sm text-forge-400">{data.description}</p>
      </div>

      {data.progress && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Mastery" value={pct(data.progress.effective_mastery)} accent={data.color} />
          <Stat label="Skill level" value={data.progress.level} hint={`${data.progress.xp} XP`} />
          <Stat
            label="Deepest tier"
            value={data.progress.highest_tier_cleared || '—'}
            hint={TIER_LABELS[data.progress.highest_tier_cleared] ?? 'Not started'}
          />
          <Stat
            label="Last practised"
            value={<span className="text-lg">{relativeTime(data.progress.last_practiced_at)}</span>}
            accent={data.progress.forgetting_score > 0.1 ? '#fb923c' : undefined}
          />
        </div>
      )}

      <Card title="Tree" subtitle="Indentation is the prerequisite chain">
        <ul className="space-y-1.5">
          {data.nodes.map((node, i) => {
            const depth = depthOf(node);
            return (
              <motion.li
                key={node.slug}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.02 }}
                style={{ marginLeft: depth * 20 }}
              >
                <Link
                  to={`/app/concepts?node=${node.slug}`}
                  className={cn(
                    'flex items-center gap-3 rounded-lg border px-3 py-2.5 transition-colors',
                    node.unlocked
                      ? 'border-forge-700 bg-forge-900/50 hover:border-forge-600'
                      : 'border-forge-800 bg-forge-900/30 opacity-55',
                  )}
                >
                  {depth > 0 && <ChevronRight className="h-3 w-3 shrink-0 text-forge-600" />}
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{
                      backgroundColor: node.mastery > 0 ? data.color : '#3a4670',
                      opacity: node.mastery > 0 ? 0.4 + node.mastery * 0.6 : 1,
                    }}
                  />

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-forge-100">
                        {node.name}
                      </span>
                      {!node.unlocked && <Lock className="h-3 w-3 shrink-0 text-forge-600" />}
                    </div>
                    <p className="truncate text-xs text-forge-500">{node.summary}</p>
                  </div>

                  <div className="shrink-0 text-right">
                    <div className="font-mono text-xs tabular-nums" style={{ color: data.color }}>
                      {node.concepts_total > 0 ? pct(node.mastery) : '—'}
                    </div>
                    <div className="text-[10px] text-forge-600">
                      {node.concepts_mastered}/{node.concepts_total}
                    </div>
                  </div>

                  <Chip className="shrink-0 font-mono normal-case tracking-normal">
                    T{node.tier_range[0]}–{node.tier_range[1]}
                  </Chip>
                </Link>
              </motion.li>
            );
          })}
        </ul>
      </Card>

      <Card title="Ladder" subtitle="Every node is practised across ten depths">
        <ul className="grid gap-1.5 sm:grid-cols-2">
          {Object.entries(TIER_LABELS).map(([tier, label]) => {
            const reached = (data.progress?.highest_tier_cleared ?? 0) >= Number(tier);
            return (
              <li
                key={tier}
                className={cn(
                  'flex items-center gap-2.5 rounded-md border px-2.5 py-1.5 text-xs',
                  reached
                    ? 'border-accent/30 bg-accent/5 text-forge-200'
                    : 'border-forge-800 text-forge-600',
                )}
              >
                <span className="w-5 shrink-0 font-mono">T{tier}</span>
                <span>{label}</span>
                {reached && <span className="ml-auto text-accent">✓</span>}
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-xs leading-relaxed text-forge-500">
          Mastery is capped by the deepest tier you have actually cleared. Answering tier-1
          questions forever cannot take {titleCase(data.name)} past 25%.
        </p>
      </Card>
    </div>
  );
}
