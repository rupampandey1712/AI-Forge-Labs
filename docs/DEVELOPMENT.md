# Development

## Setup

```bash
git clone <repo> && cd "Python RPG"

# Backend
cd backend
python -m venv .venv
. .venv/Scripts/activate            # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
python -m app.cli bootstrap --simulate-days 45
uvicorn app.main:app --reload

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

`http://localhost:5173` · sign in with `player@aiforge.dev` / `forge-me-2026`.

Vite proxies `/api` to `localhost:8000`, so the browser sees one origin and CORS
never enters the picture locally.

### Optional extras

```bash
pip install -e ".[ml]"    # numpy/pandas already in base; adds torch, sklearn, matplotlib
pip install -e ".[ai]"    # langchain, langgraph, langsmith, anthropic
```

Base install stays fast on purpose — torch alone is ~2GB and CI does not need it.

---

## The CLI

```bash
python -m app.cli bootstrap --simulate-days 45   # schema + seed + demo player
python -m app.cli create-schema                  # SQLite dev only; Postgres uses Alembic
python -m app.cli seed [--strict]                # idempotent; safe on a live database
python -m app.cli content-check                  # validate packs, no database needed
python -m app.cli openapi                        # regenerate openapi.json
python -m app.cli demo-user --simulate-days 60
python -m app.cli stats
```

`--simulate-days` replays attempts through the **real** engines rather than
writing rows directly. Simulated data that bypassed the engine would not
exercise it, and the demo would show numbers the real game cannot produce.

---

## Verification loop

```bash
# Backend
pytest                                   # 264 tests, ~45s
pytest tests/unit -q                      # pure engines, <1s
pytest -m "not slow"                      # skip sandbox + solvability
ruff check app tests --fix
ruff format app tests
mypy app/game app/domain                  # strict where it pays

# Frontend
npm run typecheck
npm run lint
npm run test                              # contract suite
npm run build
```

CI runs all of it, plus the backend suite against **both** SQLite and
PostgreSQL, plus an Alembic up/down/up round trip, plus a re-seed idempotency
check.

---

## Migrations

```bash
# After changing a model
alembic revision --autogenerate -m "add x to y"
alembic upgrade head

# Always verify it reverses — a migration you cannot roll back is one you
# cannot deploy on a Friday.
alembic downgrade -1 && alembic upgrade head
```

`alembic/env.py` has a `render_item` hook that flattens our custom column types
to plain SQLAlchemy in the generated file. Without it, migrations would emit
`app.db.types.UTCDateTime()` and a rename six months from now would break every
historical migration. **Migrations must be replayable with nothing but
SQLAlchemy.**

---

## Adding content

Content is typed Python in `app/content/packs/`. The format lives in
`app/content/schema.py`.

### 1. A concept

```python
ConceptSpec(
    slug="python-asyncio-event-loop",
    title="The Event Loop",
    category=Category.PYTHON,
    skill_node="python.asyncio",      # must exist in skills/registry.py
    difficulty=6,
    summary="One thread, a queue of ready callbacks, and why one sleep() ruins it.",
    explanation="""...""",            # teach the MECHANISM, not the syntax
    examples=[example("...", "code", output="...", note="...")],
    common_mistakes=[mistake("...", why="...", fix="...", severity=Severity.CRITICAL)],
    real_world_usage=["..."],
    requires=["python-generators"],   # hard prerequisite — gates content
    related=["fastapi-async"],        # soft link — drives recommendations
)
```

### 2. A challenge

```python
ChallengeSpec(
    slug="py-fix-blocking-endpoint",
    tier=T.DEBUG,
    broken_code="...",                # present ⇒ this is a debug challenge
    reference_solution="...",
    solution_explanation="...",       # revealing a solution must also TEACH
    tests=[
        eq("happy path", "solve([1,2])", [1,2]),
        eq("edge", "solve([])", [], hidden=True),      # at least one hidden
        script("is not quadratic", "...", hidden=True, points=2.0),
    ],
    concepts=["python-asyncio-event-loop"],
    hints=["...", "...", "..."],      # escalating, never the answer
    explanation_prompts=[point("Names the event loop", "event loop", weight=2)],
)
```

Test kinds: `eq`, `approx`, `raises`, `predicate`, `script`, `prints`.
Use `predicate` when many answers are correct ("returns a generator", "is
sorted", "did not mutate the input") — testing an exact value there grades style
instead of correctness.

### 3. Register and verify

```python
# app/content/registry.py
_PACK_MODULES = (python_core, your_pack, meta)
```

```bash
python -m app.cli content-check
python -m app.cli seed
pytest tests/integration/test_content_integrity.py
```

The integrity suite **executes every reference solution against its own hidden
tests**, and asserts that every `broken_code` actually fails. Content that
claims to be solvable but is not is the worst bug a learning product can ship,
and it is invisible to every other kind of test.

It also checks: no prerequisite cycles, no prerequisite harder than its
dependent, every MCQ distractor has an explanation, every free-text question has
a rubric — and that **each question's own ideal answer scores ≥ 0.6 correctness
against its own rubric**. If the model answer cannot pass the grader, the rubric
is wrong.

---

## Adding an endpoint

1. Schema in `app/schemas/` — separate player-facing and internal models if the
   data contains anything the player must not see.
2. Service method in `app/services/` — raise `ForgeError` subclasses, never
   `HTTPException`.
3. Route in `app/api/routes/` — thin; let the exception handlers map errors.
4. Client method in `frontend/src/lib/api.ts` + types in `src/types/api.ts`.
5. Add the path to `CALLS` in `frontend/src/test/contract.test.ts`.
6. `python -m app.cli openapi` and commit the schema.

Step 6 is enforced: CI fails if `openapi.json` is stale, because a drifted
schema means the contract test is checking a fiction.

---

## Conventions

**Backend**
- Type hints everywhere; `mypy` strict on `app/game` and `app/domain`.
- Services never import FastAPI.
- `app/game/` imports nothing but `app/domain` and the stdlib.
- Comments explain **why**, not what. If a decision has a cost, name it.
- `async def` only when something is actually awaited — `ruff`'s `ASYNC` rules
  are enabled and they have already caught a real blocking-I/O-in-async bug in
  this codebase.

**Frontend**
- Server state belongs to React Query. Zustand holds auth and the reward queue
  only. Duplicating the profile into a store is how two pages end up showing
  different XP.
- `noUnusedLocals`/`noUnusedParameters` are on; `npm run lint` is
  `--max-warnings 0`.
- Never `style.display` for visibility toggles.

---

## Debugging

```bash
LOG_LEVEL=DEBUG DB_ECHO=true uvicorn app.main:app --reload   # see every query
SANDBOX_MODE=disabled uvicorn app.main:app --reload           # rule out the sandbox
```

Every response carries `x-request-id`; grep the logs for it. `Server-Timing`
shows backend duration natively in browser devtools.

```bash
curl localhost:8000/api/v1/health/ready | python -m json.tool
```

---

## Sandbox modes

| Mode         | When                                                                    |
| ------------ | ----------------------------------------------------------------------- |
| `subprocess` | Local single-player development. Default.                               |
| `docker`     | Anything shared. Build the image first (below).                         |
| `disabled`   | Debugging the rest of the app; returns a clear error instead of running. |

```bash
docker build -f infra/docker/sandbox.Dockerfile -t aiforge-sandbox:latest backend
SANDBOX_MODE=docker uvicorn app.main:app --reload
```

Before touching anything under `app/sandbox/`, read the security posture note at
the top of `runner_main.py`. `tests/integration/test_sandbox_security.py`
encodes the contract — a failure there is a security incident, not a flaky test.
