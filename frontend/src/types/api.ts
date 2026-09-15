/**
 * Hand-written mirrors of the backend's Pydantic response models.
 *
 * WHY hand-written rather than generated from OpenAPI: the generated output is
 * a wall of `components['schemas']['…']` indirection that makes every call site
 * unreadable, and it regenerates noisily on unrelated backend edits. These are
 * the ~25 shapes the UI actually consumes. The guard against drift is
 * `src/test/contract.test.ts`, which validates these types against the live
 * OpenAPI schema — so a backend rename fails the frontend build rather than
 * silently rendering `undefined`.
 */

export interface ApiError {
  error: { code: string; message: string; details: Record<string, unknown> };
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ── Auth ────────────────────────────────────────────────────────────────────
export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserPublic {
  id: string;
  email: string;
  username: string;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface AuthResponse {
  user: UserPublic;
  tokens: TokenPair;
}

// ── Player ──────────────────────────────────────────────────────────────────
export interface PlayerProfile {
  id: string;
  display_name: string;
  avatar_seed: string;
  title: string;
  total_xp: number;
  level: number;
  rank: string;
  experience_band: string;
  coins: number;
  reputation: number;
  current_streak: number;
  longest_streak: number;
  last_active_date: string | null;
  missions_completed: number;
  challenges_passed: number;
  questions_answered: number;
  bosses_defeated: number;
  incidents_resolved: number;
  total_practice_seconds: number;
  unlocked_buildings: string[];
  preferred_mentor: string;
  onboarding_completed: boolean;
  xp_into_level: number;
  xp_for_next_level: number;
  progress_pct: number;
  next_rank: string | null;
  next_rank_level: number | null;
  created_at: string;
}

export interface XPGrant {
  source: string;
  amount: number;
  reason: string;
  metadata: Record<string, unknown>;
}

export interface Progression {
  xp_gained: number;
  total_xp: number;
  previous_level: number;
  new_level: number;
  previous_rank: string;
  new_rank: string;
  leveled_up: boolean;
  ranked_up: boolean;
  xp_into_level: number;
  xp_for_next_level: number;
  progress_pct: number;
  coins_gained: number;
  grants: XPGrant[];
  new_badges: string[];
  new_achievements: string[];
  unlocked_buildings: string[];
}

export interface SkillProgress {
  skill_slug: string;
  name: string;
  icon: string;
  color: string;
  level: number;
  xp: number;
  mastery: number;
  effective_mastery: number;
  peak_mastery: number;
  confidence: number;
  forgetting_score: number;
  highest_tier_cleared: number;
  attempts: number;
  correct: number;
  accuracy: number;
  streak: number;
  last_practiced_at: string | null;
  concepts_total: number;
  concepts_started: number;
  concepts_due: number;
  concepts_decayed: number;
}

export interface SkillNode {
  slug: string;
  name: string;
  summary: string;
  parent_slug: string | null;
  tier_range: number[];
  unlock_level: number;
  display_order: number;
  unlocked: boolean;
  mastery: number;
  concepts_total: number;
  concepts_mastered: number;
}

export interface SkillTree {
  skill_slug: string;
  name: string;
  description: string;
  icon: string;
  color: string;
  building: string | null;
  progress: SkillProgress | null;
  nodes: SkillNode[];
}

export interface Building {
  id: string;
  name: string;
  tagline: string;
  description: string;
  skill_slugs: string[];
  categories: string[];
  required_level: number;
  required_rank: string | null;
  position: { x: number; y: number };
  accent: string;
  icon: string;
  unlocked: boolean;
  mission_count: number;
  missions_completed: number;
  mastery: number;
  has_alert: boolean;
  alert_text: string | null;
}

export interface WorldMap {
  profile: PlayerProfile;
  buildings: Building[];
  alerts: DecayAlert[];
}

export interface Badge {
  slug: string;
  name: string;
  description: string;
  tier: string;
  icon: string;
  xp_reward: number;
  earned: boolean;
  earned_at: string | null;
  secret: boolean;
}

export interface Achievement {
  slug: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  xp_reward: number;
  coin_reward: number;
  target: number;
  progress: number;
  completed: boolean;
  completed_at: string | null;
  secret: boolean;
}

export interface XPTransaction {
  source: string;
  amount: number;
  reason: string;
  skill_slug: string | null;
  reference_type: string | null;
  reference_slug: string | null;
  balance_after: number;
  created_at: string;
}

export interface LeaderboardRow {
  position: number;
  display_name: string;
  xp: number;
  level: number;
  rank: string;
  is_me: boolean;
}

export interface Dashboard {
  profile: PlayerProfile;
  skills: SkillProgress[];
  retention_alerts: DecayAlert[];
  due_reviews: number;
  daily: unknown | null;
  recent_events: RecentEvent[];
  recommended: Recommendation[];
  open_mistakes: OpenMistake[];
  unseen_badges: Badge[];
  streak_calendar: { date: string; count: number }[];
}

export interface RecentEvent {
  type: string;
  concept_slug: string | null;
  skill_slug: string | null;
  score: number | null;
  tier: number | null;
  at: string;
  payload: Record<string, unknown>;
}

export interface Recommendation {
  kind: string;
  slug: string;
  title: string;
  reason: string;
}

export interface OpenMistake {
  pattern: string;
  title: string;
  severity: string;
  occurrences: number;
  why_it_matters: string;
}

// ── Content ─────────────────────────────────────────────────────────────────
export interface ConceptSummary {
  slug: string;
  title: string;
  category: string;
  skill_slug: string;
  base_difficulty: number;
  summary: string;
  estimated_minutes: number;
  tags: string[];
  mastery: number;
  effective_mastery: number;
  due: boolean;
  decayed: boolean;
}

export interface ConceptDetail extends ConceptSummary {
  explanation: string;
  examples: { title: string; code: string; output: string; note: string }[];
  common_mistakes: { mistake: string; why: string; fix: string; severity: string }[];
  real_world_usage: string[];
  visualization: { type: string; [k: string]: unknown } | null;
  max_tier: number;
  prerequisites: ConceptSummary[];
  leads_to: ConceptSummary[];
  related: ConceptSummary[];
  challenge_slugs: string[];
  question_slugs: string[];
}

export interface VisibleTest {
  name: string;
  description: string;
  call: string | null;
  expect: unknown;
  points: number;
}

export interface Challenge {
  slug: string;
  title: string;
  category: string;
  skill_slug: string;
  tier: number;
  prompt: string;
  starter_code: string;
  hints_available: number;
  visible_tests: VisibleTest[];
  hidden_test_count: number;
  explanation_prompts: string[];
  requires_packages: string[];
  par_seconds: number;
  time_limit_seconds: number;
  concept_slugs: string[];
  expected_complexity: string | null;
  target_speedup: number | null;
  baseline_code: string | null;
  attempts_made: number;
  solved: boolean;
}

export interface ChallengeListItem {
  slug: string;
  title: string;
  category: string;
  skill_slug: string;
  tier: number;
  par_seconds: number;
  solved: boolean;
  concept_slugs: string[];
}

export interface QuestionOption {
  id: string;
  text: string;
}

export interface Question {
  slug: string;
  kind: string;
  category: string;
  skill_slug: string;
  tier: number;
  interview_level: string;
  prompt: string;
  context: string | null;
  options: QuestionOption[];
  hints_available: number;
  par_seconds: number;
  concept_slugs: string[];
}

export interface TestResult {
  name: string;
  passed: boolean;
  hidden: boolean;
  expected: unknown;
  actual: unknown;
  message: string;
  duration_ms: number;
}

export interface Grade {
  passed: boolean;
  score: number;
  points: number;
  max_points: number;
  tests_passed: number;
  tests_total: number;
  test_results: TestResult[];
  stdout: string;
  stderr: string;
  runtime_ms: number;
  timed_out: boolean;
  headline: string;
  what_happened: string;
  root_cause: string | null;
  hint: string | null;
  explanation_score: number | null;
  explanation_feedback: string | null;
  missing_points: string[];
  detected_mistakes: DetectedMistake[];
  speedup_factor: number | null;
  progression: Progression | null;
  mastery_delta: Record<string, MasteryDelta> | null;
  next_review_at: string | null;
  can_retry: boolean;
  reveal_solution: boolean;
  solution: string | null;
  solution_explanation: string | null;
}

export interface MasteryDelta {
  before: number;
  after: number;
  next_review_days?: number;
}

export interface DetectedMistake {
  pattern: string;
  title: string;
  description: string;
  why_it_matters: string;
  correct_approach: string;
  severity: string;
  line: number | null;
  concept_slug: string | null;
  category: string | null;
  evidence: string;
}

export interface MissionStep {
  position: number;
  step_type: string;
  title: string;
  prompt: string;
  challenge_slug: string | null;
  question_slug: string | null;
  config: Record<string, unknown>;
  required: boolean;
  status: string;
  score: number | null;
}

export interface MissionSummary {
  slug: string;
  title: string;
  kind: string;
  category: string;
  building: string;
  tier: number;
  skill_slug: string;
  objective: string;
  estimated_minutes: number;
  required_level: number;
  is_boss: boolean;
  locked: boolean;
  lock_reason: string | null;
  completed: boolean;
  best_score: number | null;
  attempts: number;
}

export interface MissionDetail extends MissionSummary {
  briefing: string;
  success_criteria: string[];
  artifacts: Record<string, unknown>;
  concept_slugs: string[];
  par_seconds: number;
  steps: MissionStep[];
  attempt_id: string | null;
  debrief: string | null;
}

export interface MissionCompletion {
  passed: boolean;
  score: number;
  elapsed_seconds: number;
  progression: Progression;
  debrief: string;
  journal_prompt: Record<string, string>;
}

// ── Retention ───────────────────────────────────────────────────────────────
export interface DecayAlert {
  severity: 'info' | 'warning' | 'critical';
  scope: string;
  slug: string;
  title: string;
  headline: string;
  detail: string;
  from_mastery: number;
  to_mastery: number;
  days_since_practice: number;
  repair_mission_slug: string | null;
  repair_kind: string;
  concept_slugs: string[];
}

export interface ConceptDecay {
  concept_slug: string;
  title: string;
  category: string;
  skill_slug: string;
  mastery: number;
  peak_mastery: number;
  effective_mastery: number;
  retrievability: number;
  forgetting_probability: number;
  mastery_drop: number;
  days_since_practice: number;
  urgency: number;
  is_due: boolean;
  is_decayed: boolean;
  is_critical: boolean;
  due_at: string | null;
  lapses: number;
  attempts: number;
  accuracy: number;
}

export interface RetentionDashboard {
  generated_at: string;
  overall_retention: number;
  concepts_tracked: number;
  concepts_due: number;
  concepts_decayed: number;
  concepts_critical: number;
  alerts: DecayAlert[];
  due_now: ConceptDecay[];
  upcoming: ConceptDecay[];
  strongest: ConceptDecay[];
  weakest: ConceptDecay[];
  recently_forgotten: ConceptDecay[];
  by_skill: SkillRetention[];
  forecast: ForecastPoint[];
}

export interface SkillRetention {
  skill_slug: string;
  name: string;
  color: string;
  concepts: number;
  due: number;
  decayed: number;
  mastery: number;
  effective_mastery: number;
}

export interface ForecastPoint {
  day: number;
  date: string;
  retention: number;
  effective_mastery: number;
}

export interface DailySlot {
  slot: number;
  kind: string;
  category: string;
  title: string;
  reason: string;
  tier: number;
  ref_type: string;
  ref_slug: string;
  estimated_minutes: number;
  completed: boolean;
  score: number | null;
}

export interface DailyMission {
  id: string;
  for_date: string;
  slots: DailySlot[];
  estimated_minutes: number;
  completed: boolean;
  completed_at: string | null;
  xp_awarded: number;
  completed_count: number;
  streak: number;
  generation_reason: Record<string, unknown>;
}

export interface MistakeRecord {
  pattern: string;
  title: string;
  description: string;
  why_it_matters: string;
  correct_approach: string;
  severity: string;
  category: string | null;
  skill_slug: string | null;
  concept_slug: string | null;
  occurrences: number;
  clean_streak: number;
  resolved: boolean;
  first_seen_at: string;
  last_seen_at: string;
}

// ── Interview ───────────────────────────────────────────────────────────────
export interface InterviewTurn {
  position: number;
  prompt: string;
  context: string | null;
  options: QuestionOption[];
  kind: string;
  tier: number;
  category: string | null;
  is_followup: boolean;
  parent_position: number | null;
  time_limit_seconds: number | null;
  answered: boolean;
  score: number | null;
  interviewer_reaction: string;
}

export interface InterviewSession {
  id: string;
  level: string;
  mode: string;
  persona: string;
  status: string;
  focus_categories: string[];
  planned_questions: number;
  questions_asked: number;
  started_at: string;
  completed_at: string | null;
  current_turn: InterviewTurn | null;
  turns: InterviewTurn[];
}

export interface InterviewFeedback {
  score: number;
  dimension_scores: Record<string, number>;
  hit_points: string[];
  missing_points: string[];
  interviewer_reaction: string;
  ideal_answer: string | null;
  common_wrong_answer: string | null;
  level_gap: Record<string, string>;
  graded_by: string;
}

export interface InterviewAnswerResponse {
  feedback: InterviewFeedback;
  next_turn: InterviewTurn | null;
  session_complete: boolean;
  progression: Progression | null;
}

export interface InterviewReport {
  session_id: string;
  level: string;
  overall_score: number;
  verdict: string;
  dimension_scores: Record<string, number>;
  summary: string;
  strengths: string[];
  gaps: string[];
  per_question: InterviewReportQuestion[];
  recommended_concepts: string[];
  recommended_missions: string[];
  interview_readiness: number;
  progression: Progression | null;
}

export interface InterviewReportQuestion {
  position: number;
  prompt: string;
  tier: number;
  category: string | null;
  is_followup: boolean;
  score: number | null;
  elapsed_seconds: number;
  missing_points: string[];
  reaction: string;
  answer: string | null;
}

// ── Analytics ───────────────────────────────────────────────────────────────
export interface MasteryRow {
  slug: string;
  name: string;
  mastery: number;
  effective_mastery: number;
  peak_mastery: number;
  delta_30d: number;
  attempts: number;
  accuracy: number;
  last_practiced_at: string | null;
}

export interface TimeSeriesPoint {
  date: string;
  value: number;
  label: string | null;
}

export interface ProgressAnalytics {
  generated_at: string;
  total_xp: number;
  level: number;
  rank: string;
  experience_band: string;
  mastery_by_skill: MasteryRow[];
  mastery_by_category: MasteryRow[];
  xp_over_time: TimeSeriesPoint[];
  activity_over_time: TimeSeriesPoint[];
  accuracy_over_time: TimeSeriesPoint[];
  xp_by_source: { source: string; amount: number }[];
  tier_distribution: { tier: number; count: number }[];
  strongest_skills: MasteryRow[];
  weakest_skills: MasteryRow[];
  recently_forgotten: { concept_slug: string; skill_slug: string; from: number; to: number; days: number }[];
  most_common_mistakes: { pattern: string; title: string; occurrences: number; severity: string }[];
  interview_readiness: number;
  coding_speed_index: number;
  debugging_score: number;
  architecture_score: number;
  production_score: number;
  consistency_score: number;
  practice_minutes_7d: number;
  practice_minutes_30d: number;
}

export interface ReadinessBreakdown {
  overall: number;
  by_level: Record<string, number>;
  components: ReadinessComponent[];
  blocking_gaps: ReadinessComponent[];
  next_actions: Recommendation[];
}

export interface ReadinessComponent {
  slug: string;
  name: string;
  weight: number;
  value: number;
  contribution: number;
  headroom: number;
}

export interface HealthInfo {
  name: string;
  version: string;
  environment: string;
  database_dialect: string;
  sandbox_mode: string;
  llm_provider: string;
  llm_configured: boolean;
  api_prefix: string;
}

export interface CodeRunResult {
  status: string;
  stdout: string;
  stderr: string;
  duration_ms: number;
  timed_out: boolean;
  error_type: string | null;
  error_message: string;
  traceback: string | null;
  benchmark_ms: number | null;
}
