#!/usr/bin/env bash
#
# Smoke-test a running sandbox service.
#
#   docker run --rm -d --name sbx -e SANDBOX_SERVICE_TOKEN=local-token \
#     -p 8001:8001 aiforge-sandbox:latest
#   bash infra/docker/smoke-sandbox.sh http://localhost:8001 local-token
#
# Checks the three properties the split exists to provide: it refuses anonymous
# callers, it really executes and grades, and it clamps the limits it is handed
# rather than trusting them.

set -u
BASE="${1:-http://localhost:8001}"
TOKEN="${2:-local-token}"
FAILED=0

pass() { echo "  OK  $1"; }
fail() { echo "  !!  $1"; FAILED=1; }

echo "=== health (must be open — an orchestrator probes it) ==="
if curl -fsS "$BASE/health" >/dev/null 2>&1; then
  curl -fsS "$BASE/health"
  echo
  pass "health responds without a token"
else
  fail "health did not respond"
  exit 1
fi

echo
echo "=== auth ==="
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/execute" \
  -H 'Content-Type: application/json' -d '{"code":"x = 1"}')
[ "$code" = "401" ] && pass "anonymous caller refused (401)" \
                    || fail "anonymous caller got $code, expected 401"

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/execute" \
  -H 'Content-Type: application/json' -H 'X-Sandbox-Token: wrong' \
  -d '{"code":"x = 1"}')
[ "$code" = "401" ] && pass "wrong token refused (401)" \
                    || fail "wrong token got $code, expected 401"

echo
echo "=== execution ==="
cat > /tmp/ok.json <<'JSON'
{"code": "def double(x):\n    return x * 2",
 "tests": [{"name": "doubles", "kind": "equals", "call": "double(4)", "expect": 8},
           {"name": "zero", "kind": "equals", "call": "double(0)", "expect": 0, "hidden": true}]}
JSON
body=$(curl -fsS -X POST "$BASE/execute" -H 'Content-Type: application/json' \
  -H "X-Sandbox-Token: $TOKEN" --data-binary @/tmp/ok.json)
echo "$body" | grep -q '"status": *"ok"' && pass "correct submission executes and passes" \
                                         || fail "correct submission did not pass: $body"

# A wrong answer must actually fail. A sandbox that passes everything is worse
# than one that is down, because nothing surfaces it.
cat > /tmp/bad.json <<'JSON'
{"code": "def double(x):\n    return x + 2",
 "tests": [{"name": "doubles", "kind": "equals", "call": "double(4)", "expect": 8}]}
JSON
body=$(curl -fsS -X POST "$BASE/execute" -H 'Content-Type: application/json' \
  -H "X-Sandbox-Token: $TOKEN" --data-binary @/tmp/bad.json)
echo "$body" | grep -q '"status": *"failed"' && pass "wrong submission fails" \
                                             || fail "wrong submission did not fail: $body"

echo
echo "=== the limits are not trusted ==="
body=$(curl -fsS -X POST "$BASE/execute" -H 'Content-Type: application/json' \
  -H "X-Sandbox-Token: $TOKEN" \
  -d '{"code":"while True:\n    pass","timeout_seconds":9999,"tests":[]}')
echo "$body" | grep -q '"timed_out": *true' && pass "a 9999s timeout request was clamped" \
                                            || fail "infinite loop was not stopped: $body"

echo
echo "=== network is unavailable to player code ==="
body=$(curl -fsS -X POST "$BASE/execute" -H 'Content-Type: application/json' \
  -H "X-Sandbox-Token: $TOKEN" \
  -d '{"code":"import socket\nsocket.create_connection((\"1.1.1.1\", 53), timeout=3)","tests":[]}')
echo "$body" | grep -q '"status": *"ok"' && fail "player code opened a socket: $body" \
                                         || pass "socket attempt did not succeed"

echo
[ $FAILED -eq 0 ] && echo "SANDBOX SMOKE PASSED" || echo "SANDBOX SMOKE FAILED"
exit $FAILED
