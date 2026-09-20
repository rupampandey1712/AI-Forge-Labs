/**
 * Frontend ↔ backend contract test.
 *
 * WHY this exists: the API types in `src/types/api.ts` are hand-written, which
 * is a deliberate trade (readable call sites, no generated indirection) with
 * one obvious risk — silent drift when the backend renames something. A wrong
 * TypeScript type does not fail the build; it renders `undefined` at 2am.
 *
 * This test closes that hole by checking every path the API client calls
 * against the committed OpenAPI schema. A backend rename therefore fails the
 * FRONTEND build, which is exactly where the broken call site lives.
 *
 * Regenerate the schema with:  cd backend && python -m app.cli openapi
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

interface OpenAPISchema {
  paths: Record<string, Record<string, unknown>>;
  components?: { schemas?: Record<string, { properties?: Record<string, unknown>; required?: string[] }> };
}

const schema: OpenAPISchema = JSON.parse(
  readFileSync(join(__dirname, '../../../openapi.json'), 'utf-8'),
);

const PREFIX = '/api/v1';

/** Every endpoint `src/lib/api.ts` calls, as (method, path template) pairs. */
const CALLS: [string, string][] = [
  ['get', '/health/info'],
  ['post', '/auth/register'],
  ['post', '/auth/login'],
  ['post', '/auth/refresh'],
  ['post', '/auth/logout'],
  ['get', '/auth/me'],
  ['post', '/auth/change-password'],
  ['get', '/player/profile'],
  ['patch', '/player/profile'],
  ['get', '/player/dashboard'],
  ['get', '/player/world'],
  ['get', '/player/skills'],
  ['get', '/player/skills/{skill_slug}'],
  ['get', '/player/badges'],
  ['get', '/player/achievements'],
  ['post', '/player/badges/seen'],
  ['get', '/player/xp'],
  ['get', '/player/leaderboard'],
  ['get', '/concepts'],
  ['get', '/concepts/{slug}'],
  ['get', '/challenges'],
  ['get', '/challenges/{slug}'],
  ['post', '/challenges/{slug}/submit'],
  ['get', '/challenges/{slug}/hint'],
  ['get', '/questions/random'],
  ['get', '/questions/{slug}'],
  ['post', '/questions/{slug}/submit'],
  ['get', '/questions/{slug}/hint'],
  ['get', '/missions'],
  ['get', '/missions/{slug}'],
  ['post', '/missions/{slug}/start'],
  ['post', '/missions/{slug}/step'],
  ['post', '/missions/{slug}/complete'],
  ['post', '/missions/{slug}/abandon'],
  ['get', '/daily-challenge'],
  ['post', '/daily-challenge/submit'],
  ['get', '/daily-challenge/history'],
  ['get', '/retention'],
  ['get', '/retention/due'],
  ['get', '/mistakes'],
  ['post', '/interview/start'],
  ['get', '/interview/{session_id}'],
  ['post', '/interview/{session_id}/answer'],
  ['get', '/interview/{session_id}/report'],
  ['post', '/interview/{session_id}/end'],
  ['get', '/analytics/progress'],
  ['get', '/analytics/readiness'],
  ['get', '/analytics/retention'],
  ['post', '/code/execute'],
  ['get', '/journal'],
  ['post', '/journal'],
  ['get', '/labs/status'],
  ['post', '/labs/transformer/attention'],
  ['post', '/labs/transformer/tokenize'],
  ['post', '/labs/transformer/sampling'],
  ['get', '/labs/rag/corpora'],
  ['post', '/labs/rag/chunk-preview'],
  ['post', '/labs/rag/query'],
  ['get', '/labs/rag/experiments'],
  ['get', '/labs/rag/golden-set'],
  ['get', '/labs/agents'],
  ['get', '/labs/agents/{slug}'],
  ['post', '/labs/agents/run'],
  ['post', '/labs/agents/resume'],
  ['post', '/labs/mentor/ask'],
  ['post', '/labs/mentor/socratic'],
  ['post', '/labs/mentor/generate'],
  ['post', '/labs/evals/run'],
];

describe('API contract', () => {
  it('the committed schema is non-trivial', () => {
    expect(Object.keys(schema.paths).length).toBeGreaterThan(40);
  });

  it.each(CALLS)('%s %s exists in the backend', (method, path) => {
    const full = `${PREFIX}${path}`;
    expect(
      schema.paths[full],
      `${full} is not in the OpenAPI schema. Either the client calls a path that no longer exists, ` +
        `or openapi.json is stale (regenerate: cd backend && python -m app.cli openapi).`,
    ).toBeDefined();
    expect(
      schema.paths[full]?.[method],
      `${method.toUpperCase()} is not allowed on ${full}.`,
    ).toBeDefined();
  });

  it('the client covers every non-admin endpoint the backend exposes', () => {
    const called = new Set(CALLS.map(([m, p]) => `${m} ${PREFIX}${p}`));
    const exposed = Object.entries(schema.paths).flatMap(([path, methods]) =>
      Object.keys(methods)
        .filter((m) => ['get', 'post', 'patch', 'put', 'delete'].includes(m))
        .map((m) => `${m} ${path}`),
    );
    // Liveness/readiness probes are for infrastructure, not the SPA.
    const uncovered = exposed.filter(
      (op) => !called.has(op) && !op.includes('/health/live') && !op.includes('/health/ready'),
    );
    expect(uncovered, `Endpoints the frontend never calls: ${uncovered.join(', ')}`).toEqual([]);
  });
});

describe('response shapes', () => {
  const props = (name: string): string[] =>
    Object.keys(schema.components?.schemas?.[name]?.properties ?? {});

  // Spot-check the fields the UI would break most visibly without. These are
  // the ones that silently render `undefined` rather than throwing.
  it.each([
    ['PlayerProfileOut', ['level', 'rank', 'total_xp', 'progress_pct', 'current_streak', 'experience_band']],
    ['DecayAlertOut', ['severity', 'headline', 'detail', 'from_mastery', 'to_mastery']],
    ['GradeOut', ['passed', 'score', 'headline', 'what_happened', 'test_results', 'mastery_delta']],
    ['DailySlotOut', ['slot', 'kind', 'title', 'reason', 'tier', 'ref_type', 'ref_slug']],
    ['RetentionDashboardOut', ['overall_retention', 'concepts_due', 'alerts', 'forecast', 'by_skill']],
    ['InterviewFeedbackOut', ['score', 'dimension_scores', 'interviewer_reaction', 'level_gap']],
    ['SkillProgressOut', ['skill_slug', 'mastery', 'effective_mastery', 'highest_tier_cleared']],
    // Labs: the intermediates are the product. A missing `raw_scores` or
    // `state_diff` turns a visualiser into a black box with nicer colours.
    ['AttentionResponse', ['tokens', 'heads', 'd_head', 'causal', 'scaled', 'insight']],
    ['AttentionHeadOut', ['weights', 'raw_scores', 'entropy', 'argmax']],
    ['RAGQueryResponse', ['retrieved', 'stages', 'prompt', 'metrics', 'diagnosis', 'total_ms']],
    ['RetrievedChunkOut', ['doc_slug', 'score', 'rerank_score', 'original_rank']],
    ['AgentRunResponse', ['history', 'node_visits', 'looped', 'halted_reason', 'interrupted_at']],
    ['StepOut', ['node', 'state_diff', 'edge_taken', 'edge_reason', 'duration_ms']],
    ['MentorResponseOut', ['level', 'message', 'reveals_answer', 'next_level', 'trace']],
    ['EvalRunResponse', ['metrics', 'per_case', 'verdict', 'reasons', 'cases_passed']],
  ])('%s exposes the fields the UI reads', (name, expected) => {
    const actual = props(name);
    expect(actual.length, `${name} is missing from the schema`).toBeGreaterThan(0);
    for (const field of expected) {
      expect(actual, `${name}.${field} is missing`).toContain(field);
    }
  });

  it('challenge payloads never carry the solution', () => {
    // The single most important leak to guard: a player must not be able to
    // read the answer out of the network tab.
    const challenge = props('ChallengeOut');
    expect(challenge).not.toContain('reference_solution');
    expect(challenge).not.toContain('tests');
    expect(challenge).toContain('visible_tests');
  });

  it('generated questions carry their rejection reasons', () => {
    // The content agent is allowed to produce bad questions; it is not allowed
    // to produce bad questions that look fine. `issues` is how the UI knows.
    const generated = props('GeneratedQuestionOut');
    expect(generated).toEqual(expect.arrayContaining(['issues', 'is_usable', 'rubric']));
  });

  it('question payloads never reveal which option is correct', () => {
    const option = props('QuestionOptionOut');
    expect(option).toEqual(expect.arrayContaining(['id', 'text']));
    expect(option).not.toContain('correct');
    expect(option).not.toContain('why');

    const question = props('QuestionOut');
    expect(question).not.toContain('expected_answer');
    expect(question).not.toContain('rubric');
  });
});
