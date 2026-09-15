# Architecture

This document explains **why** each boundary is where it is — including the ones
deliberately not drawn. Every abstraction in this codebase is supposed to have a
reason; where one does not, it should not exist.

---

## 1. The shape

```
┌─────────────────────────────────────────────────────────────────┐
│  React 18 + TypeScript + Vite                                   │
│  React Query (server state) · Zustand (auth + reward queue)     │
└───────────────────────────┬─────────────────────────────────────┘
                            │ /api/v1 — nginx proxies to backend
                            │ so the browser sees one origin
┌───────────────────────────▼─────────────────────────────────────┐
│  FastAPI                                                        │
│                                                                 │
│  api/routes ──► services ──► repositories ──► models            │
│       │             │                                            │
│       │             └──────► game/ (PURE — imports nothing)      │
│       │                                                          │
│       └──► middleware: request id · timing · headers · limiter   │
└──┬──────────┬──────────┬───────────┬──────────────┬─────────────┘
   │          │          │           │              │
   ▼          ▼          ▼           ▼              ▼
PostgreSQL  Redis    Worker     LLM gateway    SANDBOX
(async SA2) (cache)  (asyncio)  (4 providers)  (isolated process
                                               or container)
```

### Dependency direction

```
routes ──► services ──► repositories ──► models ──► db
   │           │
   └───────────┴──► game/ ──► domain/
                              (stdlib only)
```

Nothing points back up. `app/game/` imports only `app/domain/enums.py` and the
standard library — it cannot see SQLAlchemy, FastAPI or a settings object. That
is what makes the whole progression and retention model unit-testable in
milliseconds and reusable from the CLI, the seeder and the worker.

---

## 2. The layers, and what each one is for

### `app/domain/` — vocabulary

String enums for ranks, skills, categories, tiers, question kinds. Deliberately
**not** PostgreSQL `ENUM` types: adding a rank should be a code change, not a
migration containing an `ALTER TYPE` that cannot run inside a transaction.

### `app/game/` — the pure engines

| Module                    | Responsibility                                           |
| ------------------------- | -------------------------------------------------------- |
| `xp/engine.py`            | Level curve, ranks, itemised award rules                  |
| `retention/model.py`      | Forgetting curve, spaced repetition, mastery ceilings     |
| `grading/rubric.py`       | Seven-dimension free-text scoring                         |
| `grading/mistakes.py`     | AST mistake detection → named patterns                    |
| `skills/registry.py`      | 16 skills, 113 tree nodes, 14 buildings                   |
| `achievements/rules.py`   | Declarative criteria interpreter                          |

**Why pure matters here specifically.** These rules are the part of the product
most likely to be tuned and most expensive to get wrong. `tests/unit/` runs 63
of them in under a second, asserting *properties* (monotonicity, invertibility,
boundedness) rather than magic numbers — so balance changes do not invalidate
the suite, but genuine breakage still fails it.

### `app/repositories/` — query reuse, not an ORM wrapper

The usual justification for a repository ("so we can swap the database") is
fiction. It earns its place here for two real reasons:

1. **Eager-loading options live in one place.** The copy of a query that forgets
   `selectinload` is the one that ships the N+1.
2. **Services take a repository**, so a unit test can pass a fake.

What it deliberately does **not** do is hide SQLAlchemy. Services write bespoke
`select()` statements whenever a query is genuinely one-off. A repository that
forces everything through `find_by(**kwargs)` ends up reimplementing SQL badly.

### `app/services/` — orchestration

Where multi-step operations live. `GradingService.submit_challenge` is the
canonical example: sandbox execution → test grading → mistake detection →
explanation grading → XP award → retention update → mistake database →
learning event → failure framing.

Keeping that in one service is what guarantees those steps always happen
*together*. A challenge graded without a retention update would silently break
the single most important feature in the product.

Services raise `ForgeError` subclasses and never import FastAPI — which is why
the same code runs from the CLI, the seeder and the worker.

### `app/api/` — transport

Routes are thin. Exception handling is centralised in `main.py:install_exception_handlers`,
so the error envelope is identical across all 53 endpoints and the frontend can
rely on it.

---

## 3. Decisions worth defending

### Async everywhere

**Why**: the workload is I/O-bound — Postgres, Redis, sandbox subprocesses, LLM
calls that can take 40 seconds. One async worker holds thousands of in-flight
requests where a sync one would need a thread each.

**The cost, stated plainly**: a single blocking call poisons the entire event
loop. That is not a theoretical risk — it is the most common way an async
service ends up *slower* than the sync version it replaced. The mistake detector
flags `time.sleep()` inside `async def` as **critical** precisely because this
codebase would be hypocritical otherwise.

### The request is the unit of work

`get_session` commits on success and rolls back on exception. A mission
submission that awards XP, updates three skills, writes a learning event and
schedules a review either lands entirely or not at all.

**The one deliberate exception**: refresh-token reuse detection commits before
raising. The rollback would otherwise silently undo the revocation — the
security response would appear in the log and do nothing in the database. That
exception is commented at the call site, because an undocumented `commit()` in
a service is a bug waiting to be "cleaned up".

### `expire_on_commit=False`

With SQLAlchemy's default, touching any attribute after `commit()` triggers a
lazy refresh — which in async code raises `MissingGreenlet` rather than silently
issuing a query. Disabling expiry lets services return ORM objects the response
serialiser can safely read.

### SQLite *and* PostgreSQL

`app/db/types.py` uses `with_variant` so one model definition compiles to JSONB
on Postgres and JSON-as-text on SQLite, and a `UTCDateTime` decorator guarantees
aware UTC values on both (SQLite has no timezone support, so a naive value
read back would explode inside the retention engine's datetime arithmetic).

**Why carry the cost**: the single most common reason a learning project never
gets run is "install PostgreSQL first". CI runs the full suite against both.

### Denormalised counters on `PlayerProfile`

`challenges_passed`, `missions_completed` and friends are derived data. They
exist because the dashboard is the most-hit endpoint and the alternative is five
`COUNT(*)` queries over growing tables.

The safety net: attempts are **append-only facts**, progress rows are **derived
state**. Anything denormalised can be rebuilt by replaying attempts, and the
worker's `recompute_skill_rollups` job does exactly that on a schedule — because
derived data that is only ever written incrementally always drifts eventually.

### Content authored in Python, not YAML

`app/content/schema.py` defines typed dataclasses; packs are Python modules.

**Bought**: the type checker is the first proofreader; helpers like `eq()` and
`point()` remove the copy-paste where typos live; renaming a concept slug is a
refactor the tools understand rather than a grep through JSON.

**Paid**: content authors must write Python. For a project whose author *is* an
engineer, that is the right trade — and `validate_pack` runs in CI, so a
dangling reference fails the build rather than reaching a player as a broken
mission.

### No message broker

The worker is a plain asyncio loop running five periodic jobs. None fan out,
none need a result backend, all are idempotent.

Celery would add a broker, a worker pool and a beat process to run five
functions on a timer. **The threshold for introducing a queue** is a job that
needs retries with backoff, isolation from its siblings, or fan-out across
machines — and the Architecture Tower missions make the player argue exactly
that boundary.

### Hand-written frontend types

`src/types/api.ts` mirrors the Pydantic models by hand. Generated clients bury
every call site in `components['schemas'][...]` indirection and regenerate
noisily on unrelated backend edits.

**The drift risk is real**, so it is closed by a test rather than by discipline:
`src/test/contract.test.ts` validates every path the client calls against the
committed OpenAPI schema, and CI fails if the schema is stale. A backend rename
therefore fails the *frontend* build, which is where the broken call lives.

---

## 4. The sandbox boundary

This is the one place where being wrong is a security incident rather than a
bug, so the reasoning is explicit.

```
FastAPI process                    │  Sandbox
                                   │
SandboxService                     │
  ├─ static_prescreen (AST)        │
  ├─ asyncio.Semaphore             │
  └─ backend.execute() ────JSON────┼──► runner_main.py
                                   │      (imports NOTHING from app/)
                                   │      ├─ rlimits (POSIX)
                                   │      ├─ scrubbed os.environ
                                   │      ├─ blocked socket module
                                   │      └─ framed JSON result
```

**Why a JSON protocol rather than a function call**: it is the seam that makes
isolation possible at all. If the sandbox could accept a Python callable, the
portability *and* the isolation would both be gone. The same protocol drives a
subprocess today and a container tomorrow with no change above it.

**Why the runner is standalone**: so the container image can contain nothing but
that one file. `test_runner_imports_nothing_from_the_app` parses its AST and
fails the build if anyone adds an `app.` import.

**What each backend actually guarantees:**

| Backend        | Guarantee                                                                      | Honest limit                                        |
| -------------- | ------------------------------------------------------------------------------ | --------------------------------------------------- |
| `subprocess`   | Separate process, rlimits, scrubbed env, wall-clock kill of the process tree    | Not a boundary against a determined attacker         |
| `docker`       | `--network none --read-only --cap-drop ALL --user 65534 --pids-limit 64`        | Requires a Docker socket; use a socket proxy in prod |

Python cannot sandbox itself — `ctypes`, frame walking and C extensions defeat
any in-interpreter jail. `static_prescreen` is a filter that makes abuse loud
and gives the player a useful error; it is never claimed to be the boundary.
Saying that out loud, in the code, is the point: **a sandbox that oversells
itself is more dangerous than one that does not exist.**

---

## 5. Data model

37 tables. The organising principle:

| Kind            | Tables                                                | Property                    |
| --------------- | ----------------------------------------------------- | --------------------------- |
| **Identity**    | `users`, `refresh_tokens`, `player_profiles`          | Rarely written              |
| **Content**     | `concepts`, `challenges`, `questions`, `missions`, …  | Seeded from code, by slug   |
| **Facts**       | `*_attempts`, `xp_transactions`, `learning_events`    | **Append-only**             |
| **Derived**     | `skill_progress`, `concept_progress`, leaderboard     | Rebuildable from facts      |
| **AI**          | `traces`, `spans`, `rag_experiments`, `agent_runs`    | Inspectable by design       |

Content is identified by **slug**, never by UUID. Re-seeding runs on every
deploy; if rows were identified only by UUID, a re-seed would orphan every
player's progress. `test_seeding_twice_is_a_no_op` guards this in CI.

`ConceptProgress` mirrors the pure `ReviewState` dataclass field-for-field. The
engine stays pure; the row is only its storage format; two conversion functions
in `retention_service.py` are the entire bridge.

---

## 6. Observability

- **Request IDs** via contextvar, so every log line emitted while handling a
  request carries it without being threaded through signatures.
- **Structured logs** — one event per line, key-value, JSON in production.
- **`Server-Timing`** header, so latency shows up natively in browser devtools.
- **Two health endpoints, deliberately different**: `/health/live` touches
  nothing (failure ⇒ restart me); `/health/ready` checks database, cache and
  sandbox (failure ⇒ take me out of the load balancer, do **not** restart me).
  Conflating them turns a brief database blip into a restart loop.
- **Trace/span tables** mirroring OpenTelemetry's shape, because the
  Observability Lab asks the player to *read* traces and the lesson has to
  transfer.

Redis being down degrades performance, not correctness — so it never fails
readiness. Anything whose loss changes correctness is not a cache.

---

## 7. What is deliberately absent

| Not here                  | Why                                                                     |
| ------------------------- | ----------------------------------------------------------------------- |
| A DI container            | FastAPI's `Depends` already gives per-request lifetimes and test overrides |
| A message broker          | Five idempotent timer jobs do not need one                              |
| CQRS / event sourcing     | One writer, one reader, no audit requirement beyond the XP ledger        |
| A generated API client    | Readability at call sites, with a contract test closing the drift risk   |
| A CSP on the API          | It is served by nginx, not by FastAPI — a CSP there would be theatre     |
| Microservices             | One deployable, one database, one team. The seams are in the code.       |

The last one is the point of the whole document: **every abstraction must have a
reason, and "it looks professional" is not one.**
