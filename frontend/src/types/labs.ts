/**
 * Types for the interactive labs.
 *
 * Kept in their own module rather than appended to `api.ts` because the labs
 * are instruments, not CRUD: their responses carry every intermediate value the
 * visualiser needs (raw scores, per-stage timings, state diffs), so the shapes
 * are both larger and shaped by rendering needs rather than by domain entities.
 *
 * Same drift guard applies — `src/test/contract.test.ts` validates every path
 * these are used on against the committed OpenAPI schema.
 */

// ── Transformer Lab ─────────────────────────────────────────────────────────
export interface LabToken {
  text: string;
  index: number;
  id: number;
  is_subword: boolean;
  of_word: string;
}

export interface AttentionHead {
  head: number;
  /** [query][key] — rows sum to 1. This is the matrix the heatmap draws. */
  weights: number[][];
  /** Pre-softmax Q·Kᵀ(/√d). Shown so scaling stops being an abstract claim. */
  raw_scores: number[][];
  /** Per-query-row entropy: low = sharp/confident, high = diffuse. */
  entropy: number[];
  argmax: number[];
}

export interface AttentionResponse {
  tokens: LabToken[];
  d_model: number;
  n_heads: number;
  d_head: number;
  causal: boolean;
  scaled: boolean;
  heads: AttentionHead[];
  vectors: {
    embedding: number[][];
    positional: number[][] | null;
    combined: number[][];
    shown_dimensions: number;
  } | null;
  insight: string;
}

export interface AttentionRequest {
  text?: string;
  n_heads?: number;
  d_model?: number;
  causal?: boolean;
  scaled?: boolean;
  use_positional?: boolean;
}

export interface TokenizeResponse {
  tokens: LabToken[];
  stats: {
    tokens: number;
    words: number;
    characters: number;
    tokens_per_word: number;
    chars_per_token: number;
    subword_splits: number;
  };
  cost_estimates: {
    model: string;
    /** This one prompt, once. Reads as free — which is the trap. */
    cost_per_request: number;
    /** The same prompt at a million calls. This is the number that bites. */
    input_cost_per_1m_requests: number;
  }[];
}

export interface SamplingRequest {
  temperature?: number;
  top_k?: number | null;
  top_p?: number | null;
  logits?: number[];
  labels?: string[];
}

export interface SamplingResponse {
  labels: string[];
  logits: number[];
  temperature: number;
  scaled_logits: number[];
  /** After temperature, before truncation. */
  probabilities: number[];
  /** After truncation and renormalisation — what actually gets sampled. */
  final_probabilities: number[];
  kept: boolean[];
  tokens_kept: number;
  truncation: string;
  entropy: number;
  argmax: string;
  insight: string;
}

// ── RAG Tower ───────────────────────────────────────────────────────────────
export interface RAGConfig {
  corpus?: string;
  chunk_size?: number;
  chunk_overlap?: number;
  respect_structure?: boolean;
  top_k?: number;
  use_reranker?: boolean;
  use_hybrid?: boolean;
  metadata_filter?: Record<string, unknown>;
  max_context_chars?: number;
  temperature?: number;
  min_score?: number;
  prompt_template?: string;
}

export interface ChunkPreviewResponse {
  chunks: {
    index: number;
    text: string;
    start_char: number;
    end_char: number;
    chars: number;
    tokens: number;
  }[];
  total_chunks: number;
  avg_chars: number;
  avg_tokens: number;
  /** Characters duplicated across boundaries — what overlap actually costs. */
  overlap_waste_chars: number;
  insight: string;
}

export interface RetrievedChunk {
  doc_slug: string;
  title: string;
  text: string;
  score: number;
  chunk_index: number;
  metadata: Record<string, unknown>;
  rerank_score: number | null;
  /** Position before reranking — the delta is the reranker's whole value. */
  original_rank: number | null;
}

export interface PipelineStage {
  name: string;
  duration_ms: number;
  detail: Record<string, unknown>;
}

export interface RAGQueryResponse {
  question: string;
  answer: string;
  retrieved: RetrievedChunk[];
  config: Record<string, unknown>;
  stages: PipelineStage[];
  prompt: string;
  total_ms: number;
  token_usage: Record<string, number>;
  cost_usd: number;
  simulated: boolean;
  metrics: Record<string, number>;
  experiment_id: string | null;
  diagnosis: string[];
}

export interface RAGCorpus {
  corpus: string;
  documents: number;
  chunks: number;
  embedding_model: string | null;
  total_tokens: number;
  titles: string[];
}

export interface RAGExperiment {
  id: string;
  question: string;
  chunk_size: number;
  chunk_overlap: number;
  top_k: number;
  use_reranker: boolean;
  use_hybrid: boolean;
  embedding_model: string;
  answer: string;
  metrics: Record<string, number>;
  latency_ms: number;
  created_at: string;
}

export interface RAGCompareResponse {
  experiments: RAGExperiment[];
  delta: Record<string, number>;
  verdict: string;
  reasons: string[];
}

export interface GoldenCase {
  question: string;
  relevant: string[];
  expected: string;
}

// ── Agent Factory ───────────────────────────────────────────────────────────
export interface GraphSummary {
  slug: string;
  title: string;
  teaches: string;
  difficulty: number;
  /** Deliberately broken graphs exist to be debugged, not avoided. */
  broken: boolean;
  watch_for: string;
  nodes: number;
  edges: number;
  cycles: number;
}

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  description: string;
  interrupt_before: boolean;
  is_entry: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
  label: string;
  description: string;
}

export interface GraphDiagram {
  name: string;
  entry: string | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Not bugs — but each one needs a termination argument. */
  cycles: string[][];
  info: Record<string, unknown>;
}

export interface AgentStep {
  step: number;
  node: string;
  status: string;
  duration_ms: number;
  /** Only what this node changed — the readable unit of agent debugging. */
  state_diff: Record<string, unknown>;
  state_after: Record<string, unknown>;
  edge_taken: string | null;
  edge_reason: string | null;
  error: string | null;
  tokens: number;
  cost_usd: number;
}

export interface AgentRunResponse {
  run_id: string | null;
  graph: string;
  status: string;
  final_state: Record<string, unknown>;
  history: AgentStep[];
  halted_reason: string | null;
  interrupted_at: string | null;
  steps: number;
  total_ms: number;
  node_visits: Record<string, number>;
  looped: boolean;
  diagnosis: string[];
}

// ── Mentor & content agent ──────────────────────────────────────────────────
export type MentorLevel = 'nudge' | 'hint' | 'concept' | 'partial' | 'full';

export interface MentorAskRequest {
  question: string;
  concept_slug?: string | null;
  challenge_slug?: string | null;
  code?: string | null;
  error?: string | null;
  tier?: number;
  attempts?: number;
  hints_used?: number;
  persona?: string;
}

export interface MentorResponse {
  level: MentorLevel;
  message: string;
  question_back: string | null;
  next_level: string | null;
  reveals_answer: boolean;
  simulated: boolean;
  tokens: number;
  cost_usd: number;
  /** The mentor's own graph run — the tool demonstrating its own mechanism. */
  trace: { node: string; [key: string]: unknown }[];
}

export interface SocraticResponse {
  question: string;
  targets_misconception: string;
  good_answer_contains: string[];
  tier: number;
  simulated: boolean;
}

export interface GeneratedQuestion {
  prompt: string;
  kind: string;
  tier: number;
  context: string;
  options: { id?: string; text: string; correct?: boolean; why?: string }[];
  expected_answer: string;
  ideal_senior_answer: string;
  common_wrong_answer: string;
  rubric: { point: string; keywords: string[]; weight: number }[];
  hints: string[];
  followups: string[];
  /** Non-empty means rejected — it must not be served as content. */
  issues: string[];
  is_usable: boolean;
  simulated: boolean;
}

export interface GenerateQuestionResponse {
  concept_slug: string;
  concept_title: string;
  generated: GeneratedQuestion[];
  accepted: number;
  rejected: number;
  validation_note: string;
}

// ── Evaluation Lab ──────────────────────────────────────────────────────────
export interface EvalCaseResult {
  question: string;
  answer: string;
  passed: boolean;
  metrics: Record<string, number>;
  retrieved_titles: string[];
  unsupported_claims: string[];
}

export interface EvalRunResponse {
  evaluation_id: string | null;
  name: string;
  cases_total: number;
  cases_passed: number;
  metrics: Record<string, number>;
  per_case: EvalCaseResult[];
  verdict: string;
  reasons: string[];
  baseline: Record<string, number> | null;
  judged_by: string;
}

export interface LabStatus {
  llm: { provider: string; simulated: boolean; configured: boolean };
  embeddings: { model: string; simulated: boolean };
  note: string;
}
