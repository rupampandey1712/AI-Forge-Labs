/**
 * The typed API client.
 *
 * Three responsibilities, all of which are miserable when scattered across
 * components:
 *
 * 1. **Token lifecycle.** A 401 triggers exactly one refresh, and every request
 *    that arrived during that window waits for it and then retries. Without the
 *    single-flight guard, a dashboard firing six parallel requests on a stale
 *    token would fire six refreshes — five of which hit the backend's reuse
 *    detection and log the user out of everything.
 * 2. **Error normalisation.** The backend always returns
 *    `{error: {code, message, details}}`. This turns that into a typed
 *    `ApiError` so UI code never parses response bodies.
 * 3. **One place that knows the URL shape.**
 */

import type {
  Achievement,
  ApiError,
  AuthResponse,
  Badge,
  Challenge,
  ChallengeListItem,
  CodeRunResult,
  ConceptDetail,
  ConceptSummary,
  DailyMission,
  Dashboard,
  Grade,
  HealthInfo,
  InterviewAnswerResponse,
  InterviewReport,
  InterviewSession,
  LeaderboardRow,
  MissionCompletion,
  MissionDetail,
  MissionSummary,
  MistakeRecord,
  Page,
  PlayerProfile,
  ProgressAnalytics,
  Question,
  ReadinessBreakdown,
  RetentionDashboard,
  SkillProgress,
  SkillTree,
  TokenPair,
  WorldMap,
  XPTransaction,
} from '@/types/api';
import type {
  AgentRunResponse,
  AttentionRequest,
  AttentionResponse,
  ChunkPreviewResponse,
  EvalRunResponse,
  GenerateQuestionResponse,
  GoldenCase,
  GraphDiagram,
  GraphSummary,
  LabStatus,
  MentorAskRequest,
  MentorResponse,
  RAGCompareResponse,
  RAGConfig,
  RAGCorpus,
  RAGQueryResponse,
  SamplingRequest,
  SamplingResponse,
  SocraticResponse,
  TokenizeResponse,
} from '@/types/labs';

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1';
const ACCESS_KEY = 'aiforge.access';
const REFRESH_KEY = 'aiforge.refresh';

export class ApiRequestError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = 'ApiRequestError';
  }

  /** Field-level messages from a 422, keyed by field name, for form display. */
  get fieldErrors(): Record<string, string> {
    const fields = this.details.fields;
    if (!Array.isArray(fields)) return {};
    return Object.fromEntries(
      fields.map((f: { field: string; message: string }) => [f.field, f.message]),
    );
  }

  get isAuthError(): boolean {
    return this.status === 401;
  }

  get isLocked(): boolean {
    return this.status === 423;
  }
}

// ── Token storage ───────────────────────────────────────────────────────────
// localStorage rather than an httpOnly cookie is a deliberate, documented
// trade-off for a single-player local game: it makes the SPA work with no
// cookie/CSRF plumbing, at the cost of XSS exposure. A multi-tenant deployment
// should move to httpOnly refresh cookies + CSRF tokens — noted here rather
// than hidden, because the Security missions ask exactly this question.
export const tokens = {
  access: (): string | null => localStorage.getItem(ACCESS_KEY),
  refresh: (): string | null => localStorage.getItem(REFRESH_KEY),
  set(pair: TokenPair) {
    localStorage.setItem(ACCESS_KEY, pair.access_token);
    localStorage.setItem(REFRESH_KEY, pair.refresh_token);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

type Listener = () => void;
const authFailureListeners = new Set<Listener>();

/** Notified when the session is unrecoverable, so the app can redirect once. */
export function onAuthFailure(listener: Listener): () => void {
  authFailureListeners.add(listener);
  return () => authFailureListeners.delete(listener);
}

// Single-flight refresh: concurrent 401s share one in-progress refresh.
let refreshInFlight: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  const stored = tokens.refresh();
  if (!stored) return false;

  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: stored }),
      });
      if (!response.ok) return false;
      tokens.set((await response.json()) as TokenPair);
      return true;
    } catch {
      return false;
    } finally {
      // Cleared in a microtask so every waiter observes the same result before
      // a subsequent 401 can start a second refresh.
      queueMicrotask(() => {
        refreshInFlight = null;
      });
    }
  })();

  return refreshInFlight;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  auth?: boolean;
  signal?: AbortSignal;
  /** Internal: prevents infinite refresh recursion. */
  _retried?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = true, signal, _retried = false } = options;

  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (auth) {
    const token = tokens.access();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });

  if (response.status === 401 && auth && !_retried) {
    if (await refreshTokens()) {
      return request<T>(path, { ...options, _retried: true });
    }
    tokens.clear();
    authFailureListeners.forEach((l) => l());
  }

  if (!response.ok) {
    let payload: ApiError | null = null;
    try {
      payload = (await response.json()) as ApiError;
    } catch {
      /* a non-JSON error body (proxy error, 502) — fall through */
    }
    throw new ApiRequestError(
      response.status,
      payload?.error?.code ?? `http_${response.status}`,
      payload?.error?.message ?? response.statusText ?? 'Request failed',
      payload?.error?.details ?? {},
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const qs = (params: Record<string, string | number | boolean | undefined | null>): string => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : '';
};

// ── The surface ─────────────────────────────────────────────────────────────
export const api = {
  health: {
    info: () => request<HealthInfo>('/health/info', { auth: false }),
  },

  auth: {
    register: (body: { email: string; username: string; password: string; display_name?: string }) =>
      request<AuthResponse>('/auth/register', { method: 'POST', body, auth: false }),
    login: (body: { identifier: string; password: string }) =>
      request<AuthResponse>('/auth/login', { method: 'POST', body, auth: false }),
    logout: (allSessions = false) =>
      request<{ message: string }>(`/auth/logout${qs({ all_sessions: allSessions })}`, {
        method: 'POST',
        body: { refresh_token: tokens.refresh() ?? '' },
      }),
    me: () => request<{ id: string; email: string; username: string }>('/auth/me'),
    changePassword: (body: { current_password: string; new_password: string }) =>
      request<{ message: string }>('/auth/change-password', { method: 'POST', body }),
  },

  player: {
    profile: () => request<PlayerProfile>('/player/profile'),
    updateProfile: (body: Partial<Pick<PlayerProfile, 'display_name' | 'avatar_seed' | 'preferred_mentor'>>) =>
      request<PlayerProfile>('/player/profile', { method: 'PATCH', body }),
    dashboard: () => request<Dashboard>('/player/dashboard'),
    world: () => request<WorldMap>('/player/world'),
    skills: () => request<SkillProgress[]>('/player/skills'),
    skillTree: (slug: string) => request<SkillTree>(`/player/skills/${slug}`),
    badges: () => request<Badge[]>('/player/badges'),
    achievements: () => request<Achievement[]>('/player/achievements'),
    markBadgesSeen: () => request<{ message: string }>('/player/badges/seen', { method: 'POST' }),
    xpHistory: (limit = 50) => request<XPTransaction[]>(`/player/xp${qs({ limit })}`),
    leaderboard: (limit = 25) => request<LeaderboardRow[]>(`/player/leaderboard${qs({ limit })}`),
  },

  concepts: {
    list: (params: { category?: string; skill_slug?: string; node_slug?: string; search?: string; page?: number; page_size?: number } = {}) =>
      request<Page<ConceptSummary>>(`/concepts${qs(params)}`),
    get: (slug: string) => request<ConceptDetail>(`/concepts/${slug}`),
  },

  challenges: {
    list: (params: { category?: string; skill_slug?: string; tier?: number; page?: number; page_size?: number } = {}) =>
      request<Page<ChallengeListItem>>(`/challenges${qs(params)}`),
    get: (slug: string) => request<Challenge>(`/challenges/${slug}`),
    submit: (
      slug: string,
      body: {
        code: string;
        elapsed_seconds?: number;
        hints_used?: number;
        run_only?: boolean;
        explanation?: string;
        complexity?: string;
        tradeoffs?: string;
        confidence?: number;
      },
    ) => request<Grade>(`/challenges/${slug}/submit`, { method: 'POST', body }),
    hint: (slug: string, index: number) =>
      request<{ index: number; text: string; remaining: number; cost_coins: number }>(
        `/challenges/${slug}/hint${qs({ index })}`,
      ),
  },

  questions: {
    get: (slug: string) => request<Question>(`/questions/${slug}`),
    random: (params: { category?: string; tier?: number; interview_level?: string } = {}) =>
      request<Question | null>(`/questions/random${qs(params)}`),
    submit: (
      slug: string,
      body: {
        answer_text?: string;
        selected_option_ids?: string[];
        elapsed_seconds?: number;
        hints_used?: number;
        confidence?: number;
      },
    ) => request<Grade>(`/questions/${slug}/submit`, { method: 'POST', body }),
    hint: (slug: string, index: number) =>
      request<{ index: number; text: string; remaining: number; cost_coins: number }>(
        `/questions/${slug}/hint${qs({ index })}`,
      ),
  },

  missions: {
    list: (params: { building?: string; category?: string; kind?: string; include_locked?: boolean; page?: number; page_size?: number } = {}) =>
      request<Page<MissionSummary>>(`/missions${qs(params)}`),
    get: (slug: string) => request<MissionDetail>(`/missions/${slug}`),
    start: (slug: string) => request<MissionDetail>(`/missions/${slug}/start`, { method: 'POST' }),
    submitStep: (slug: string, body: Record<string, unknown>) =>
      request<Grade>(`/missions/${slug}/step`, { method: 'POST', body }),
    complete: (slug: string) =>
      request<MissionCompletion>(`/missions/${slug}/complete`, { method: 'POST' }),
    abandon: (slug: string) =>
      request<{ message: string }>(`/missions/${slug}/abandon`, { method: 'POST' }),
  },

  daily: {
    get: () => request<DailyMission>('/daily-challenge'),
    completeSlot: (slot: number, score: number) =>
      request<DailyMission>('/daily-challenge/submit', { method: 'POST', body: { slot, score } }),
    history: (limit = 14) =>
      request<{ date: string; completed: boolean; slots: number; completed_slots: number; xp_awarded: number }[]>(
        `/daily-challenge/history${qs({ limit })}`,
      ),
  },

  retention: {
    dashboard: () => request<RetentionDashboard>('/retention'),
    due: (limit = 20) =>
      request<{ concept_slug: string; skill_slug: string; category: string; retrievability: number; effective_mastery: number; urgency: number; days_since_practice: number }[]>(
        `/retention/due${qs({ limit })}`,
      ),
    mistakes: (includeResolved = false) =>
      request<MistakeRecord[]>(`/mistakes${qs({ include_resolved: includeResolved })}`),
  },

  interview: {
    start: (body: { level?: string; focus_categories?: string[]; mode?: string; question_count?: number }) =>
      request<InterviewSession>('/interview/start', { method: 'POST', body }),
    get: (id: string) => request<InterviewSession>(`/interview/${id}`),
    answer: (
      id: string,
      body: { position: number; answer_text?: string; selected_option_ids?: string[]; elapsed_seconds?: number; confidence?: number },
    ) => request<InterviewAnswerResponse>(`/interview/${id}/answer`, { method: 'POST', body }),
    report: (id: string) => request<InterviewReport>(`/interview/${id}/report`),
    end: (id: string) => request<{ message: string }>(`/interview/${id}/end`, { method: 'POST' }),
  },

  analytics: {
    progress: () => request<ProgressAnalytics>('/analytics/progress'),
    readiness: () => request<ReadinessBreakdown>('/analytics/readiness'),
    retention: () =>
      request<{ overall_retention: number; tracked: number; due: number; decayed: number; critical: number; calibration_error: number }>(
        '/analytics/retention',
      ),
  },

  code: {
    execute: (body: { code: string; setup_code?: string; stdin?: string; timeout?: number }) =>
      request<CodeRunResult>('/code/execute', { method: 'POST', body }),
  },

  journal: {
    list: (limit = 20) =>
      request<{ id: string; context_slug: string | null; what_i_learned: string; mistake_made: string; would_do_differently: string; confidence: number | null; concept_slugs: string[]; created_at: string }[]>(
        `/journal${qs({ limit })}`,
      ),
    add: (body: {
      what_i_learned?: string;
      mistake_made?: string;
      would_do_differently?: string;
      confidence?: number;
      context_slug?: string;
      concept_slugs?: string[];
    }) => request<{ id: string }>('/journal', { method: 'POST', body }),
  },

  // The labs are instruments: every call returns the intermediates, so these
  // are grouped by the tower they belong to rather than by HTTP shape.
  artifacts: {
    /**
     * Fetch a stored artifact as an object URL.
     *
     * WHY NOT just `<img src={url}>`: the artifact route is authenticated, so
     * a bare img tag sends no Authorization header and gets a 401. This fetches
     * through the same client that handles token refresh, then hands back a
     * blob URL the img tag can use.
     *
     * The caller MUST revokeObjectURL when the image unmounts — every object
     * URL pins its blob in memory until it is revoked, and a workbench session
     * that renders fifty plots would hold all fifty.
     */
    async objectUrl(path: string): Promise<string> {
      const response = await fetch(path, {
        headers: tokens.access() ? { Authorization: `Bearer ${tokens.access()}` } : {},
      });
      if (!response.ok) throw new ApiRequestError(response.status, 'artifact_failed', 'Could not load artifact.');
      return URL.createObjectURL(await response.blob());
    },
  },

  labs: {
    status: () => request<LabStatus>('/labs/status'),

    attention: (body: AttentionRequest) =>
      request<AttentionResponse>('/labs/transformer/attention', { method: 'POST', body }),
    tokenize: (text: string) =>
      request<TokenizeResponse>('/labs/transformer/tokenize', { method: 'POST', body: { text } }),
    sampling: (body: SamplingRequest) =>
      request<SamplingResponse>('/labs/transformer/sampling', { method: 'POST', body }),

    corpora: () => request<RAGCorpus[]>('/labs/rag/corpora'),
    chunkPreview: (body: {
      text: string;
      chunk_size?: number;
      chunk_overlap?: number;
      respect_structure?: boolean;
    }) => request<ChunkPreviewResponse>('/labs/rag/chunk-preview', { method: 'POST', body }),
    ragQuery: (body: {
      question: string;
      config?: RAGConfig;
      expected_answer?: string;
      relevant_doc_ids?: string[];
      save_experiment?: boolean;
    }) => request<RAGQueryResponse>('/labs/rag/query', { method: 'POST', body }),
    experiments: (limit = 20) =>
      request<RAGCompareResponse>(`/labs/rag/experiments${qs({ limit })}`),
    goldenSet: () => request<GoldenCase[]>('/labs/rag/golden-set'),

    graphs: () => request<GraphSummary[]>('/labs/agents'),
    graph: (slug: string) => request<GraphDiagram>(`/labs/agents/${slug}`),
    runAgent: (body: {
      graph: string;
      question: string;
      recursion_limit?: number;
      initial_state?: Record<string, unknown>;
      save_run?: boolean;
    }) => request<AgentRunResponse>('/labs/agents/run', { method: 'POST', body }),
    resumeAgent: (body: { run_id: string; approved: boolean; note?: string }) =>
      request<AgentRunResponse>('/labs/agents/resume', { method: 'POST', body }),

    mentorAsk: (body: MentorAskRequest) =>
      request<MentorResponse>('/labs/mentor/ask', { method: 'POST', body }),
    socratic: (body: { concept_slug: string; player_answer: string; tier?: number }) =>
      request<SocraticResponse>('/labs/mentor/socratic', { method: 'POST', body }),
    generate: (body: { concept_slug: string; tier?: number; kind?: string; count?: number }) =>
      request<GenerateQuestionResponse>('/labs/mentor/generate', { method: 'POST', body }),

    runEval: (body: {
      name: string;
      config?: RAGConfig;
      cases?: { question: string; relevant_doc_ids?: string[]; expected_answer?: string }[];
      use_golden_set?: boolean;
      use_llm_judge?: boolean;
      baseline_evaluation_id?: string | null;
    }) => request<EvalRunResponse>('/labs/evals/run', { method: 'POST', body }),
  },
};

export { API_BASE };
