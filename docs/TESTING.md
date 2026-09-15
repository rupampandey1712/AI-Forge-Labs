# Testing

264 backend tests + 62 frontend contract tests. This document explains the
strategy, and — more usefully — **what is deliberately not mocked and why**.

---

## The shape

| Suite                          | Count | Speed | What it protects                          |
| ------------------------------ | ----- | ----- | ----------------------------------------- |
| `tests/unit/`                  | 63    | <1s   | The pure engines — properties, not numbers |
| `tests/integration/test_auth_api.py` | 22 | ~3s | Auth, and the attacks it resists          |
| `tests/integration/test_game_loop.py` | ~30 | ~20s | The whole loop, over real HTTP           |
| `tests/integration/test_sandbox_security.py` | ~25 | ~15s | The sandbox's security contract   |
| `tests/integration/test_content_integrity.py` | ~120 | ~10s | Content that is actually solvable |
| `frontend/src/test/contract.test.ts` | 62 | ~1s | Frontend/backend drift                 |

```bash
pytest                     # everything
pytest tests/unit -q       # the engines, sub-second
pytest -m "not slow"       # skip sandbox + solvability
pytest -m integration      # HTTP and database only
```

---

## What is never mocked

This is the part worth arguing about, so here is the argument.

| Component        | Mocked? | Reasoning                                                                 |
| ---------------- | ------- | ------------------------------------------------------------------------- |
| **Database**     | No      | Real SQLite (and Postgres in CI). An ORM mock tests your mock's opinion of SQLAlchemy, not SQLAlchemy. Every N+1 and every lazy-load-after-commit bug would be invisible. |
| **The sandbox**  | No      | It executes real subprocesses. Its correctness *is* process isolation, timeouts and kill semantics — none of which a fake has. |
| **HTTP layer**   | No      | `httpx.ASGITransport` runs the real app: real middleware, real dependency graph, real exception handlers. No network, no server. |
| **The engines**  | No      | They are pure. There is nothing to mock.                                   |
| **Content**      | No      | Reference solutions are *executed* against their own hidden tests.          |
| **Time**         | **Injected** | Not mocked — passed in. Every retention function takes `now=`, so a year of forgetting runs in microseconds and deterministically. |
| **LLM**          | **Swapped** | The offline `MockProvider` is deterministic (seeded by a prompt hash), which is what makes AI features testable at all. |

The only thing genuinely faked is the LLM, and it is faked by a *real
implementation of the same interface* rather than by a patch.

### Why not a transactional-rollback fixture

It is faster, and it breaks the moment the code under test calls `commit()` —
which ours does, because the request *is* the unit of work. Testing under a
different transaction model than production runs is precisely how "passes in CI,
fails in prod" happens.

Instead: a fresh in-memory SQLite database per test, created from
`Base.metadata`. ~30ms, and guaranteed clean — which removes the single biggest
source of flaky suites, order dependence.

`StaticPool` is required: in-memory SQLite is per-connection, so without it the
schema created in the fixture is invisible to the code under test and everything
fails with "no such table".

---

## Property tests over example tests

The engines assert **properties**, not magic numbers:

```python
def test_curve_is_strictly_increasing(self):
    values = [total_xp_for_level(lv) for lv in range(1, MAX_LEVEL + 1)]
    assert all(b > a for a, b in pairwise(values))

def test_grinding_tier_one_cannot_beat_deep_work(self):
    """The core balance guarantee: depth must dominate volume."""
    assert tier9_award > tier1_award * 10
```

`assert total_xp_for_level(22) == 13048` fails the moment anyone tunes the
curve — *including when the tuning is correct*. A property test survives balance
changes and still catches real breakage.

Properties currently guarded: curve monotonicity and invertibility, rank
monotonicity, award ordering across all ten tiers, streak-bonus capping,
logarithmic optimisation scaling, retrievability monotonic decay, interval and
ease bounds, mastery ceilings, and the savings floor.

---

## Content integrity — the highest-value suite

`test_content_integrity.py` is the one that catches bugs no other test can.

```python
@pytest.mark.parametrize("challenge", ALL_CHALLENGES, ids=lambda c: c.slug)
async def test_every_reference_solution_passes(self, challenge):
    """Execute every authored solution against its own hidden suite."""
```

Content that *claims* to be solvable but is not is the worst bug a learning
product can ship, and it is invisible to unit tests, integration tests and code
review alike. So the suite executes it.

It also asserts:

- Every `broken_code` **actually fails** — a "debug this" challenge whose
  starting code already passes is pointless
- No prerequisite cycles in the knowledge graph (content would be permanently
  unreachable)
- No prerequisite harder than its dependent
- Every MCQ distractor has a `why` — a distractor without an explanation
  teaches nothing when the player picks it
- Every free-text question has a rubric, or it cannot be graded at all
- **Every question's own ideal answer scores ≥ 0.6 correctness against its own
  rubric.** If the model answer cannot pass the grader, the rubric is wrong.
- A naive answer scores at least 2 points *below* the ideal one — proving the
  grader discriminates rather than just matching keywords
- Every badge/achievement criteria key is one the rules engine understands, so
  a badge can never be unearnable because of a typo

---

## Sandbox security tests

These encode a **contract**, not behaviour. A failure there is a security
incident, not a flaky test.

```python
async def test_secrets_are_not_inherited(self, sandbox):
    """A print(os.environ) must never be a credential dump."""

async def test_the_game_process_is_unaffected_by_a_crash(self, sandbox):
    """Execution happens in a separate process — the API must survive anything."""

def test_runner_imports_nothing_from_the_app():
    """The runner must stay copyable into a minimal container with no app code."""
```

The last one parses `runner_main.py`'s AST and fails if anyone adds an `app.`
import. The entire isolation argument rests on that file being standalone, so
it is verified rather than assumed — and CI additionally checks the built
sandbox image contains nothing but that one file.

The suite also asserts what the pre-screen **allows**: `import os`, `import sys`,
`asyncio`, custom `__eq__`. Over-blocking would teach players to write worse
Python to please the grader, which is worse than the risk it avoids.

---

## The frontend contract suite

`src/types/api.ts` is hand-written. The drift risk is real, so it is closed by a
test rather than by discipline:

```ts
it.each(CALLS)('%s %s exists in the backend', (method, path) => { … });

it('the client covers every non-admin endpoint the backend exposes', () => { … });

it('challenge payloads never carry the solution', () => {
  expect(props('ChallengeOut')).not.toContain('reference_solution');
});
```

A backend rename therefore fails the **frontend** build, which is where the
broken call site lives. CI also fails if `openapi.json` is stale, because a
drifted schema means this suite is checking a fiction.

---

## Bugs this suite has already caught

Not hypothetical — these were found by the tests during development:

| Bug                                                        | Found by                             |
| ---------------------------------------------------------- | ------------------------------------ |
| Badge criteria evaluated **before** the counters they read  | `test_badges_unlock_from_declarative_criteria` |
| Mission steps held to the interview *hire* bar (6.0/10)     | `test_start_step_and_complete`       |
| Refresh-reuse revocation silently undone by the rollback    | `test_reuse_revokes_every_session`   |
| Rubric keywords containing `(`/`^` never matched anything   | End-to-end smoke of a real answer    |
| `mastery_ceiling(0)` contradicting its own caller           | `test_mastery_ceiling_lookup`        |
| Blocking `pathlib` I/O inside an `async def`                | `ruff`'s `ASYNC240`                  |

The rubric bug is the instructive one: every `correctness` score for answers
using `O(n^2)` notation was silently zero, and no test that mocked the grader
would ever have found it.

---

## CI

| Job               | Gate                                                              |
| ----------------- | ----------------------------------------------------------------- |
| `lint`            | ruff check + format, fails in ~40s                                |
| `content`         | Pack validation + **openapi.json freshness**                      |
| `backend-tests`   | Full suite against **SQLite and PostgreSQL**                      |
| —                 | Alembic up → down → up (a migration you cannot reverse…)           |
| —                 | Seeding twice is a no-op (a re-seed runs on every deploy)          |
| `typecheck`       | mypy strict on `app/game` + `app/domain` (advisory)               |
| `frontend`        | typecheck, lint (`--max-warnings 0`), contract tests, build       |
| `security`        | pip-audit, sandbox invariants, secret scan                        |
| `docker`          | Three images build; **sandbox image contains only the runner**    |
| `ci-passed`       | One required check for branch protection                          |

Both database dialects run because they have genuinely different behaviour —
JSON containment, `ALTER TABLE`, timezone handling — and both are supported
paths.

---

## Adding a test

**A new engine rule** → `tests/unit/`, as a property if you can state one.

**A new endpoint** → `tests/integration/`, over real HTTP via the `seeded_client`
fixture, and add the path to the frontend `CALLS` list.

**New content** → nothing to write. The parametrised integrity suite picks it up
automatically and will execute your reference solution.

**A bug fix** → a test that fails before the fix. All six bugs listed above have
one.
