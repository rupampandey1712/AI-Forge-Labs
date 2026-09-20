#!/usr/bin/env bash
#
# Compile, inspect and lint the Bicep template — without an Azure subscription.
#
# WHY THIS EXISTS: `az bicep build` catches wrong property names and bad API
# shapes, which is where most Bicep bugs live and which no amount of reading
# finds. It needs no login, no subscription and no deployment, so there is no
# excuse for an uncompiled template.
#
# Run it through the azure-cli image so nothing has to be installed locally:
#
#   docker run --rm -v "$PWD/infra/azure:/work" -w /work \
#     mcr.microsoft.com/azure-cli:latest bash validate.sh
#
# What this does NOT do: `az deployment group validate` and `what-if` both need
# a real subscription, because they check quota, policy and name availability
# against a live tenant. Those stay a pre-deploy step — see docs/DEPLOYMENT.md.

set -u
cd "$(dirname "$0")"
FAILED=0

# The image ships the CLI but not the Bicep binary; installing is idempotent.
az bicep install --only-show-errors >/dev/null 2>&1 || true

echo "=== bicep version ==="
az bicep version 2>&1 | grep -i "bicep cli" || az bicep version

echo
echo "=== build ==="
az bicep build --file main.bicep --outfile /tmp/main.json 2>/tmp/build.err
status=$?
cat /tmp/build.err
if [ $status -ne 0 ]; then
  echo "BUILD FAILED (exit $status)"
  exit 1
fi
# Only diagnostics that name a line in the template count. The CLI also emits
# unrelated config notices on stderr ("bicep.use_binary_from_path has been set
# to false"), and treating those as failures makes the check cry wolf.
if grep -qE "main\.bicep\([0-9]+," /tmp/build.err; then
  echo "!! build produced template diagnostics (above)"
  FAILED=1
else
  echo "BUILD OK - no errors, no warnings"
fi

echo
echo "=== compiled ARM shape ==="
python3 - <<'PY'
import collections
import json

d = json.load(open("/tmp/main.json"))
res = d["resources"]
print(f"parameters : {len(d.get('parameters', {}))}")
print(f"variables  : {len(d.get('variables', {}))}")
print(f"outputs    : {len(d.get('outputs', {}))}")
print(f"resources  : {len(res)}")
print()
for t, n in sorted(collections.Counter(r["type"] for r in res).items()):
    print(f"  {n}x  {t}")
PY

echo
echo "=== invariants ==="
python3 - <<'PY'
import json
import sys

d = json.load(open("/tmp/main.json"))
res = d["resources"]
problems = []

# Every credential-shaped parameter must be securestring, or it lands in the
# deployment history in plain text where anyone with reader access can see it.
for name, spec in d.get("parameters", {}).items():
    if any(w in name.lower() for w in ("secret", "password", "token", "key")):
        if spec.get("type") != "securestring":
            problems.append(f"parameter {name} is {spec.get('type')}, expected securestring")
        else:
            print(f"  OK  {name} is securestring")

# The trust boundary, asserted against the compiled template rather than the
# source: the sandbox must not be reachable from the internet.
apps = [r for r in res if r["type"] == "Microsoft.App/containerApps"]
for app in apps:
    name = app.get("name", "")
    ingress = app.get("properties", {}).get("configuration", {}).get("ingress", {})
    external = ingress.get("external")
    label = "sandbox" if "sandbox" in name else "public"
    if "sandbox" in name:
        if external is not False:
            problems.append(f"{name} has external={external}; the sandbox must not be public")
        else:
            print(f"  OK  sandbox ingress is internal (external=false)")
    else:
        print(f"  --  {label} app ingress external={external}")

if not apps:
    problems.append("no container apps found in the compiled template")

# The sandbox must carry no database, cache or signing-key wiring. Checked on
# the compiled JSON because that is what actually deploys.
#
# Note what is NOT forbidden: a vault reference. The sandbox legitimately reads
# its own auth token from the vault, so grepping for "vaultUri" flagged correct
# config as a violation. The real invariant is about *which* secrets it can
# reach, so the check names them.
FORBIDDEN_ENV = ("DATABASE_URL", "REDIS_URL", "JWT_SECRET")
FORBIDDEN_SECRETS = ("database-url", "redis-url", "jwt-secret", "postgres-admin-password")

for app in apps:
    if "sandbox" not in app.get("name", ""):
        continue
    config = app.get("properties", {}).get("configuration", {})
    containers = app.get("properties", {}).get("template", {}).get("containers", [])

    env_names = {e.get("name") for c in containers for e in c.get("env", [])}
    leaked_env = sorted(env_names & set(FORBIDDEN_ENV))
    if leaked_env:
        problems.append(f"sandbox exposes env vars: {', '.join(leaked_env)}")

    secret_names = {s.get("name") for s in config.get("secrets", [])}
    leaked_secrets = sorted(secret_names & set(FORBIDDEN_SECRETS))
    if leaked_secrets:
        problems.append(f"sandbox holds secrets: {', '.join(leaked_secrets)}")

    if not leaked_env and not leaked_secrets:
        held = ", ".join(sorted(n for n in secret_names if n)) or "none"
        print(f"  OK  sandbox holds only: {held}")

if problems:
    print()
    for p in problems:
        print(f"  !!  {p}")
    sys.exit(1)
PY
[ $? -ne 0 ] && FAILED=1

echo
echo "=== lint ==="
az bicep lint --file main.bicep 2>&1 | tail -40 || true

echo
if [ $FAILED -ne 0 ]; then
  echo "VALIDATION FAILED"
  exit 1
fi
echo "VALIDATION PASSED"
