#!/usr/bin/env bash
# M9.1 Step 7.5 — automated multi-round E2E for the agentic loop.
#
# Drives /chat → simulated user approval → /chat/continue → assert terminal_reason.
# No Chrome extension required. Closes the gap between per-call unit tests
# (test_browser_directives.py) and manual UI tests (Step 8).
#
# Default lane: cloud (fast: prefix → Groq).
# LIVE_LOCAL=1: routes through local master-ai instead.
#
# Run:
#   bash ~/scripts/test_browser_e2e.sh
#   LIVE_LOCAL=1 bash ~/scripts/test_browser_e2e.sh

set -euo pipefail

BASE_URL="${MASTER_AI_BASE_URL:-http://127.0.0.1:8080}"
TOKEN_FILE="${HOME}/.master_ai_extension_token"
TOKEN="$(cat "${TOKEN_FILE}" 2>/dev/null || true)"

if [[ "${LIVE_LOCAL:-0}" == "1" ]]; then
  LANE_PREFIX="local:"
  LANE_LABEL="local"
else
  LANE_PREFIX="fast:"
  LANE_LABEL="cloud(fast)"
fi

R1="/tmp/m9_e2e_r1.json"
R2="/tmp/m9_e2e_r2.json"

echo "[e2e] lane=${LANE_LABEL} base=${BASE_URL} token=$( [[ -n "${TOKEN}" ]] && echo set || echo empty )"

echo "[e2e] round 1: POST /chat — request a browser nav that needs a follow-up"
curl -sS -X POST "${BASE_URL}/chat" \
  -H "Content-Type: application/json" \
  -H "X-Master-AI-Token: ${TOKEN}" \
  -d "$(python3 -c '
import json, os, sys
prefix = sys.argv[1]
prompt = (
    f"{prefix} Two-step task — emit ONLY these directives, no others. "
    "Round 1: BROWSER_NAV: https://example.com. "
    "After the approval comes back, in round 2 emit BROWSER_READ: main on one line "
    "and DONE: navigated and read example.com on the next line, then STOP. "
    "Do NOT propose any further actions after DONE:."
)
print(json.dumps({"prompt": prompt, "source": "chrome_extension"}))
' "${LANE_PREFIX}")" \
  -o "${R1}"

TURN_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("turn_id",""))' "${R1}")"
if [[ -z "${TURN_ID}" ]]; then
  echo "[e2e] FAIL: round 1 did not return turn_id"
  python3 -m json.tool < "${R1}" | head -30
  exit 2
fi
echo "[e2e] round 1 turn_id=${TURN_ID}"

R1_ACTIONS_JSON="$(python3 -c '
import json, sys
r = json.load(open(sys.argv[1]))
print(json.dumps(r.get("actions") or []))
' "${R1}")"
echo "[e2e] round 1 actions: ${R1_ACTIONS_JSON}"

# Build action_results that simulate "user approved and the extension dispatched".
# Shape matches stt_server._format_action_results / _duplicate_failure_reason:
#   { action: {kind, target}, verdict: "approved", result: "success", final_state: {...} }
ACTION_RESULTS_JSON="$(python3 -c '
import json, sys
acts = json.loads(sys.argv[1])
out = []
for a in acts:
    kind = (a.get("kind") or "").upper()
    target = a.get("target") or ""
    if kind == "BROWSER_NAV":
        final_state = {"navigated": target}
    elif kind == "BROWSER_READ":
        final_state = {"text": "Welcome to the example.com test page (synthetic e2e body)."}
    elif kind == "BROWSER_CLICK":
        final_state = {"clicked": target}
    elif kind == "BROWSER_FILL":
        final_state = {"value": "(redacted by e2e harness)"}
    else:
        final_state = {"reason": "approved by e2e harness"}
    out.append({
        "action": {"kind": kind, "target": target},
        "verdict": "approved",
        "result": "success",
        "final_state": final_state,
    })
print(json.dumps(out))
' "${R1_ACTIONS_JSON}")"

echo "[e2e] round 2: POST /chat/continue — post simulated approval back"
curl -sS -X POST "${BASE_URL}/chat/continue" \
  -H "Content-Type: application/json" \
  -H "X-Master-AI-Token: ${TOKEN}" \
  -d "$(python3 -c '
import json, sys
print(json.dumps({"parent_turn_id": sys.argv[1], "action_results": json.loads(sys.argv[2])}))
' "${TURN_ID}" "${ACTION_RESULTS_JSON}")" \
  -o "${R2}"

python3 - <<'PY'
import json, sys
r2 = json.load(open("/tmp/m9_e2e_r2.json"))
term = r2.get("terminal_reason")
reply = (r2.get("reply") or "")
acceptable = ("done_directive", "no_actions")
ok = term in acceptable
print(f"[e2e] round 2 terminal_reason={term!r}")
print(f"[e2e] round 2 reply (first 200ch): {reply[:200]!r}")
if not ok:
    print(f"[e2e] FAIL: expected terminal_reason in {acceptable}; got {term!r}")
    print(f"[e2e] full round-2 response (first 800ch): {json.dumps(r2)[:800]}")
    sys.exit(3)
print(f"[e2e] PASS — E2E loop OK: {term}")
PY
