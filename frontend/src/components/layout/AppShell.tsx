/**
 * The persistent frame: sidebar, top bar, reward overlay.
 *
 * The top bar always shows XP, level, rank and streak. That is deliberate —
 * progression must be visible from every screen, or the RPG layer becomes a
 * page you visit rather than a system you feel.
 */

import { AnimatePresence, motion } from 'framer-motion';
import {
  Activity,
  Award,
  BookOpen,
  Bot,
  Braces,
  Bug,
  Coins,
  FlaskConical,
  Flame,
  GitBranch,
  Home,
  LogOut,
  type LucideIcon,
  Layers,
  Map,
  Menu,
  Mic,
  ShieldCheck,
  Swords,
  Target,
  TrendingUp,
  Zap,
} from 'lucide-react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuth, useUI } from '@/stores/game';
import { cn, compactNumber, RANK_TITLES } from '@/lib/utils';
import { Progress, Tooltip } from '@/components/ui';
import { RewardOverlay } from '@/components/game/RewardOverlay';

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  badgeKey?: 'due' | 'daily';
}

const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: 'Play',
    items: [
      { to: '/app', label: 'Dashboard', icon: Home },
      { to: '/app/world', label: 'World Map', icon: Map },
      { to: '/app/daily', label: 'Daily Mission', icon: Target, badgeKey: 'daily' },
      { to: '/app/missions', label: 'Missions', icon: Swords },
    ],
  },
  {
    section: 'Train',
    items: [
      { to: '/app/practice', label: 'Practice', icon: Zap },
      { to: '/app/concepts', label: 'Codex', icon: BookOpen },
      { to: '/app/interview', label: 'Interview Arena', icon: Mic },
      { to: '/app/retention', label: 'Retention', icon: Activity, badgeKey: 'due' },
    ],
  },
  {
    // The labs are a distinct mode of engagement: everything above asks you
    // questions, and these hand you the instrument. Grouping them apart keeps
    // that distinction legible rather than burying them in "Train".
    section: 'Labs',
    items: [
      { to: '/app/labs', label: 'All Labs', icon: FlaskConical },
      { to: '/app/labs/transformer', label: 'Transformer', icon: Layers },
      { to: '/app/labs/rag', label: 'RAG Bench', icon: Braces },
      { to: '/app/labs/agents', label: 'Agent Factory', icon: GitBranch },
      { to: '/app/labs/evals', label: 'Evaluation', icon: ShieldCheck },
      { to: '/app/labs/mentor', label: 'AI Mentor', icon: Bot },
    ],
  },
  {
    section: 'Review',
    items: [
      { to: '/app/skills', label: 'Skill Trees', icon: TrendingUp },
      { to: '/app/mistakes', label: 'Mistake Log', icon: Bug },
      { to: '/app/analytics', label: 'Analytics', icon: Activity },
      { to: '/app/achievements', label: 'Achievements', icon: Award },
    ],
  },
];

export function AppShell() {
  const { sidebarOpen, toggleSidebar } = useUI();
  const logout = useAuth((s) => s.logout);
  const location = useLocation();

  // One lightweight poll drives the whole chrome. `staleTime` stops every
  // route change from refetching; the dashboard page owns the fresh copy.
  const { data: profile } = useQuery({
    queryKey: ['profile'],
    queryFn: api.player.profile,
    staleTime: 20_000,
  });

  const { data: retention } = useQuery({
    queryKey: ['retention-summary'],
    queryFn: api.analytics.retention,
    staleTime: 60_000,
  });

  const { data: daily } = useQuery({
    queryKey: ['daily'],
    queryFn: api.daily.get,
    staleTime: 60_000,
  });

  const badgeFor = (key?: NavItem['badgeKey']): number => {
    if (key === 'due') return retention?.due ?? 0;
    if (key === 'daily') {
      if (!daily || daily.completed) return 0;
      return daily.slots.length - daily.completed_count;
    }
    return 0;
  };

  return (
    <div className="flex min-h-screen">
      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <AnimatePresence initial={false}>
        {sidebarOpen && (
          <motion.aside
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 240, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 260, damping: 30 }}
            className="sticky top-0 z-30 h-screen shrink-0 overflow-hidden border-r border-forge-800 bg-forge-900/80 backdrop-blur"
          >
            <div className="flex h-full w-60 flex-col">
              <div className="flex items-center gap-2.5 px-5 py-5">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-signal-xp">
                  <span className="font-display text-sm font-bold text-forge-950">AF</span>
                </div>
                <div className="min-w-0">
                  <div className="truncate font-display text-sm font-semibold">AI Forge Labs</div>
                  <div className="truncate text-[10px] uppercase tracking-widest text-forge-500">
                    Engineering Sim
                  </div>
                </div>
              </div>

              <nav className="flex-1 space-y-5 overflow-y-auto px-3 pb-4">
                {NAV.map((group) => (
                  <div key={group.section}>
                    <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-forge-600">
                      {group.section}
                    </div>
                    <ul className="space-y-0.5">
                      {group.items.map((item) => {
                        const count = badgeFor(item.badgeKey);
                        return (
                          <li key={item.to}>
                            <NavLink
                              to={item.to}
                              end={item.to === '/app'}
                              className={({ isActive }) =>
                                cn(
                                  'group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors',
                                  isActive
                                    ? 'bg-accent/10 font-medium text-accent'
                                    : 'text-forge-300 hover:bg-forge-800 hover:text-forge-100',
                                )
                              }
                            >
                              <item.icon className="h-4 w-4 shrink-0" aria-hidden />
                              <span className="flex-1 truncate">{item.label}</span>
                              {count > 0 && (
                                <span className="rounded-full bg-signal-decay px-1.5 py-0.5 text-[10px] font-bold text-forge-950">
                                  {count}
                                </span>
                              )}
                              {location.pathname === item.to && (
                                <motion.span
                                  layoutId="nav-active"
                                  className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-accent"
                                />
                              )}
                            </NavLink>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
              </nav>

              <div className="border-t border-forge-800 p-3">
                <button
                  onClick={logout}
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-forge-400 transition-colors hover:bg-forge-800 hover:text-forge-100"
                >
                  <LogOut className="h-4 w-4" aria-hidden />
                  Sign out
                </button>
              </div>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      {/* ── Main ────────────────────────────────────────────────────────── */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-forge-800 bg-forge-950/85 backdrop-blur">
          <div className="flex items-center gap-4 px-4 py-2.5">
            <button
              onClick={toggleSidebar}
              aria-label={sidebarOpen ? 'Collapse navigation' : 'Expand navigation'}
              className="rounded-md p-1.5 text-forge-400 transition-colors hover:bg-forge-800 hover:text-forge-100"
            >
              <Menu className="h-4 w-4" />
            </button>

            {profile && (
              <>
                <div className="flex min-w-0 items-center gap-3">
                  <Avatar seed={profile.avatar_seed} level={profile.level} />
                  <div className="hidden min-w-0 sm:block">
                    <div className="truncate text-sm font-medium leading-tight">
                      {profile.display_name}
                    </div>
                    <div className="truncate text-[11px] leading-tight text-forge-400">
                      {RANK_TITLES[profile.rank] ?? profile.rank} · {profile.experience_band} yrs
                    </div>
                  </div>
                </div>

                <div className="hidden min-w-0 flex-1 md:block">
                  <Tooltip
                    label={`${profile.xp_into_level} / ${profile.xp_for_next_level} XP to level ${profile.level + 1}`}
                  >
                    <div className="w-full max-w-sm">
                      <div className="mb-1 flex items-baseline justify-between text-[11px]">
                        <span className="font-medium text-forge-300">Level {profile.level}</span>
                        <span className="font-mono tabular-nums text-forge-500">
                          {compactNumber(profile.total_xp)} XP
                        </span>
                      </div>
                      <Progress value={profile.progress_pct / 100} height={5} />
                    </div>
                  </Tooltip>
                </div>

                <div className="ml-auto flex items-center gap-3 text-sm">
                  <Tooltip label={`${profile.current_streak}-day streak (best ${profile.longest_streak})`}>
                    <span className="flex items-center gap-1 text-signal-decay">
                      <Flame className="h-4 w-4" aria-hidden />
                      <span className="font-mono tabular-nums">{profile.current_streak}</span>
                    </span>
                  </Tooltip>
                  <Tooltip label="Coins — spend on hints and mentor consults">
                    <span className="flex items-center gap-1 text-signal-warn">
                      <Coins className="h-4 w-4" aria-hidden />
                      <span className="font-mono tabular-nums">{compactNumber(profile.coins)}</span>
                    </span>
                  </Tooltip>
                </div>
              </>
            )}
          </div>
        </header>

        <main className="min-w-0 flex-1 px-4 py-6 lg:px-8">
          <Outlet />
        </main>
      </div>

      <RewardOverlay />
    </div>
  );
}

/**
 * Deterministic generated avatar.
 *
 * WHY generated rather than an image upload: no storage, no moderation, no
 * broken-image state, and it stays recognisable. The seed hashes to a hue, so
 * the same player is always the same colour.
 */
function Avatar({ seed, level }: { seed: string; level: number }) {
  const hash = Array.from(seed).reduce((acc, ch) => acc * 31 + ch.charCodeAt(0), 7);
  const hue = Math.abs(hash) % 360;
  const initials = seed.slice(0, 2).toUpperCase();

  return (
    <div className="relative shrink-0">
      <div
        className="flex h-9 w-9 items-center justify-center rounded-lg font-display text-xs font-bold text-forge-950"
        style={{
          background: `linear-gradient(135deg, hsl(${hue} 70% 62%), hsl(${(hue + 48) % 360} 72% 54%))`,
        }}
      >
        {initials}
      </div>
      <span className="absolute -bottom-1 -right-1 rounded-md border border-forge-700 bg-forge-900 px-1 font-mono text-[10px] font-bold tabular-nums text-accent">
        {level}
      </span>
    </div>
  );
}
