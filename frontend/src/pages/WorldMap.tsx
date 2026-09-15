/**
 * The world map — 14 buildings on a pannable canvas.
 *
 * WHY an SVG/absolute-positioned canvas rather than a grid of cards: the map is
 * the spatial memory of the game. Backend City is always down-left of the
 * Transformer Center; the Debugging Dungeon is always in the dark corner. That
 * consistency is what makes a player say "I'm going to the RAG Tower" instead
 * of "I'm clicking the eighth card".
 *
 * Locked buildings are dimmed but still *visible and positioned* — seeing what
 * you have not unlocked is most of the motivation.
 */

import { motion } from 'framer-motion';
import { Lock, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button, LoadingPanel, Modal } from '@/components/ui';
import { MasteryBar } from '@/components/game/bits';
import { cn, pct, titleCase } from '@/lib/utils';
import type { Building } from '@/types/api';

export default function WorldMap() {
  const { data, isLoading } = useQuery({ queryKey: ['world'], queryFn: api.player.world });
  const [selected, setSelected] = useState<Building | null>(null);

  if (isLoading || !data) return <LoadingPanel rows={10} className="mx-auto max-w-6xl" />;

  const unlockedCount = data.buildings.filter((b) => b.unlocked).length;

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">AI Forge Labs</h1>
          <p className="mt-1 text-sm text-forge-400">
            {unlockedCount} of {data.buildings.length} districts open · {titleCase(data.profile.rank)},
            level {data.profile.level}
          </p>
        </div>
        {data.alerts.length > 0 && (
          <span className="chip border-signal-decay/40 bg-signal-decay/10 text-signal-decay">
            {data.alerts.length} decay alert{data.alerts.length === 1 ? '' : 's'}
          </span>
        )}
      </div>

      {/* ── The map ─────────────────────────────────────────────────────── */}
      <div className="panel relative aspect-[16/10] w-full overflow-hidden">
        {/* Ambient layers: grid, glow, a slow scan line. Cheap, and they make
            the canvas read as a live console rather than a static image. */}
        <div className="absolute inset-0 bg-grid bg-grid opacity-40" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_50%_35%,rgba(34,211,238,0.10),transparent_65%)]" />
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px animate-scan-line bg-gradient-to-r from-transparent via-accent/40 to-transparent" />

        {/* Connective tissue between adjacent districts. */}
        <svg className="absolute inset-0 h-full w-full" aria-hidden>
          {CONNECTIONS.map(([from, to]) => {
            const a = data.buildings.find((b) => b.id === from);
            const b = data.buildings.find((x) => x.id === to);
            if (!a || !b) return null;
            const live = a.unlocked && b.unlocked;
            return (
              <line
                key={`${from}-${to}`}
                x1={`${a.position.x * 100}%`}
                y1={`${a.position.y * 100}%`}
                x2={`${b.position.x * 100}%`}
                y2={`${b.position.y * 100}%`}
                stroke={live ? 'rgba(34,211,238,0.28)' : 'rgba(58,70,112,0.28)'}
                strokeWidth={1.5}
                strokeDasharray={live ? undefined : '4 6'}
              />
            );
          })}
        </svg>

        {data.buildings.map((building, i) => (
          <BuildingNode
            key={building.id}
            building={building}
            index={i}
            onSelect={() => setSelected(building)}
          />
        ))}
      </div>

      {/* ── Legend / list fallback for small screens ────────────────────── */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data.buildings.map((building) => (
          <button
            key={building.id}
            onClick={() => setSelected(building)}
            className={cn(
              'panel panel-hover flex items-start gap-3 p-3 text-left',
              !building.unlocked && 'opacity-60',
            )}
          >
            <span
              className="mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: building.unlocked ? building.accent : '#3a4670' }}
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium text-forge-100">{building.name}</span>
                {!building.unlocked && <Lock className="h-3 w-3 shrink-0 text-forge-500" />}
                {building.has_alert && (
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-signal-decay" />
                )}
              </div>
              <p className="mt-0.5 truncate text-xs text-forge-500">{building.tagline}</p>
              {building.unlocked && building.mission_count > 0 && (
                <div className="mt-1.5 flex items-center gap-2 text-[11px] text-forge-500">
                  <span className="font-mono">
                    {building.missions_completed}/{building.mission_count}
                  </span>
                  <span>missions</span>
                  {building.mastery > 0 && (
                    <span className="ml-auto font-mono" style={{ color: building.accent }}>
                      {pct(building.mastery)}
                    </span>
                  )}
                </div>
              )}
            </div>
          </button>
        ))}
      </div>

      <BuildingModal building={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

function BuildingNode({
  building,
  index,
  onSelect,
}: {
  building: Building;
  index: number;
  onSelect: () => void;
}) {
  return (
    <motion.button
      onClick={onSelect}
      initial={{ opacity: 0, scale: 0.6 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: index * 0.045, type: 'spring', stiffness: 260, damping: 18 }}
      whileHover={{ scale: 1.14, zIndex: 10 }}
      className="absolute -translate-x-1/2 -translate-y-1/2 focus:outline-none"
      style={{ left: `${building.position.x * 100}%`, top: `${building.position.y * 100}%` }}
      aria-label={`${building.name}${building.unlocked ? '' : ' (locked)'}`}
    >
      <div className="relative flex flex-col items-center gap-1.5">
        {/* An alert ring pulses — the only animation on the map that demands
            attention, which is what keeps it meaningful. */}
        {building.has_alert && building.unlocked && (
          <span
            className="absolute inset-0 -m-1 animate-pulse-ring rounded-xl border-2"
            style={{ borderColor: '#fb923c' }}
          />
        )}

        <div
          className={cn(
            'flex h-10 w-10 items-center justify-center rounded-xl border-2 transition-all sm:h-12 sm:w-12',
            building.unlocked
              ? 'shadow-lg backdrop-blur-sm'
              : 'border-forge-700 bg-forge-900/70',
          )}
          style={
            building.unlocked
              ? {
                  borderColor: building.accent,
                  backgroundColor: `${building.accent}1a`,
                  boxShadow: `0 0 20px -6px ${building.accent}`,
                }
              : undefined
          }
        >
          {building.unlocked ? (
            <Sparkles className="h-4 w-4 sm:h-5 sm:w-5" style={{ color: building.accent }} aria-hidden />
          ) : (
            <Lock className="h-3.5 w-3.5 text-forge-500" aria-hidden />
          )}
        </div>

        <span
          className={cn(
            'max-w-[92px] text-center text-[10px] font-medium leading-tight sm:max-w-[110px] sm:text-[11px]',
            building.unlocked ? 'text-forge-200' : 'text-forge-600',
          )}
        >
          {building.name}
        </span>

        {building.unlocked && building.mission_count > 0 && (
          <span className="font-mono text-[9px] text-forge-500">
            {building.missions_completed}/{building.mission_count}
          </span>
        )}
      </div>
    </motion.button>
  );
}

function BuildingModal({ building, onClose }: { building: Building | null; onClose: () => void }) {
  return (
    <Modal open={!!building} onClose={onClose} title={building?.name} size="md">
      {building && (
        <div className="space-y-4">
          <p className="text-sm italic text-forge-400">{building.tagline}</p>
          <p className="text-sm leading-relaxed text-forge-200">{building.description}</p>

          {building.unlocked ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-forge-700 bg-forge-900/60 p-3">
                  <div className="stat-label">Missions</div>
                  <div className="mt-0.5 font-display text-lg tabular-nums">
                    {building.missions_completed}
                    <span className="text-forge-500">/{building.mission_count}</span>
                  </div>
                </div>
                <div className="rounded-lg border border-forge-700 bg-forge-900/60 p-3">
                  <div className="stat-label">Mastery</div>
                  <div className="mt-0.5 font-display text-lg tabular-nums" style={{ color: building.accent }}>
                    {pct(building.mastery)}
                  </div>
                </div>
              </div>

              {building.skill_slugs.length > 0 && (
                <div>
                  <div className="stat-label mb-2">Trains</div>
                  <div className="flex flex-wrap gap-1.5">
                    {building.skill_slugs.map((slug) => (
                      <Link key={slug} to={`/app/skills/${slug}`} className="chip border-forge-600 bg-forge-800 text-forge-300 hover:border-accent hover:text-accent">
                        {titleCase(slug)}
                      </Link>
                    ))}
                  </div>
                </div>
              )}

              {building.alert_text && (
                <div className="rounded-lg border border-signal-decay/40 bg-signal-decay/10 p-3 text-sm text-signal-decay">
                  {building.alert_text}
                </div>
              )}

              <Link to={`/app/missions?building=${building.id}`}>
                <Button variant="primary" className="w-full">
                  Enter {building.name}
                </Button>
              </Link>
            </>
          ) : (
            <div className="rounded-lg border border-forge-700 bg-forge-900/60 p-4 text-center">
              <Lock className="mx-auto h-5 w-5 text-forge-500" />
              <p className="mt-2 text-sm text-forge-300">{building.alert_text ?? 'Not yet unlocked.'}</p>
              <p className="mt-1 text-xs text-forge-500">
                Requires level {building.required_level}
                {building.required_rank ? ` · ${titleCase(building.required_rank)}` : ''}
              </p>
            </div>
          )}

          <MasteryBar mastery={building.mastery} className="pt-1" />
        </div>
      )}
    </Modal>
  );
}

/** Which districts are drawn as connected. Purely visual, but consistent. */
const CONNECTIONS: [string, string][] = [
  ['python_academy', 'backend_city'],
  ['python_academy', 'debugging_dungeon'],
  ['python_academy', 'interview_arena'],
  ['backend_city', 'production_city'],
  ['backend_city', 'data_science_lab'],
  ['data_science_lab', 'ml_arena'],
  ['ml_arena', 'deep_learning_lab'],
  ['deep_learning_lab', 'transformer_center'],
  ['transformer_center', 'rag_tower'],
  ['rag_tower', 'agent_factory'],
  ['agent_factory', 'ai_war_room'],
  ['production_city', 'architecture_tower'],
  ['architecture_tower', 'staff_hq'],
  ['ai_war_room', 'staff_hq'],
  ['interview_arena', 'architecture_tower'],
  ['debugging_dungeon', 'production_city'],
];
