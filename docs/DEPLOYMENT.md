# Running and deploying

**Everything runs locally in Docker. There is no Azure account and nothing here
connects to one.** The Bicep template in `infra/azure/` is a reference artefact
— compiled and checked, never deployed. That distinction is kept explicit below
rather than implied, because a template presented as a deployment path when
nobody can deploy it is worse than no template.

Three images, one of which is a security boundary rather than a scaling
decision. Read [ADR-001](adr/ADR-001-modular-monolith-with-one-split.md) for why
there are three and not one, or three and not ten.

```
Browser ──> web ──> api ──internal──> sandbox
                     │
                     ├──> Postgres
                     └──> Redis
```

## The fastest path

No Postgres, no Docker, no API key. Falls back to SQLite and the deterministic
offline model:

```bash
cd backend
python -m app.cli bootstrap     # migrate, seed, create a player, simulate 45 days
uvicorn app.main:app --reload

cd frontend && npm run dev
```

Sign in with **player@aiforge.dev** / **forge-me-2026**. The bootstrap simulates
45 days of practice history, so the retention dashboard has a real decay curve
rather than an empty state.

## The full stack

```bash
docker compose up --build
```

Postgres, Redis, migrations as a one-shot job, seeding, the API, the worker and
the frontend. Healthchecks gate the ordering, so the API does not start against
a database that is not yet accepting connections.

## The split: the sandbox as its own service

This is the shape that matters, and it is the one the spec requires (§35/§66):

```bash
docker compose --profile split up --build
```

`sandbox` runs on an `internal: true` network with **no published ports**.
`backend-split` runs with `SANDBOX_MODE=remote` pointed at it.

| | api | sandbox |
|---|---|---|
| Reachable from your laptop | yes | **no** |
| Database credentials | yes | no |
| JWT signing key | yes | no |
| Executes player code | **no** | yes |

Verify the boundary is real rather than assumed:

```bash
# The API reports remote mode.
curl -s localhost:8000/api/v1/health/info | jq .sandbox_mode      # "remote"

# The sandbox is NOT reachable from outside the internal network.
curl -s --max-time 3 localhost:8001/health                        # connection refused
```

If that second command succeeds, the boundary is gone.

`SANDBOX_MODE=remote` **fails to start** when `SANDBOX_SERVICE_URL` is unset,
rather than falling back to a local subprocess. A silent fallback would mean a
deployment that believes it is isolated and is not.

## Configuration

| Variable | Where | Notes |
|---|---|---|
| `DATABASE_URL` | api | Empty falls back to SQLite |
| `REDIS_URL` | api | Optional; caching degrades gracefully without it |
| `SECRET_KEY` | api | 32+ bytes. Changing it logs everyone out. |
| `SANDBOX_MODE` | api | `subprocess`, `docker`, `remote` or `disabled` |
| `SANDBOX_SERVICE_URL` | api | Required when mode is `remote` |
| `SANDBOX_SERVICE_TOKEN` | api + sandbox | Must match; compared with `compare_digest` |
| `LLM_PROVIDER` | api | `mock` keeps every AI lab working offline and deterministic |
| `SANDBOX_TIMEOUT_CEILING` | sandbox | Hard cap; the sandbox clamps what it is handed |

## The Bicep template — reference only

`infra/azure/main.bicep` describes the same three-container shape on Azure
Container Apps. **It has never been deployed and there is no subscription
behind it.** It is kept because it is a concrete statement of the production
shape and because the Architecture Tower missions reference it.

What *is* verified, with no Azure account and no login:

```bash
docker run --rm -v "$PWD/infra/azure:/work" -w /work \
  mcr.microsoft.com/azure-cli:latest bash validate.sh
```

That compiles the template, prints the resource inventory, and asserts the
invariants that matter:

- every credential parameter is a `securestring`
- the sandbox container app has `external: false` ingress
- the sandbox holds no database, cache or signing-key wiring

Compiling it found three real defects that reading it had not: two wrong
property names on the Postgres `authConfig` block, and a Key Vault that was
created, granted a role, and referenced by nothing.

What that check **cannot** tell you: `az deployment group validate` and
`what-if` need a live tenant, because they check quota, policy and name
availability. So the template is proven well-formed, not proven deployable.

## When something breaks

| Symptom | Look at |
|---|---|
| Code submissions fail | `/api/v1/health/info` — check `sandbox_mode` |
| AI labs feel canned | Same endpoint — `llm_provider: mock` means offline |
| Frontend renders `undefined` | The contract test; regenerate `openapi.json` |
| Content gate failing | It names the concept, challenge or question |
| `$'\r': command not found` | A shell script picked up CRLF; `.gitattributes` pins `*.sh` to LF |
