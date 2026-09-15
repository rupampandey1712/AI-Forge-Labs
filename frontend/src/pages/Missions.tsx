import { motion } from 'framer-motion';
import { Clock, Lock, Swords, Trophy } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Card, Chip, EmptyState, LoadingPanel } from '@/components/ui';
import { KindChip, TierChip } from '@/components/game/bits';
import { cn, titleCase } from '@/lib/utils';
import type { MissionSummary } from '@/types/api';

export default function Missions() {
  const [params, setParams] = useSearchParams();
  const building = params.get('building') ?? undefined;
  const kind = params.get('kind') ?? undefined;

  const missions = useQuery({
    queryKey: ['missions', building, kind],
    queryFn: () => api.missions.list({ building, kind, page_size: 60 }),
  });
  const world = useQuery({ queryKey: ['world'], queryFn: api.player.world });

  const setFilter = (key: string, value?: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };

  if (missions.isLoading) return <LoadingPanel rows={8} className="mx-auto max-w-5xl" />;

  const items = missions.data?.items ?? [];
  const unlocked = items.filter((m) => !m.locked);
  const locked = items.filter((m) => m.locked);

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">Missions</h1>
        <p className="mt-1 text-sm text-forge-400">
          {unlocked.length} available · {locked.length} locked · {items.filter((m) => m.completed).length}{' '}
          completed
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setFilter('building')}
          className={cn(
            'chip',
            !building ? 'border-accent bg-accent/10 text-accent' : 'border-forge-600 bg-forge-800 text-forge-300',
          )}
        >
          All districts
        </button>
        {world.data?.buildings
          .filter((b) => b.mission_count > 0)
          .map((b) => (
            <button
              key={b.id}
              onClick={() => setFilter('building', b.id)}
              disabled={!b.unlocked}
              className={cn(
                'chip normal-case tracking-normal disabled:opacity-40',
                building === b.id
                  ? 'border-accent bg-accent/10 text-accent'
                  : 'border-forge-600 bg-forge-800 text-forge-300',
              )}
            >
              {b.name}
            </button>
          ))}
      </div>

      {items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Swords className="h-8 w-8" />}
            title="No missions here yet"
            description="Try another district, or run the content seeder."
          />
        </Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {[...unlocked, ...locked].map((mission, i) => (
            <MissionCard key={mission.slug} mission={mission} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}

function MissionCard({ mission, index }: { mission: MissionSummary; index: number }) {
  const body = (
    <div
      className={cn(
        'panel h-full p-4 transition-colors',
        mission.locked ? 'opacity-55' : 'panel-hover',
        mission.is_boss && !mission.locked && 'border-signal-warn/40',
        mission.completed && 'border-signal-success/30',
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <KindChip kind={mission.kind} />
        <TierChip tier={mission.tier} />
        {mission.is_boss && (
          <span className="chip border-signal-warn/50 bg-signal-warn/10 text-signal-warn">
            <Trophy className="h-3 w-3" /> Boss
          </span>
        )}
        {mission.completed && (
          <span className="chip border-signal-success/40 bg-signal-success/10 text-signal-success">
            Cleared
          </span>
        )}
        <span className="ml-auto flex items-center gap-1 text-[11px] text-forge-500">
          <Clock className="h-3 w-3" />
          {mission.estimated_minutes}m
        </span>
      </div>

      <h3 className="mt-2.5 font-display text-base font-semibold text-forge-100">{mission.title}</h3>
      <p className="mt-1 line-clamp-2 text-sm leading-relaxed text-forge-400">{mission.objective}</p>

      <div className="mt-3 flex items-center gap-2 text-[11px] text-forge-500">
        <Chip className="normal-case tracking-normal">{titleCase(mission.skill_slug)}</Chip>
        {mission.attempts > 0 && <span>{mission.attempts} attempt{mission.attempts === 1 ? '' : 's'}</span>}
        {mission.best_score !== null && mission.best_score > 0 && (
          <span className="font-mono">best {(mission.best_score * 100).toFixed(0)}%</span>
        )}
      </div>

      {mission.locked && (
        <div className="mt-3 flex items-center gap-2 rounded-md border border-forge-700 bg-forge-950/60 px-2.5 py-1.5 text-xs text-forge-400">
          <Lock className="h-3.5 w-3.5 shrink-0" />
          {mission.lock_reason}
        </div>
      )}
    </div>
  );

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.03 }}>
      {mission.locked ? body : <Link to={`/app/missions/${mission.slug}`}>{body}</Link>}
    </motion.div>
  );
}
