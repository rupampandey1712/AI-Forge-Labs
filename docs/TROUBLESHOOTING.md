# Troubleshooting

Things that go wrong, and why. Diagnosis first — several of these have the same
symptom and different causes.

---

## Start here

```bash
curl -s localhost:8000/api/v1/health/ready | python -m json.tool
curl -s localhost:8000/api/v1/health/info  | python -m json.tool
```

`/health/ready` tells you which dependency is unhappy. `/health/info` tells you
which database dialect, sandbox mode and LLM provider you are *actually*
running — which is usually not the one you thought.

Every response carries `x-request-id`. Grep the logs for it before guessing.

---

## Backend will not start

### `SECRET_KEY must be a strong, non-default value in production`

Working as intended. `APP_ENV=production` refuses a weak or default secret.

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

### `sqlalchemy.exc.OperationalError: connection refused`

Postgres is not up, or not up *yet*.

```bash
docker compose ps
docker compose logs postgres | tail -20
```

Under Compose this should be impossible — `depends_on: condition:
service_healthy` gates it. If you see it there, the healthcheck is wrong, not
the dependency order.

Running bare-metal, the fix is usually to just unset `DATABASE_URL` and let it
fall back to SQLite.

### `ModuleNotFoundError: No module named 'app'`

Run from `backend/`, with the venv active, after `pip install -e ".[dev]"`.
The `-e` matters: a non-editable install will not see your edits.

### `ImportError: email-validator is not installed`

```bash
pip install -e ".[dev]"     # pydantic[email] is in the base dependencies
```

---

## Database

### `no such table: users`

The schema was never created.

```bash
python -m app.cli create-schema     # SQLite dev
alembic upgrade head                 # Postgres
```

### `sqlite3.OperationalError: index ... already exists`

A composite `Index("ix_table_column", ...)` collides with the name the naming
convention generates for a `column(index=True)`. Rename the composite index —
this exact bug is why `ix_knowledge_documents_corpus_chunk` has that suffix.

### Alembic autogenerate produces an empty migration

The model was not imported. `app/models/__init__.py` must import it — that file
exists precisely so `Base.metadata` is complete for autogenerate and so
SQLAlchemy can resolve `relationship()` targets by class name.

### Migration references `app.db.types.UTCDateTime`

The `render_item` hook in `alembic/env.py` is not being applied. Migrations must
be replayable with **nothing but SQLAlchemy** — coupling a historical migration
to today's application code means a rename six months from now breaks every old
migration.

---

## Sandbox

### Every submission returns `sandbox_error`

```bash
curl -s localhost:8000/api/v1/health/ready | python -m json.tool   # check "sandbox"
```

| Cause                              | Fix                                                                |
| ---------------------------------- | ------------------------------------------------------------------ |
| `SANDBOX_MODE=disabled`            | Set it to `subprocess`                                             |
| `docker` mode, image not built     | `docker build -f infra/docker/sandbox.Dockerfile -t aiforge-sandbox:latest backend` |
| `docker` mode, no socket access    | See the commented volume in `docker-compose.yml` — and read the warning |
| Antivirus blocking subprocess spawn | Exclude the venv directory (common on Windows)                     |

### Submissions are extremely slow

On Windows, real-time antivirus scans every spawned Python process. A single
execution can go from 5ms to 2s. Exclude `backend/.venv` and the temp directory.

### `Execution timed out` on code that is obviously fine

Check `time_limit_seconds` on the challenge. `SANDBOX_TIMEOUT_SECONDS` is the
global default; a challenge can set its own lower.

If it is genuinely the environment, the subprocess backend adds a 3-second grace
period on top of the in-runner limit — a hang past that means the process never
started, not that the code was slow.

### `import numpy` fails inside the sandbox

Subprocess mode runs in the backend's venv, so `pip install -e ".[ml]"`. Docker
mode uses the sandbox image, which already bundles numpy, pandas, matplotlib and
scikit-learn — but deliberately **not** torch (~2GB).

---

## Frontend

### Blank page, console shows 404s for `/api/...`

The Vite proxy is not reaching the backend. Check that `uvicorn` is on port 8000,
or set `VITE_API_TARGET`.

### 401 on every request, immediately after signing in

The access token is expiring or being rejected. Almost always: the backend
restarted with a *different* `SECRET_KEY`, invalidating every issued token.
Sign out and back in.

### Signed out unexpectedly, and everywhere

Refresh-token **reuse detection** fired. Presenting an already-rotated token is
the stolen-token signature, so every session for that user is revoked. It is
working as designed.

The usual innocent cause: two tabs refreshing simultaneously. The client's
single-flight guard prevents this within one tab; across tabs, the last one wins.

### `npm run build` fails with `The token '&&' is not a valid statement separator`

npm is using PowerShell as its script shell. Every script in `package.json` is
deliberately a single command for this reason — if you add one with `&&`, it
will break on Windows. Chain them in CI instead.

### Types are wrong after a backend change

```bash
cd backend && python -m app.cli openapi
cd ../frontend && npm run test
```

The contract test will name the endpoint that moved. CI fails on a stale
`openapi.json` for exactly this reason.

---

## Content

### `ContentError: references unknown concept 'x'`

A challenge or question points at a concept slug that no pack defines. Either
the concept is missing or the slug has a typo. `python -m app.cli content-check`
names it.

### `ContentError: free-text question with no rubric cannot be graded`

Every non-MCQ question needs a rubric. Without one the grader falls back to
token overlap with the model answer, which is too crude to be fair.

### A reference solution fails its own tests

```bash
pytest tests/integration/test_content_integrity.py -k your-challenge-slug
```

The failure output shows the exact test and message. This is the suite's whole
reason for existing — content that claims to be solvable but is not is the worst
bug a learning product can ship.

### `warning: no hidden tests — solution can be hard-coded`

Add at least one `hidden=True` test. Without one a player can special-case the
visible examples and the grade means nothing.

---

## Retention and gameplay

### The retention dashboard is empty

Correct behaviour for a new account — nothing has been practised, so nothing can
decay. To see it populated:

```bash
python -m app.cli demo-user --simulate-days 60
```

That replays attempts through the **real** engines rather than writing rows, so
the numbers it produces are numbers the game can actually produce.

### A concept shows as "due" immediately after passing it

Check `interval_days`. A pass with 3 hints and a low score can schedule a review
inside a day — the engine correctly treats a heavily-assisted solve as weak
evidence of recall. Working as designed.

### Mastery is stuck below 60%

You are hitting the **tier ceiling**. Mastery is capped by the deepest tier you
have actually cleared: tier 3 caps at 58%, tier 5 at 80%. Answering more tier-3
questions cannot move it. Take the tier-6+ content.

### The daily mission has fewer slots than expected

It draws from seeded content and never repeats a slug within a day. With only
one content pack seeded, the pools exhaust. Seed more packs.

### Badges are not unlocking

```bash
pytest tests/integration/test_game_loop.py -k badges
```

Check the criteria keys against `NUMERIC_STATS` in
`app/game/achievements/rules.py`. CI validates this, so a typo should never
reach you — but a key the interpreter silently ignores makes a badge
permanently unearnable.

---

## Docker

### `seed` exits non-zero and the backend never starts

By design — `depends_on: condition: service_completed_successfully`. Read the
seed logs; it is almost always a content validation error.

```bash
docker compose logs seed
```

### Postgres data survives a `down`

The named volume persists. To genuinely reset:

```bash
docker compose down -v      # -v drops volumes. This deletes all player progress.
```

### Backend healthcheck never passes

```bash
docker compose logs backend | tail -40
```

`/health/live` touches nothing, so a failure means the process is not listening
at all — usually a config validation error at import time, which the logs will
show in full.

---

## Performance

### Dashboard is slow

It is one endpoint returning eight sections. If it is slow, enable
`DB_ECHO=true` and count the queries — the panel is designed to be a fixed
number of grouped queries, and a regression to per-row lookups is an N+1 that
the code comments warn about explicitly.

### Everything is slow after enabling Redis

Check that Redis is actually reachable. `RedisCache` degrades to a miss on every
failure rather than raising — correct, but it means an unreachable Redis costs a
connection timeout *per call*. `/health/ready` reports `degraded`.

---

## Still stuck

1. `/health/ready` — which dependency?
2. `/health/info` — which configuration is actually loaded?
3. `x-request-id` from the failing response — grep the logs for it
4. `LOG_LEVEL=DEBUG DB_ECHO=true` — see every query
5. `SANDBOX_MODE=disabled` — rule out the sandbox entirely
6. `pytest -x` — the suite covers most of the failure modes above and will
   usually reproduce the problem faster than the UI will
