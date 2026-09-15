import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** Merge Tailwind classes so a later class genuinely overrides an earlier one. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export const pct = (value: number, digits = 0): string =>
  `${(value * 100).toFixed(digits)}%`;

export const compactNumber = (value: number): string =>
  value >= 1_000_000
    ? `${(value / 1_000_000).toFixed(1)}M`
    : value >= 1_000
      ? `${(value / 1_000).toFixed(1)}k`
      : String(value);

export function duration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function relativeTime(iso: string | null): string {
  if (!iso) return 'never';
  const delta = (Date.now() - new Date(iso).getTime()) / 1000;
  if (delta < 60) return 'just now';
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  const days = Math.floor(delta / 86400);
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

export const titleCase = (slug: string): string =>
  slug.replace(/[_-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

/** Tier 1..10 -> the ladder label from spec §56. */
export const TIER_LABELS: Record<number, string> = {
  1: 'Remember',
  2: 'Understand',
  3: 'Implement',
  4: 'Debug',
  5: 'Optimize',
  6: 'Design',
  7: 'Explain',
  8: 'Production',
  9: 'Staff tradeoff',
  10: 'Principal architecture',
};

/**
 * Tier colour. Deliberately a gradient from cool to hot rather than a
 * rainbow: the player should read "how deep is this" at a glance without
 * having to learn a legend.
 */
export function tierColor(tier: number): string {
  if (tier <= 2) return 'text-forge-300 bg-forge-700/60 border-forge-600';
  if (tier <= 4) return 'text-accent bg-accent/10 border-accent/30';
  if (tier <= 6) return 'text-signal-xp bg-signal-xp/10 border-signal-xp/30';
  if (tier <= 8) return 'text-signal-warn bg-signal-warn/10 border-signal-warn/30';
  return 'text-signal-danger bg-signal-danger/10 border-signal-danger/40';
}

export function masteryColor(mastery: number): string {
  if (mastery >= 0.8) return '#34d399';
  if (mastery >= 0.6) return '#22d3ee';
  if (mastery >= 0.4) return '#a78bfa';
  if (mastery >= 0.2) return '#fbbf24';
  return '#f43f5e';
}

export const severityColor: Record<string, string> = {
  critical: 'text-signal-danger border-signal-danger/40 bg-signal-danger/10',
  high: 'text-signal-decay border-signal-decay/40 bg-signal-decay/10',
  medium: 'text-signal-warn border-signal-warn/40 bg-signal-warn/10',
  low: 'text-forge-300 border-forge-600 bg-forge-700/40',
};

export const RANK_TITLES: Record<string, string> = {
  python_apprentice: 'Python Apprentice',
  python_developer: 'Python Developer',
  backend_engineer: 'Backend Engineer',
  senior_python_engineer: 'Senior Python Engineer',
  ml_engineer: 'ML Engineer',
  deep_learning_engineer: 'Deep Learning Engineer',
  ai_engineer: 'AI Engineer',
  llm_engineer: 'LLM Engineer',
  ai_platform_engineer: 'AI Platform Engineer',
  staff_ai_engineer: 'Staff AI Engineer',
  principal_ai_engineer: 'Principal AI Engineer',
};

export const VERDICT_LABELS: Record<string, { label: string; className: string }> = {
  strong_hire: { label: 'Strong Hire', className: 'text-signal-success' },
  hire: { label: 'Hire', className: 'text-accent' },
  lean_hire: { label: 'Lean Hire', className: 'text-signal-xp' },
  lean_no_hire: { label: 'Lean No Hire', className: 'text-signal-warn' },
  no_hire: { label: 'No Hire', className: 'text-signal-danger' },
};

/** Respect the OS "reduce motion" setting — animations here are decorative. */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/** Kind -> colour/label for mission and daily-slot badges.
 *  Lives here rather than beside <KindChip> so that component file exports
 *  only components, which is what React Fast Refresh requires. */
export const KIND_STYLES: Record<string, { label: string; className: string }> = {
  coding: { label: 'Coding', className: 'border-accent/40 bg-accent/10 text-accent' },
  challenge: { label: 'Coding', className: 'border-accent/40 bg-accent/10 text-accent' },
  debugging: { label: 'Debug', className: 'border-signal-danger/40 bg-signal-danger/10 text-signal-danger' },
  concept: { label: 'Concept', className: 'border-forge-600 bg-forge-800 text-forge-300' },
  explain: { label: 'Explain', className: 'border-signal-xp/40 bg-signal-xp/10 text-signal-xp' },
  interview: { label: 'Interview', className: 'border-signal-warn/40 bg-signal-warn/10 text-signal-warn' },
  incident: { label: 'Incident', className: 'border-signal-danger/50 bg-signal-danger/15 text-signal-danger' },
  boss: { label: 'Boss', className: 'border-signal-warn/60 bg-signal-warn/15 text-signal-warn' },
  architecture: { label: 'Design', className: 'border-forge-400/40 bg-forge-700 text-forge-200' },
  code_review: { label: 'Review', className: 'border-signal-success/40 bg-signal-success/10 text-signal-success' },
  data_lab: { label: 'Data', className: 'border-signal-success/40 bg-signal-success/10 text-signal-success' },
  ml_lab: { label: 'ML', className: 'border-signal-warn/40 bg-signal-warn/10 text-signal-warn' },
  rag_lab: { label: 'RAG', className: 'border-accent/40 bg-accent/10 text-accent' },
  agent_lab: { label: 'Agent', className: 'border-signal-xp/40 bg-signal-xp/10 text-signal-xp' },
  refactor: { label: 'Refactor', className: 'border-forge-500 bg-forge-700 text-forge-200' },
  capstone: { label: 'Capstone', className: 'border-signal-warn/60 bg-signal-warn/15 text-signal-warn' },
  visualization: { label: 'Charts', className: 'border-signal-success/40 bg-signal-success/10 text-signal-success' },
};
