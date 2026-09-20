# Deployment

Three deployable images, one of which is a security boundary rather than a
scaling decision. Read [ADR-001](adr/ADR-001-modular-monolith-with-one-split.md)
first if you want to know why there are three and not one, or three and not ten.

```
Internet ──> aiforge-web ──> aiforge-api ──internal──> aiforge-sandbox-service
                                  │
                                  ├──> Postgres Flexible Server
                                  ├──> Redis
                                  └──> Key Vault  (managed identity)
```

The sandbox has **no public ingress**. Only the API can reach it. It holds no
credentials and has no database connection, because it executes player code by
design and the only defence that matters against a sandbox escape is that there
is nothing on the other side worth taking.

## Local: the split, on your machine

The default compose stack runs the sandbox in-process, which is fine for
development. To run the deployed shape:

```bash
docker compose --profile split up --build
```

That starts `sandbox` on an `internal: true` network with no published ports,
and `backend-split` with `SANDBOX_MODE=remote` pointed at it. If you can `curl`
the sandbox from your laptop, the boundary is broken — it should be unreachable.

Verify the boundary is real:

```bash
# The API is up and reports remote mode.
curl -s localhost:8000/api/v1/health/info | jq .sandbox_mode      # "remote"

# The sandbox is not reachable from outside the internal network.
curl -s --max-time 3 localhost:8001/health                        # connection refused

# A submission still grades, which means it crossed the boundary.
# (log in first; see README for the demo credentials)
```

`SANDBOX_MODE=remote` **fails to start** if `SANDBOX_SERVICE_URL` is unset,
rather than falling back to a local subprocess. That is deliberate: a silent
fallback would mean a deployment that believes it is isolated and is not.

## Azure

### What gets created

| Resource | SKU | Why this one |
|---|---|---|
| Container Apps environment | Consumption | Scale-to-zero, managed ingress, no cluster to operate |
| Container Registry | Basic | Three images; Premium buys geo-replication nothing needs |
| Postgres Flexible Server | B1ms (B2s in prod) | Spiky low load; ~1/10th the cost of the smallest General Purpose tier |
| Redis | Basic C0 | Cache only — everything in it is rebuildable from Postgres |
| Key Vault | Standard, RBAC | RBAC rather than access policies, so grants appear in subscription-wide access reviews |
| Log Analytics + App Insights | PerGB2018 | 30-day retention |
| User-assigned managed identity | — | Must exist *before* the apps, to hold registry and vault roles |

### Deploy

```bash
RG=aiforge-dev
az group create -n $RG -l uksouth

# Build and push. Tag with the git SHA — never `latest`, or a rollback has
# nothing to roll back to.
TAG=$(git rev-parse --short HEAD)
ACR=$(az acr list -g $RG --query "[0].name" -o tsv)

az acr build -r $ACR -t aiforge-api:$TAG              -f backend/Dockerfile backend
az acr build -r $ACR -t aiforge-web:$TAG              -f frontend/Dockerfile frontend
az acr build -r $ACR -t aiforge-sandbox-service:$TAG  -f infra/docker/sandbox-service.Dockerfile backend

az deployment group create \
  -g $RG \
  -f infra/azure/main.bicep \
  -p environmentName=dev \
     imageTag=$TAG \
     postgresAdminPassword="$(openssl rand -base64 32)" \
     jwtSecret="$(openssl rand -base64 48)" \
     sandboxToken="$(openssl rand -base64 32)" \
     llmProvider=gemini \
     llmApiKey="$GEMINI_API_KEY"
```

Outputs give you the web URL, the API URL, and the sandbox's internal FQDN —
the last one is printed specifically so you can confirm it is not public.

### Migrations

The API does **not** run migrations on startup. N replicas starting at once
would race, and the loser crashes. Run them as a one-shot job:

```bash
az containerapp job create \
  -g $RG -n aiforge-migrate \
  --environment aiforge-dev-env \
  --trigger-type Manual \
  --replica-timeout 600 \
  --image $ACR.azurecr.io/aiforge-api:$TAG \
  --command "alembic" "upgrade" "head" \
  --secrets "database-url=<connection string>" \
  --env-vars "DATABASE_URL=secretref:database-url"

az containerapp job start -g $RG -n aiforge-migrate
```

Then seed once, with `python -m app.cli seed`, using the same job shape.

### Rolling back

Container Apps keeps revisions. A bad deploy is:

```bash
az containerapp revision list -g $RG -n aiforge-dev-api -o table
az containerapp ingress traffic set -g $RG -n aiforge-dev-api \
  --revision-weight <previous-revision>=100
```

Seconds, not a rebuild. This is why the image tag is the git SHA — a rollback
needs a specific prior artefact to point at, and `latest` is not one.

## Configuration

| Variable | Where | Notes |
|---|---|---|
| `DATABASE_URL` | api | Container Apps secret, from Bicep |
| `REDIS_URL` | api | Container Apps secret |
| `JWT_SECRET` | api | 32+ random bytes. Rotating it logs everyone out. |
| `SANDBOX_MODE` | api | `remote` in Azure. Anything else means the API can execute code. |
| `SANDBOX_SERVICE_URL` | api | Internal FQDN. Required when mode is `remote`. |
| `SANDBOX_SERVICE_TOKEN` | api + sandbox | Must match. Compared with `compare_digest`. |
| `LLM_PROVIDER` / `LLM_API_KEY` | api | `mock` keeps every AI lab working offline, deterministically. |
| `SANDBOX_TIMEOUT_CEILING` | sandbox | Hard cap. The sandbox clamps what it is handed rather than trusting it. |
| `SANDBOX_MEMORY_CEILING_MB` | sandbox | Same. |

Nothing that carries a secret is read by the sandbox service, and it imports
`app.core.config` not at all — see the boundary test.

## What this deployment does not do yet

Stated rather than implied, because an unlisted gap reads as an oversight:

- **Postgres is reachable from Azure services**, via the `AllowAzureServices`
  firewall rule, because Container Apps egress IPs are not fixed. The correct
  production answer is a VNet-integrated environment with a private endpoint,
  which is a larger change than this template makes. Fine for dev; do the VNet
  work before anything real lives in the database.
- **No custom domain or managed certificate.** Container Apps gives you a
  `*.azurecontainerapps.io` hostname with TLS; a real deployment wants
  `az containerapp hostname bind`.
- **No autoscale on anything but HTTP concurrency.** Queue-depth scaling via
  KEDA is the next step if sandbox executions start queueing.
- **The Bicep has not been deployed from this repository.** It is written
  against the resource schemas and reviewed, but `az` was not available in the
  environment where it was authored, so it has not been `az bicep build`-ed or
  run. Validate it before trusting it:
  ```bash
  az bicep build -f infra/azure/main.bicep
  az deployment group validate -g $RG -f infra/azure/main.bicep -p ...
  ```

## Cost

Rough monthly, UK South, dev sizing, assuming light use:

| | |
|---|---|
| Container Apps (API min 1 replica, 0.5 vCPU) | ~£25 |
| Container Apps (sandbox min 1 replica, 1 vCPU) | ~£35 |
| Container Apps (web, scale to zero) | ~£0 |
| Postgres B1ms + 32GB | ~£15 |
| Redis Basic C0 | ~£12 |
| Registry Basic, Key Vault, Log Analytics | ~£8 |
| **Total** | **~£95** |

Setting `apiMinReplicas=0` and `sandboxMinReplicas=0` takes this to near zero
when idle, at the cost of a cold start of several seconds on the first request —
which for a single-player game you open in the evening is usually the right
trade.
