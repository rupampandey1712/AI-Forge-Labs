# API Reference

Base URL: `/api/v1` · Interactive docs: `http://localhost:8000/docs`

The machine-readable source of truth is `openapi.json` at the repo root,
regenerated with `python -m app.cli openapi` and verified fresh by CI.

---

## Conventions

### Errors

Every error — validation, domain, HTTP, unexpected — returns the same envelope:

```json
{
  "error": {
    "code": "content_locked",
    "message": "Reach level 6",
    "details": { "slug": "m-python-boss-framework" }
  }
}
```

| Status | Code                 | Meaning                                          |
| ------ | -------------------- | ------------------------------------------------ |
| 401    | `unauthenticated`    | Missing, expired, malformed or wrong-type token  |
| 403    | `permission_denied`  | Authenticated, not allowed                       |
| 404    | `not_found`          | No such resource, **or not yours**               |
| 408    | `sandbox_timeout`    | Submitted code exceeded its wall clock           |
| 409    | `conflict`           | Duplicate, or a state-machine violation          |
| 422    | `validation_failed`  | `details.fields[]` carries per-field messages    |
| 423    | `content_locked`     | A gameplay rule, not a bug — message says why    |
| 429    | `rate_limited`       | `Retry-After` header set                         |
| 500    | `internal_error`     | `details.request_id` correlates with the logs    |

A 422 always carries field-level detail so a form can render errors next to
their inputs:

```json
{"error": {"code": "validation_failed", "message": "Some fields are invalid.",
 "details": {"fields": [{"field": "password", "message": "Password needs 16+ characters…",
                         "type": "value_error"}]}}}
```

Resources belonging to another player return **404, not 403** — a 403 confirms
the resource exists, which is an enumeration oracle.

### Headers

| Header                   | Direction | Purpose                                     |
| ------------------------ | --------- | ------------------------------------------- |
| `Authorization: Bearer`  | →         | Access token                                |
| `X-Request-ID`           | ↔         | Echoed, or generated; correlates with logs  |
| `Server-Timing`          | ←         | Backend duration, visible in browser devtools |
| `X-RateLimit-Remaining`  | ←         | Requests left this minute                   |

---

## Auth

| Method | Path                    | Notes                                            |
| ------ | ----------------------- | ------------------------------------------------ |
| POST   | `/auth/register`        | Creates user + profile + all 16 skill rows       |
| POST   | `/auth/login`           | `identifier` accepts email **or** username       |
| POST   | `/auth/refresh`         | **Rotates**: the old token is revoked            |
| POST   | `/auth/logout`          | `?all_sessions=true` revokes every session       |
| GET    | `/auth/me`              |                                                  |
| POST   | `/auth/change-password` | Revokes every other session                      |

**Refresh rotation and reuse detection.** Each refresh issues a new token and
revokes the old `jti`. Presenting an already-rotated token is the stolen-token
signature, so it revokes **every** session for that user — including the
legitimate one — and forces re-authentication.

Password policy: 16+ characters, *or* 8+ with at least 3 of
{lowercase, uppercase, digit, symbol}. Length is the dominant strength factor,
so a passphrase passes without symbol gymnastics.

---

## Player

| Method | Path                          | Notes                                      |
| ------ | ----------------------------- | ------------------------------------------ |
| GET    | `/player/profile`             |                                            |
| PATCH  | `/player/profile`             | display name, avatar, mentor persona        |
| GET    | `/player/dashboard`           | **One fat payload** — see below             |
| GET    | `/player/world`               | 14 buildings + unlock state + alerts        |
| GET    | `/player/skills`              | All 16, for the radar chart                 |
| GET    | `/player/skills/{skill_slug}` | One tree with per-node mastery              |
| GET    | `/player/badges`              | Secret + unearned render as `???`           |
| GET    | `/player/achievements`        | With progress toward `target`               |
| GET    | `/player/xp`                  | The append-only ledger                      |
| GET    | `/player/leaderboard`         |                                             |

`/player/dashboard` returns profile, skills, retention alerts, due count, recent
events, recommendations, open mistakes, unseen badges and the streak calendar in
one response. **Why one fat endpoint**: the dashboard needs all of it to draw a
first frame, and six round trips on a cold load is how a "fast" SPA feels slow.

---

## Content

| Method | Path                            | Notes                                           |
| ------ | ------------------------------- | ----------------------------------------------- |
| GET    | `/concepts`                     | Filter by category, skill, node, search         |
| GET    | `/concepts/{slug}`              | Includes prerequisites and what it leads to     |
| GET    | `/challenges`                   |                                                 |
| GET    | `/challenges/{slug}`            | **Visible tests only**                          |
| POST   | `/challenges/{slug}/submit`     | The core game loop                              |
| GET    | `/challenges/{slug}/hint`       | One at a time; costs coins                      |
| GET    | `/questions/random`             | Excludes anything seen in 45 days               |
| GET    | `/questions/{slug}`             |                                                 |
| POST   | `/questions/{slug}/submit`      |                                                 |
| POST   | `/code/execute`                 | Free-form sandbox run — **not graded**          |

### What never appears in a response

| Field                              | Why                                            |
| ---------------------------------- | ---------------------------------------------- |
| `Challenge.reference_solution`     | It is the answer                               |
| `Challenge.tests` (hidden ones)    | Reconstructable suite ⇒ hard-codeable solution |
| `QuestionOption.correct` / `.why`  | It is the answer                               |
| `Question.expected_answer`         | It is the answer                                |
| `Question.rubric`                  | Reveals exactly which keywords score            |

Enforced structurally — the player-facing schema does not have those fields — and
asserted by `frontend/src/test/contract.test.ts` against the OpenAPI schema.

Hidden test *results* report only pass/fail and the test name. Returning the
expected value on failure would let a player reconstruct the suite by submitting
garbage and reading the diffs.

### Submitting a challenge

```http
POST /api/v1/challenges/py-dedupe-preserve-order/submit
{
  "code": "def dedupe(items):\n    return list(dict.fromkeys(items))",
  "elapsed_seconds": 142,
  "hints_used": 0,
  "explanation": "The naive version is O(n^2) because `x in result` is a linear scan…",
  "complexity": "O(n)",
  "confidence": 0.85
}
```

```json
{
  "passed": true, "score": 1.0, "tests_passed": 6, "tests_total": 6,
  "headline": "✅ All tests green",
  "explanation_score": 0.72,
  "explanation_feedback": "Solid, but not yet a senior answer. Still missing: …",
  "detected_mistakes": [],
  "progression": {
    "xp_gained": 74, "leveled_up": false, "progress_pct": 61.2,
    "grants": [
      {"source": "challenge_passed",  "amount": 32, "reason": "Tier 3 objective cleared"},
      {"source": "first_attempt_bonus","amount": 9, "reason": "Solved on the first attempt"},
      {"source": "explanation_bonus", "amount": 8, "reason": "Explained the WHY"}
    ],
    "new_badges": ["first-commit"]
  },
  "mastery_delta": {
    "python-list-vs-tuple-vs-set-vs-dict": {"before": 0.17, "after": 0.33, "next_review_days": 3.5}
  },
  "next_review_at": "2026-09-18T00:53:57Z"
}
```

`run_only: true` executes visible tests and returns feedback **without**
recording an attempt, awarding XP or touching the retention model — experimentation
must be free of consequences.

On failure the response carries `headline`, `what_happened`, `root_cause` and
the next `hint`; after four genuine attempts, `reveal_solution` flips true and
`solution` + `solution_explanation` are included.

---

## Gameplay

| Method | Path                            | Notes                                       |
| ------ | ------------------------------- | ------------------------------------------- |
| GET    | `/missions`                     | Locked missions included, with the reason    |
| GET    | `/missions/{slug}`              | **423** if locked; debrief withheld until passed |
| POST   | `/missions/{slug}/start`        | Introduces concepts to the retention model  |
| POST   | `/missions/{slug}/step`         | Step XP is deferred to completion            |
| POST   | `/missions/{slug}/complete`     | Passes on the **mean** of required steps     |
| GET    | `/daily-challenge`              | Generated once per day; **cannot be rerolled** |
| POST   | `/daily-challenge/submit`       | Mark a slot complete                        |
| GET    | `/retention`                    | Decay, alerts, 90-day forecast              |
| GET    | `/retention/due`                | Sorted by urgency, not by date              |
| GET    | `/mistakes`                     | Named patterns with clean-streak progress   |
| POST   | `/interview/start`              | `level`, `mode: standard\|pressure`         |
| POST   | `/interview/{id}/answer`        | Returns feedback **and** the next turn      |
| GET    | `/interview/{id}/report`        | Verdict, dimensions, per-question debrief   |
| GET    | `/analytics/progress`           | Mastery, trends, composite scores           |
| GET    | `/analytics/readiness`          | **With the components that produced it**    |
| GET/POST | `/journal`                    | Engineering journal                         |

Every daily slot carries a `reason` string. That is not decoration — a training
plan the player understands is one they trust.

`/analytics/readiness` never returns a bare number. `components[]` gives each
input's weight, current value, contribution and **headroom**, so "where does an
hour of work buy the most" is answerable from the response.

---

## Health

| Path             | Checks                           | On failure                        |
| ---------------- | -------------------------------- | --------------------------------- |
| `/health/live`   | Nothing                          | **Restart the container**          |
| `/health/ready`  | Database, cache, sandbox         | **Remove from LB, do not restart** |
| `/health/info`   | Non-secret runtime configuration | —                                  |

Conflating liveness and readiness turns a brief database blip into a restart
loop. Redis being down degrades performance but not correctness, so it reports
`degraded` without failing readiness.

---

## Rate limiting

240 requests/minute per client by default (`RATE_LIMIT_PER_MINUTE`), sliding
window.

**Stated limitation**: the limiter counts per *process*. With four workers the
real limit is 4× the configured value and it resets on deploy. That is fine for
a single-player game and is left visible rather than hidden behind a class named
`DistributedRateLimiter` that is not one. The production answer is Redis (a
sorted set per key) or the ingress — and Backend City has the player build
exactly that.
