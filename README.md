# AI Forge Labs

**Learn it. Build it. Break it. Debug it. Explain it. Master it.**

An engineering simulator for Python, backend, data, ML, deep learning, LLM, RAG
and agent work. You join a fictional company as a **Python Apprentice** and work
toward **Principal AI Engineer** through production incidents, broken pipelines,
architecture reviews and interviews that do not accept a memorised answer.

It is not a course. There is no "read this and click Next".

---

## The one thing that makes this different

Most learning tools let you finish and forget. This one **models what you are
losing**.

Every concept you practise gets a memory state — stability, ease, mastery — and
a forgetting curve. Stop touching generators for a month and the dashboard says
so, in your numbers:

```
⚠ PYTHON KNOWLEDGE DECAY DETECTED
Your Python mastery dropped from 91% → 68%. Four concepts including
"Generators" have not been practised for 32 days.

  → Repair the Data Pipeline        emergency mission · ~18 min
```

Tomorrow's daily mission is then built *from that decay*, and every slot tells
you why it was chosen. That is the whole product thesis: a training tool is only
worth anything if it is still useful a year later.

---

## Run it

### Fastest path — no infrastructure

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"

python -m app.cli bootstrap --simulate-days 45        # schema + content + a player with history
uvicorn app.main:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173> and sign in with `player@aiforge.dev` /
`forge-me-2026`.

`--simulate-days 45` back-dates real practice history through the real engines,
so the retention dashboard, the decay alerts and the analytics charts have
something to show on the first screen. Without it you get a correct but empty
dashboard, which hides the most important feature.

No PostgreSQL required: with `DATABASE_URL` unset the app falls back to SQLite
via aiosqlite. Same SQLAlchemy programming model, zero setup.

### Full stack

```bash
cp .env.example .env          # edit SECRET_KEY before anything real
docker compose up --build
```

| Service    | URL                            |
| ---------- | ------------------------------ |
| Frontend   | <http://localhost:5173>        |
| API + docs | <http://localhost:8000/docs>   |
| PostgreSQL | `localhost:5432` (forge/forge) |
| Redis      | `localhost:6379`               |

Compose runs migrations and seeding as one-shot jobs that must succeed before
the backend starts, so there is no start-crash-restart race.

---

## What is in the box

### The world

Fourteen districts, unlocking as you rank up.

| District                        | What it trains                                             |
| ------------------------------- | ---------------------------------------------------------- |
| **Python Academy**              | Syntax → object model, generators, decorators, asyncio      |
| **Backend City**                | FastAPI, Pydantic, SQLAlchemy, PostgreSQL, query plans      |
| **Data Science Lab**            | NumPy, pandas, matplotlib on realistic, dirty data          |
| **ML Arena**                    | Supervised/unsupervised, evaluation, leakage, bias/variance |
| **Deep Learning Lab**           | PyTorch: tensors, autograd, training loops that diverge     |
| **Transformer Research Center** | Tokenization → attention → a working block                  |
| **RAG Tower**                   | Chunking, retrieval, reranking, grounding, evaluation       |
| **Agent Factory**               | LangChain primitives, LangGraph state machines              |
| **Production City**             | Testing, Docker, CI/CD, observability                       |
| **Interview Arena**             | Junior → Principal, scored on seven dimensions              |
| **Architecture Tower**          | System design from one box to global                        |
| **Debugging Dungeon**           | Memory leaks, races, N+1, blocked event loops               |
| **AI War Room**                 | Timed production incidents across the whole stack           |
| **Staff Engineer HQ**           | Platform design, trade-off defence, the capstone            |

### The ten-tier ladder

The single most important design decision. A concept is not "done" at tier 3.

| Tier | Level                   | Example (decorators)                                       |
| ---- | ----------------------- | ---------------------------------------------------------- |
| 1    | Remember                | What is a decorator?                                        |
| 2    | Understand              | Why is `@x` just `f = x(f)`?                                |
| 3    | Implement               | Write a `@retry(3)` decorator                               |
| 4    | Debug                   | This decorator broke FastAPI's request model. Why?          |
| 5    | Optimize                | Four decorators deep and every call is slow. Fix it.        |
| 6    | Design                  | Design a cross-cutting concern layer                        |
| 7    | Explain                 | Explain `functools.wraps` to a mid-level engineer           |
| 8    | Production              | Sentry groups every error under `wrapper`. Root cause?      |
| 9    | Staff trade-off         | Keep this decorator-heavy framework? Argue it.              |
| 10   | Principal architecture  | Design the platform's extensibility model                   |

Mastery is **capped by the deepest tier you have actually cleared**. Answering
tier-1 questions forever cannot take Python past 25%.

### The engines

| Engine                | What it does                                                                   |
| --------------------- | ------------------------------------------------------------------------------ |
| **XP / progression**  | Itemised, attributable awards. Depth always out-earns volume.                   |
| **Retention**         | Exponential forgetting curve + adaptive SM-2 scheduling                         |
| **Rubric grader**     | Seven dimensions; discriminates junior 0.4 / mid 5.0 / senior 7.6 / staff 9.3   |
| **Mistake detector**  | AST analysis producing *named, reusable* patterns                               |
| **Daily generator**   | Repair → mistake → frontier → breadth → interview, with reasons                 |
| **Interview**         | Adapts difficulty, follows up on strong answers, writes a debrief               |

All of them are pure functions with no I/O, unit-tested in milliseconds.

---

## Architecture

```
React + TypeScript + Vite
          │  /api  (nginx proxy — one origin, no CORS)
          ▼
      FastAPI  ──────────────────────────────────┐
          │                                      │
    ┌─────┼─────┬──────────┬──────────┐          │
    ▼     ▼     ▼          ▼          ▼          ▼
PostgreSQL  Redis   Worker   LLM gateway   SANDBOX (isolated)
(SQLAlchemy  (cache)  (jobs)  (Gemini /     ├─ subprocess (dev)
 2.0 async)                    Anthropic /  └─ docker     (prod)
                               OpenAI /
                               offline mock)
```

**Layering**: routes → services → repositories → models, with the pure game
engines (`app/game/`) depending on nothing at all. Services raise domain errors;
the API layer is the single place that maps them to HTTP.

See **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the reasoning behind each
boundary, including the ones deliberately *not* drawn.

---

## Code execution safety

The game server **never executes player code in-process**.

| Layer               | What it guarantees                                                      |
| ------------------- | ----------------------------------------------------------------------- |
| Static pre-screen   | AST rejects network/process imports and escape reflection before spawn   |
| Admission control   | Bounded semaphore — 20 infinite loops cannot take down the host          |
| JSON protocol       | Nothing but plain data crosses the boundary                              |
| Standalone runner   | Imports *nothing* from the app; enforced by a test                       |
| Subprocess backend  | Separate process, rlimits, scrubbed env, wall-clock kill of the tree     |
| Docker backend      | `--network none --read-only --cap-drop ALL --user 65534 --pids-limit 64` |

The subprocess backend is honest defence-in-depth for local single-player use;
`SANDBOX_MODE=docker` is the answer for anything shared. Both are documented
with their actual limits in `app/sandbox/runner_main.py` — because a sandbox
that oversells itself is more dangerous than one that does not exist.

---

## LLM providers

Every AI feature works **with no API key**. The offline mock is deterministic,
which is what makes the evaluation labs reproducible and the AI features
testable at all.

```bash
LLM_PROVIDER=gemini      # or anthropic | openai | mock
GEMINI_API_KEY=...
LLM_MODEL=               # blank = provider default
```

Adding a provider is one class and one line — see `app/ai/llm/providers.py`.

---

## Project layout

```
backend/
  app/
    api/          routes, dependencies, middleware
    core/         config, security, logging, errors, cache
    db/           engine, session, base, portable column types
    models/       37 SQLAlchemy tables
    schemas/      Pydantic contracts (player-facing ≠ internal)
    repositories/ query reuse; services may still write raw SQL
    services/     the orchestration layer
    game/         PURE engines: xp, retention, grading, skills, achievements
    ai/           llm gateway, embeddings, rag, agents, evaluation
    sandbox/      protocol, standalone runner, subprocess + docker backends
    content/      typed authoring format, validation, idempotent seeder
    workers/      background scheduler
  tests/          unit (pure engines) + integration (HTTP, sandbox, content)
  alembic/        self-contained migrations

frontend/
  src/
    pages/        18 screens
    components/   ui primitives, game widgets, layout
    lib/          typed API client with single-flight token refresh
    stores/       auth + reward queue (server state lives in React Query)
    types/        hand-written API mirrors, guarded by a contract test

infra/docker/     the sandbox image
docs/             architecture, game design, learning path, API, testing…
```

---

## Development

```bash
# Backend
pytest                                  # 264 tests
ruff check app tests && ruff format app tests
mypy app/game app/domain                # strict where it pays
python -m app.cli content-check         # validate every content pack
python -m app.cli openapi               # regenerate the API contract

# Frontend
npm run typecheck && npm run lint && npm run test && npm run build
```

`npm run test` runs the contract suite: it verifies every endpoint the client
calls exists in the backend's OpenAPI schema, and that player-facing payloads
never contain reference solutions or correct-answer flags.

See **[DEVELOPMENT.md](docs/DEVELOPMENT.md)** for the full workflow, including
how to add a content pack.

---

## Documentation

| Document                                            | What it covers                                     |
| --------------------------------------------------- | -------------------------------------------------- |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md)             | Every boundary, and why it is where it is           |
| [GAME_DESIGN.md](docs/GAME_DESIGN.md)               | Progression, rewards, retention model, difficulty   |
| [LEARNING_PATH.md](docs/LEARNING_PATH.md)           | The curriculum, band by band                        |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md)               | Setup, workflow, authoring content                  |
| [API.md](docs/API.md)                               | Endpoint reference and error contract               |
| [TESTING.md](docs/TESTING.md)                       | Strategy, what is mocked and what is never mocked   |
| [AI_ARCHITECTURE.md](docs/AI_ARCHITECTURE.md)       | LLM gateway, evaluation, observability              |
| [RAG.md](docs/RAG.md)                               | The RAG pipeline and its failure modes              |
| [INTERVIEW_GUIDE.md](docs/INTERVIEW_GUIDE.md)       | How answers are scored, and what each band adds     |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)       | Things that go wrong, and why                       |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md)                 | Azure Container Apps, the sandbox split, cost       |
| [ADR-001](docs/adr/ADR-001-modular-monolith-with-one-split.md) | Why one service split and not ten        |

---

## An honest note on "10 years of experience"

The game models the **problems an engineer at each band is expected to solve**.
It does not claim that finishing it hands you the years, and it never will —
that claim would be both false and insulting to the thing it is trying to teach.

What it can do is make sure that when you meet those problems for real, you have
met their shape before, been wrong about them in a safe place, and had to
explain your reasoning out loud.

---

## Status

Phase 1 complete and verified end to end: engines, sandbox, API, content
pipeline, frontend, Docker, CI. Content packs beyond Python Academy are the
in-progress work — the authoring format, the validation gate and the seeding
pipeline are built, so adding a pack is content, not plumbing.

## License

MIT
