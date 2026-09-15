/**
 * Global game state.
 *
 * WHY Zustand and not Redux/Context: there are exactly two pieces of genuinely
 * global state — who is signed in, and the transient reward queue that must
 * survive a route change. Everything else is server state and belongs to React
 * Query, which already handles caching, refetching and staleness far better
 * than a hand-rolled store would.
 *
 * The rule this file exists to enforce: **server data does not live here.**
 * Duplicating the profile into a store is how a dashboard ends up showing an
 * XP total that disagrees with the one on the next page.
 */

import { create } from 'zustand';
import type { Progression } from '@/types/api';
import { api, tokens } from '@/lib/api';

// ── Auth ────────────────────────────────────────────────────────────────────
interface AuthState {
  status: 'unknown' | 'authenticated' | 'anonymous';
  username: string | null;
  login: (identifier: string, password: string) => Promise<void>;
  register: (email: string, username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Called on startup and whenever the API client reports an unrecoverable 401. */
  resolve: () => Promise<void>;
  forceAnonymous: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  status: 'unknown',
  username: null,

  async login(identifier, password) {
    const result = await api.auth.login({ identifier, password });
    tokens.set(result.tokens);
    set({ status: 'authenticated', username: result.user.username });
  },

  async register(email, username, password) {
    const result = await api.auth.register({ email, username, password });
    tokens.set(result.tokens);
    set({ status: 'authenticated', username: result.user.username });
  },

  async logout() {
    try {
      await api.auth.logout();
    } catch {
      // A failed logout call must still clear the client. The server-side
      // token expires on its own; leaving the user "logged in" locally because
      // the network blipped is the worse outcome.
    }
    tokens.clear();
    set({ status: 'anonymous', username: null });
  },

  async resolve() {
    if (!tokens.access()) {
      set({ status: 'anonymous', username: null });
      return;
    }
    try {
      const me = await api.auth.me();
      set({ status: 'authenticated', username: me.username });
    } catch {
      tokens.clear();
      set({ status: 'anonymous', username: null });
    }
  },

  forceAnonymous() {
    tokens.clear();
    set({ status: 'anonymous', username: null });
  },
}));

// ── Reward queue ────────────────────────────────────────────────────────────
/**
 * Level-ups, rank-ups and badges are celebrated by an overlay that must
 * outlive the component that triggered them — submitting the last step of a
 * mission navigates away while the animation is still playing. A queue at app
 * level is the only way that works without the overlay flashing and vanishing.
 */
export interface RewardEvent {
  id: string;
  kind: 'xp' | 'level' | 'rank' | 'badge' | 'achievement' | 'building';
  title: string;
  subtitle?: string;
  amount?: number;
  payload?: Record<string, unknown>;
}

interface RewardState {
  queue: RewardEvent[];
  current: RewardEvent | null;
  push: (events: RewardEvent[]) => void;
  /** Ingest a Progression payload and enqueue everything worth celebrating. */
  celebrate: (progression: Progression | null | undefined) => void;
  next: () => void;
  clear: () => void;
}

let rewardCounter = 0;
const nextId = () => `r${++rewardCounter}`;

export const useRewards = create<RewardState>((set, get) => ({
  queue: [],
  current: null,

  push(events) {
    if (!events.length) return;
    const { current, queue } = get();
    if (current === null) {
      const [first, ...rest] = events;
      set({ current: first ?? null, queue: [...queue, ...rest] });
    } else {
      set({ queue: [...queue, ...events] });
    }
  },

  celebrate(progression) {
    if (!progression) return;
    const events: RewardEvent[] = [];

    // Order matters: the biggest news last, so the sequence builds.
    if (progression.xp_gained > 0) {
      events.push({
        id: nextId(),
        kind: 'xp',
        title: `+${progression.xp_gained} XP`,
        subtitle: progression.grants.map((g) => g.reason).slice(0, 3).join(' · '),
        amount: progression.xp_gained,
        payload: { grants: progression.grants },
      });
    }
    for (const slug of progression.new_badges) {
      events.push({ id: nextId(), kind: 'badge', title: 'Badge earned', subtitle: slug });
    }
    for (const slug of progression.new_achievements) {
      events.push({ id: nextId(), kind: 'achievement', title: 'Achievement unlocked', subtitle: slug });
    }
    for (const id of progression.unlocked_buildings) {
      events.push({ id: nextId(), kind: 'building', title: 'New district unlocked', subtitle: id });
    }
    if (progression.leveled_up) {
      events.push({
        id: nextId(),
        kind: 'level',
        title: `Level ${progression.new_level}`,
        subtitle: `${progression.previous_level} → ${progression.new_level}`,
        amount: progression.new_level,
      });
    }
    if (progression.ranked_up) {
      events.push({
        id: nextId(),
        kind: 'rank',
        title: 'Promotion',
        subtitle: progression.new_rank,
      });
    }
    get().push(events);
  },

  next() {
    const { queue } = get();
    const [head, ...rest] = queue;
    set({ current: head ?? null, queue: rest });
  },

  clear() {
    set({ queue: [], current: null });
  },
}));

// ── Ephemeral UI preferences ────────────────────────────────────────────────
interface UIState {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  setSidebar: (open: boolean) => void;
  /** Editor font size, persisted — players sit in the editor for hours. */
  editorFontSize: number;
  setEditorFontSize: (size: number) => void;
}

const FONT_KEY = 'aiforge.editorFontSize';

export const useUI = create<UIState>((set) => ({
  sidebarOpen: true,
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebar: (open) => set({ sidebarOpen: open }),
  editorFontSize: Number(localStorage.getItem(FONT_KEY) ?? 14),
  setEditorFontSize: (size) => {
    const clamped = Math.min(24, Math.max(10, size));
    localStorage.setItem(FONT_KEY, String(clamped));
    set({ editorFontSize: clamped });
  },
}));
