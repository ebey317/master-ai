#!/usr/bin/env bash
set -euo pipefail

HOST="${SDCPP_HOST:-127.0.0.1:7860}"
OUT_DIR="${SDCPP_OUT_DIR:-$HOME/scripts/image_engine/out}"
LCM_PATH="lcm-lora-sdv1-5.safetensors"

usage() {
  cat <<EOF
imagegen.sh — local image gen via sd-server (CPU, ~56s/image on this box)

Commands:
  health                              exit 0 if sd-server reachable, 1 otherwise
  submit "<prompt>" [W H STEPS SEED]  POST a job, print job_id
  status [--verbose] <job_id>         print status[/queue_position[/error]]
  fetch  <job_id> [out_path]          decode result PNG, print saved path
  gen    "<prompt>" [out_path]        submit + poll + fetch (blocks ~1 min)
  help                                this message

Env:
  SDCPP_HOST     (default 127.0.0.1:7860)
  SDCPP_OUT_DIR  (default ~/scripts/image_engine/out)

Defaults: 512x512, 4-step euler_a + LCM-LoRA, cfg-scale 1, structured LoRA attached automatically.
EOF
}

require() { command -v "$1" >/dev/null || { echo "missing: $1" >&2; exit 2; }; }
require curl
require python3

cmd_health() {
  curl -sf "http://$HOST/sdcpp/v1/capabilities" -o /dev/null
}

cmd_submit() {
  local prompt="${1:?prompt required}"
  local w="${2:-512}" h="${3:-512}" steps="${4:-4}" seed="${5:--1}"

  local body
  body=$(python3 - "$prompt" "$w" "$h" "$steps" "$seed" "$LCM_PATH" <<'PY'
import sys, json
prompt, w, h, steps, seed, lcm_path = sys.argv[1:]
print(json.dumps({
  "prompt": prompt,
  "width": int(w), "height": int(h),
  "seed": int(seed),
  "lora": [
    {"path": lcm_path, "multiplier": 1.0, "is_high_noise": False}
  ],
  "sample_params": {
    "sample_steps": int(steps),
    "sample_method": "euler_a",
    "guidance": {"txt_cfg": 1.0}
  }
}))
PY
)
  local response
  response=$(curl -fsS -X POST "http://$HOST/sdcpp/v1/img_gen" \
    -H "Content-Type: application/json" \
    --data-binary "$body")
  python3 - "$response" <<'PY'
import sys, json
d = json.loads(sys.argv[1])
print(d["id"])
PY
}

cmd_status() {
  local verbose=0 id=""
  while (($#)); do
    case "$1" in
      -v|--verbose) verbose=1; shift ;;
      --) shift; break ;;
      *) id="${id:-$1}"; shift ;;
    esac
  done
  : "${id:?job_id required}"
  local response
  response=$(curl -sS "http://$HOST/sdcpp/v1/jobs/$id" || true)
  python3 - "$id" "$verbose" "$response" <<'PY'
import sys, json
job_id, verbose, response = sys.argv[1], sys.argv[2] == "1", sys.argv[3]
try:
  d = json.loads(response)
except json.JSONDecodeError:
  sys.exit(response or f"failed to read job status: {job_id}")
if d.get("error") == "job not found":
  sys.exit(f"job not found: {job_id}")
if verbose:
  print(json.dumps(d, indent=2, sort_keys=True))
else:
  parts = [d.get("status","unknown")]
  if d.get("status") == "queued":
    parts.append(f"queue_position={d.get('queue_position','?')}")
  if d.get("error"):
    parts.append(f"error={d['error']}")
  print(" ".join(parts))
PY
}

cmd_fetch() {
  local id="${1:?job_id required}"
  local out="${2:-}"
  if [[ -z "$out" ]]; then
    mkdir -p "$OUT_DIR"
    out="$OUT_DIR/$(date +%Y%m%d_%H%M%S)_$id.png"
  else
    mkdir -p "$(dirname "$out")"
  fi
  local response
  response=$(curl -sS "http://$HOST/sdcpp/v1/jobs/$id" || true)
  python3 - "$id" "$out" "$response" <<'PY'
import sys, json, base64
job_id, out, response = sys.argv[1:]
try:
  d = json.loads(response)
except json.JSONDecodeError:
  sys.exit(response or f"failed to fetch job: {job_id}")
if d.get("error") == "job not found":
  sys.exit(f"job not found: {job_id}")
if d.get("status") != "completed":
  sys.exit(f"job not completed: status={d.get('status')} error={d.get('error')}")
b64 = d["result"]["images"][0]["b64_json"]
open(out, "wb").write(base64.b64decode(b64))
print(out)
PY
}

cmd_gen() {
  local prompt="${1:?prompt required}"
  local out="${2:-}"
  cmd_health || { echo "sd-server not reachable at $HOST" >&2; exit 3; }
  local id; id=$(cmd_submit "$prompt")
  while :; do
    local s; s=$(cmd_status "$id" | awk '{print $1}')
    case "$s" in
      completed) cmd_fetch "$id" "$out"; return ;;
      failed|error) echo "job $id $s" >&2; return 4 ;;
    esac
    sleep 2
  done
}

case "${1:-help}" in
  health) shift; cmd_health ;;
  submit) shift; cmd_submit "$@" ;;
  status) shift; cmd_status "$@" ;;
  fetch)  shift; cmd_fetch  "$@" ;;
  gen)    shift; cmd_gen    "$@" ;;
  help|-h|--help) usage ;;
  *) usage; exit 2 ;;
esac
