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
| `STORAGE_BACKEND` | api | `local` (default) or `blob` |
| `BLOB_CONNECTION_STRING` | api | Required when the backend is `blob` |
| `QUEUE_BACKEND` | api + worker | `memory` (default) or `servicebus` |
| `SERVICEBUS_CONNECTION_STRING` | api + worker | Required when the backend is `servicebus` |

## Local Azure services

Two backends have a local-emulator option. **Neither is required** — the
defaults need nothing running, and the zero-setup path must keep working.

```bash
docker compose --profile azure up -d
```

| | Default | Emulator option |
|---|---|---|
| File storage | a directory (`var/artifacts`) | Azurite, `STORAGE_BACKEND=blob` |
| Event queue | in-process `asyncio.Queue` | Service Bus emulator, `QUEUE_BACKEND=servicebus` |

```bash
# Blob
export STORAGE_BACKEND=blob
export BLOB_CONNECTION_STRING="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"

# Service Bus
export QUEUE_BACKEND=servicebus
export SERVICEBUS_CONNECTION_STRING="Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"

pip install -e ".[azure]"
```

`/api/v1/health/info` reports which backend is live. Both **fail at startup**
rather than downgrading silently when their connection string is missing — a
process that thinks it is writing to blob and is writing to a container's
ephemeral disk loses everything on the next restart.

The Service Bus emulator keeps its state in SQL Server, which is why
`servicebus-db` exists in the compose profile. Queues are declared up front in
`infra/docker/servicebus-config.json`; a queue missing from that file fails at
publish rather than being auto-created.

### What goes where, and what does not

**Storage** holds matplotlib figures from the data-visualisation challenges.
The sandbox cannot write them itself — it has no network and no credentials, by
design — so figures come back over the execution protocol as bounded base64 and
the game server stores them.

Figures are written **during the request**, not on the queue. The grade
response carries their URLs and the player is looking at it, so deferring the
write would mean an image tag pointing at something that does not exist yet.
That was an event in the first version of this and it was wrong.

**The queue** carries only work nobody is waiting on: rebuilding the leaderboard
and refreshing decay snapshots for the concepts just practised. Both used to run
on a timer, which is why the leaderboard could be fifteen minutes stale.

The periodic scheduler stays. It runs whole-table idempotent sweeps that nothing
triggers; the queue carries per-player events that something did. Conflating
them gives you either a broker running a cron job or a cron job pretending to be
an event bus.

### Verifying the emulator paths

Neither is covered by the default test run, because neither emulator is assumed
to be up:

```bash
# Blob, against Azurite
docker run -d --name azurite -p 10000:10000 mcr.microsoft.com/azure-storage/azurite
python infra/checks/storage_check.py

# Service Bus, against the emulator
docker compose --profile azure up -d servicebus
python infra/checks/servicebus_check.py
```

The Service Bus check is the one worth running after any change to the consumer:
it exercises the broker's real delivery counting and dead-letter sub-queue,
which is what the in-process backend has to imitate faithfully.

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
