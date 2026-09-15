import { Award, Lock, Trophy } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Card, LoadingPanel, Progress, Stat, Tab, TabList, TabPanel, Tabs } from '@/components/ui';
import { cn, relativeTime, titleCase } from '@/lib/utils';
import type { Achievement, Badge } from '@/types/api';

const TIER_STYLES: Record<string, { ring: string; text: string; glow: string }> = {
  bronze: { ring: 'border-amber-700/60', text: 'text-amber-600', glow: 'shadow-none' },
  silver: { ring: 'border-slate-400/50', text: 'text-slate-300', glow: 'shadow-none' },
  gold: { ring: 'border-signal-warn/60', text: 'text-signal-warn', glow: 'shadow-[0_0_20px_-6px_#fbbf24]' },
  platinum: { ring: 'border-accent/60', text: 'text-accent', glow: 'shadow-glow' },
  legendary: {
    ring: 'border-signal-xp/70',
    text: 'text-signal-xp',
    glow: 'shadow-[0_0_28px_-6px_#a78bfa]',
  },
};

export default function Achievements() {
  const badges = useQuery({ queryKey: ['badges'], queryFn: api.player.badges });
  const achievements = useQuery({ queryKey: ['achievements'], queryFn: api.player.achievements });
  const leaderboard = useQuery({ queryKey: ['leaderboard'], queryFn: () => api.player.leaderboard(25) });

  if (badges.isLoading || achievements.isLoading) {
    return <LoadingPanel rows={8} className="mx-auto max-w-5xl" />;
  }

  const earned = badges.data?.filter((b) => b.earned) ?? [];
  const completed = achievements.data?.filter((a) => a.completed) ?? [];

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">Achievements</h1>
        <p className="mt-1 text-sm text-forge-400">
          Badges mark a moment; achievements track a journey. Both unlock from declarative criteria —
          there is no hidden logic deciding whether you qualify.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Stat label="Badges" value={`${earned.length}/${badges.data?.length ?? 0}`} accent="#fbbf24" />
        <Stat
          label="Achievements"
          value={`${completed.length}/${achievements.data?.length ?? 0}`}
          accent="#a78bfa"
        />
        <Stat
          label="Bonus XP earned"
          value={earned.reduce((sum, b) => sum + b.xp_reward, 0).toLocaleString()}
        />
      </div>

      <Tabs defaultValue="badges">
        <TabList>
          <Tab value="badges">Badges</Tab>
          <Tab value="achievements">Achievements</Tab>
          <Tab value="leaderboard">Leaderboard</Tab>
        </TabList>

        <TabPanel value="badges">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {badges.data?.map((badge) => <BadgeCard key={badge.slug} badge={badge} />)}
          </div>
        </TabPanel>

        <TabPanel value="achievements">
          <div className="space-y-3">
            {achievements.data?.map((achievement) => (
              <AchievementRow key={achievement.slug} achievement={achievement} />
            ))}
          </div>
        </TabPanel>

        <TabPanel value="leaderboard">
          <Card subtitle="All-time XP">
            {leaderboard.isLoading ? (
              <LoadingPanel rows={5} className="border-0 bg-transparent p-0 shadow-none" />
            ) : (
              <ol className="space-y-1">
                {leaderboard.data?.map((row) => (
                  <li
                    key={`${row.position}-${row.display_name}`}
                    className={cn(
                      'flex items-center gap-3 rounded-lg px-3 py-2',
                      row.is_me ? 'border border-accent/40 bg-accent/10' : 'bg-forge-900/40',
                    )}
                  >
                    <span
                      className={cn(
                        'w-7 shrink-0 text-right font-mono text-sm tabular-nums',
                        row.position <= 3 ? 'text-signal-warn' : 'text-forge-500',
                      )}
                    >
                      {row.position}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm text-forge-100">
                      {row.display_name}
                      {row.is_me && <span className="ml-2 text-xs text-accent">you</span>}
                    </span>
                    <span className="shrink-0 text-xs text-forge-500">{titleCase(row.rank)}</span>
                    <span className="w-10 shrink-0 text-right font-mono text-xs text-forge-400">
                      L{row.level}
                    </span>
                    <span className="w-20 shrink-0 text-right font-mono text-sm tabular-nums text-signal-xp">
                      {row.xp.toLocaleString()}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </TabPanel>
      </Tabs>
    </div>
  );
}

function BadgeCard({ badge }: { badge: Badge }) {
  const style = TIER_STYLES[badge.tier] ?? TIER_STYLES.bronze!;
  const hidden = badge.secret && !badge.earned;

  return (
    <div
      className={cn(
        'panel flex items-start gap-3 p-4 transition-all',
        badge.earned ? cn('border-2', style.ring, style.glow) : 'opacity-55',
      )}
    >
      <div
        className={cn(
          'flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border-2',
          badge.earned ? cn(style.ring, style.text) : 'border-forge-700 text-forge-600',
        )}
      >
        {badge.earned ? <Award className="h-5 w-5" /> : <Lock className="h-4 w-4" />}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <h3 className="truncate font-display text-sm font-semibold text-forge-100">
            {hidden ? 'Secret badge' : badge.name}
          </h3>
          <span className={cn('chip shrink-0 border-current', style.text)}>{badge.tier}</span>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-forge-400">
          {hidden ? 'Unlocks when you do something specific.' : badge.description}
        </p>
        <div className="mt-1.5 flex items-center gap-2 text-[11px]">
          {badge.xp_reward > 0 && (
            <span className="font-mono text-signal-xp">+{badge.xp_reward} XP</span>
          )}
          {badge.earned && badge.earned_at && (
            <span className="text-forge-600">{relativeTime(badge.earned_at)}</span>
          )}
        </div>
      </div>
    </div>
  );
}

function AchievementRow({ achievement }: { achievement: Achievement }) {
  const hidden = achievement.secret && !achievement.completed && achievement.progress === 0;
  const ratio = achievement.target ? achievement.progress / achievement.target : 0;

  return (
    <div
      className={cn(
        'panel p-4',
        achievement.completed && 'border-signal-success/40',
        hidden && 'opacity-55',
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border',
            achievement.completed
              ? 'border-signal-success/50 text-signal-success'
              : 'border-forge-700 text-forge-500',
          )}
        >
          <Trophy className="h-4 w-4" />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-display text-sm font-semibold text-forge-100">
              {hidden ? 'Secret achievement' : achievement.name}
            </h3>
            <span className="chip border-forge-600 bg-forge-800 text-forge-400">
              {titleCase(achievement.category)}
            </span>
            {achievement.completed && (
              <span className="chip border-signal-success/40 bg-signal-success/10 text-signal-success">
                Complete
              </span>
            )}
          </div>

          <p className="mt-1 text-xs leading-relaxed text-forge-400">
            {hidden ? 'Keep playing.' : achievement.description}
          </p>

          <div className="mt-2.5 flex items-center gap-3">
            <Progress value={ratio} height={5} className="flex-1" animate={false} />
            <span className="shrink-0 font-mono text-[11px] tabular-nums text-forge-500">
              {achievement.progress.toLocaleString()}/{achievement.target.toLocaleString()}
            </span>
          </div>

          <div className="mt-1.5 flex items-center gap-3 text-[11px]">
            {achievement.xp_reward > 0 && (
              <span className="font-mono text-signal-xp">+{achievement.xp_reward} XP</span>
            )}
            {achievement.coin_reward > 0 && (
              <span className="font-mono text-signal-warn">+{achievement.coin_reward} coins</span>
            )}
            {achievement.completed_at && (
              <span className="text-forge-600">{relativeTime(achievement.completed_at)}</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
