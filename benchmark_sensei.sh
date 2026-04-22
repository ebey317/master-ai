#!/bin/bash
# benchmark_sensei.sh — the "can Qwen compete" test.
#
# Hits local Ollama with real Master-AI-style build tasks at three tiers
# (beginner/intermediate/pro) across three Sensei-mode prompt styles
# (plan/review/auto) on two trifecta models (qwen2.5:3b, qwen2.5:7b) — up to
# 18 real runs per invocation. No simulation, no mock — real inference,
# real artifacts on disk, real scoring.
#
# Goal: surface Qwen's failure points (truncation, hallucination, syntax
# breaks, off-task output) without crashing. RED verdict is expected and
# informative — it's WHERE we see the ceiling.
#
# Usage:
#   bash ~/scripts/benchmark_sensei.sh                         # full run
#   bash ~/scripts/benchmark_sensei.sh --tier beginner         # one tier
#   bash ~/scripts/benchmark_sensei.sh --model qwen2.5:3b      # one model
#   bash ~/scripts/benchmark_sensei.sh --mode review           # one mode
#   bash ~/scripts/benchmark_sensei.sh --short                 # summary only
#
# Output:
#   ~/Desktop/master_ai_benchmark/
#     run.log                          # live transcript
#     summary.json                     # final table machine-readable
#     summary.md                       # final table human-readable
#     artifacts/<model>/<tier>/<mode>/ # AI's generated files
#
# Run time: 3b alone ~20-40 min; 3b + 7b full matrix ~2-4 hours on i7-6700T.

set -u
source ~/scripts/brand.sh 2>/dev/null || true

TIERS=(beginner intermediate pro)
MODES=(plan review auto)
# Local models — 14B joins automatically when pulled AND box has 24+ GB RAM
LOCAL_MODELS=(qwen2.5:3b qwen2.5:7b)
_ram_total_mb=$(awk '/MemTotal/ {print int($2/1024); exit}' /proc/meminfo 2>/dev/null)
if curl -sf -m 2 http://localhost:11434/api/tags 2>/dev/null | grep -q '"qwen2.5:14b"' \
    && [ "${_ram_total_mb:-0}" -ge 20000 ]; then
    LOCAL_MODELS+=(qwen2.5:14b)
fi
SHORT=0
SKIP_CLOUD=0
SKIP_VISION=0
SKIP_TTS=0
REPS=1     # endurance mode: --reps 6 repeats the whole matrix 6x

while [ $# -gt 0 ]; do
    case "$1" in
        --tier)       TIERS=("$2"); shift 2 ;;
        --mode)       MODES=("$2"); shift 2 ;;
        --model)      LOCAL_MODELS=("$2"); shift 2 ;;
        --no-cloud)   SKIP_CLOUD=1; shift ;;
        --no-vision)  SKIP_VISION=1; shift ;;
        --no-tts)     SKIP_TTS=1; shift ;;
        --short)      SHORT=1; shift ;;
        --reps)       REPS="$2"; shift 2 ;;
        *)            shift ;;
    esac
done

# Read available cloud API keys — a cloud model only joins the matrix if its
# key is present. Everything gets used — nothing idle.
KEYS_FILE="$HOME/.master_ai_keys"
GROQ_KEY=""; OPENROUTER_KEY=""
if [ -f "$KEYS_FILE" ]; then
    GROQ_KEY=$(python3 -c "import json; print(json.load(open('$KEYS_FILE')).get('groq',''))" 2>/dev/null)
    OPENROUTER_KEY=$(python3 -c "import json; print(json.load(open('$KEYS_FILE')).get('openrouter',''))" 2>/dev/null)
fi

CLOUD_PROVIDERS=()
[ "$SKIP_CLOUD" = "0" ] && [ -n "$GROQ_KEY" ]       && CLOUD_PROVIDERS+=(groq)
[ "$SKIP_CLOUD" = "0" ] && [ -n "$OPENROUTER_KEY" ] && CLOUD_PROVIDERS+=(openrouter)

OUT="$HOME/Desktop/master_ai_benchmark"
LOG="$OUT/run.log"
SUMMARY_JSON="$OUT/summary.json"
SUMMARY_MD="$OUT/summary.md"
mkdir -p "$OUT/artifacts"
: > "$LOG"

# Rolling array of result rows — each row is a JSON object string.
RESULTS=()

log() { echo -e "$1" | tee -a "$LOG"; }

# ── Task definitions ──────────────────────────────────────────
# Each tier has: title, prompt, output_ext, pass criteria (grep patterns),
# and a "budget" (max seconds + max tokens). Mode prompt wrappers are applied
# below so "plan" / "review" / "auto" are different prompting styles.
beginner_prompt() {
    cat <<'P'
Write a single bash script `hello.sh` that greets a user by name.
Requirements:
- Starts with `#!/bin/bash` shebang on line 1.
- Accepts one argument: the user's name.
- Prints `Hello, <name>!` — or if no argument, `Hello, stranger!`.
- Uses only bash built-ins, no external tools.

Output ONLY the contents of hello.sh. No markdown fences, no explanation.
P
}
beginner_criteria() {
    # returns patterns: each line is <label>|<regex>
    cat <<'C'
shebang|^#!/bin/bash
name_handling|\$[1@]|\$\{1[:-]|\$\{@
greeting|[Hh]ello
stranger_fallback|stranger|no.*name|if.*empty|-z
C
}

intermediate_prompt() {
    cat <<'P'
Write TWO files that together count words in a text file:

FILE 1 — `count.py`: a Python 3 script.
- Reads a filename from sys.argv[1].
- Opens it, reads every line.
- Prints the total word count as a single integer on one line.
- No external deps.

FILE 2 — `count.sh`: a bash wrapper.
- Shebang on line 1.
- Takes one argument (file path).
- Validates the file exists. If missing, prints `file not found` and exits non-zero.
- Otherwise invokes `python3 count.py <path>` and passes through its output.

Respond with EXACTLY this format — nothing else before/after:
===FILE: count.py===
<code>
===FILE: count.sh===
<code>
===END===
P
}
intermediate_criteria() {
    cat <<'C'
py_shebang_or_sysargv|sys\.argv
py_open|open\(
py_count|split|Counter|len
sh_shebang|^#!/bin/bash
sh_validate|-f |-e |file not found
sh_invoke_py|python3 count\.py
two_files|===FILE: count\.py===.*===FILE: count\.sh===
C
}

pro_prompt() {
    cat <<'P'
Build a minimal HTTP notes service in Python 3.

Requirements:
- Single file `notes_server.py`.
- Uses the standard library only (http.server + sqlite3 + json). No Flask, no deps.
- Creates/uses ./notes.db (SQLite) with a notes table (id INTEGER PK, body TEXT, ts INTEGER).
- Listens on 127.0.0.1:8765 (configurable via argv[1]).
- Routes:
    GET  /health       -> 200 {"status":"ok"}
    GET  /notes        -> 200 JSON array of all notes, newest first
    POST /notes {body} -> 201 {"id":N}, inserts row
    DELETE /notes/:id  -> 204 on success, 404 if missing
- Graceful shutdown on SIGINT. Connection closes cleanly.
- At least one `try/except` so a malformed POST returns 400, not a stacktrace.

Respond with EXACTLY this format:
===FILE: notes_server.py===
<full code>
===END===

The code must be runnable as `python3 notes_server.py` with no edits.
P
}
pro_criteria() {
    cat <<'C'
http_server|http\.server|HTTPServer|BaseHTTPRequestHandler
sqlite3_import|import sqlite3
routes_health|/health
routes_notes_list|/notes
routes_notes_post|do_POST|POST
routes_notes_delete|do_DELETE|DELETE
json_responses|json\.dumps|json\.loads
try_except|except |try:
shebang_or_main|if __name__|^#!/usr/bin/env python
C
}

# Budget by tier — (max_seconds, num_predict)
budget_beginner="90 400"
budget_intermediate="240 1200"
budget_pro="600 3000"

# ── Mode wrappers ─────────────────────────────────────────────
# Each mode changes the PROMPT style to simulate Sensei's modes without
# actually running the agent loop (that's a Sensei-level test). We're
# testing what the raw model produces under different instruction styles.
wrap_mode() {
    local mode="$1"
    local base="$2"
    case "$mode" in
        review)
            # Review: straightforward, no extra wrapper. Just produce the artifact.
            echo "$base"
            ;;
        plan)
            # Plan: ask for a numbered plan first, THEN the implementation.
            echo "Before writing, give a 3-line numbered plan for your implementation.
Then produce the artifact exactly as specified below.

$base"
            ;;
        auto)
            # Auto: emphasize completeness, self-check, runnable on first try.
            echo "Produce a COMPLETE, RUNNABLE artifact. Do not leave TODOs. Self-check
your output before replying: does it satisfy every requirement? Does it have
valid syntax? If you spot a problem, fix it BEFORE sending.

$base"
            ;;
    esac
}

# ── One run ───────────────────────────────────────────────────
# Arguments: model tier mode
run_one() {
    local model="$1" tier="$2" mode="$3"
    local budget_var="budget_$tier"
    local budget="${!budget_var}"
    local max_sec="${budget%% *}"
    local num_pred="${budget##* }"

    local prompt_fn="${tier}_prompt"
    local crit_fn="${tier}_criteria"
    local base_prompt; base_prompt=$("$prompt_fn")
    local full_prompt; full_prompt=$(wrap_mode "$mode" "$base_prompt")

    local art_dir="$OUT/artifacts/${model//:/_}/$tier/$mode"
    mkdir -p "$art_dir"
    local reply_file="$art_dir/reply.txt"

    # Capture RAM before the call
    local ram_before; ram_before=$(awk '/MemAvailable/ {print int($2/1024); exit}' /proc/meminfo 2>/dev/null)
    local t0; t0=$(date +%s%N)

    # Build Ollama payload safely (JSON-escape the prompt via python)
    local payload
    payload=$(python3 -c "
import json, sys
p = sys.stdin.read()
print(json.dumps({
    'model':  '$model',
    'prompt': p,
    'stream': False,
    'options': {'num_predict': $num_pred, 'temperature': 0.2}
}))
" <<<"$full_prompt")

    # Fire the request
    local response_file="$art_dir/raw.json"
    local verdict="RED"
    local note=""
    local response=""
    local tokens_s=""
    local elapsed=""

    if timeout "$max_sec" curl -sf -m "$max_sec" -X POST http://localhost:11434/api/generate \
        -H 'Content-Type: application/json' \
        -d "$payload" -o "$response_file" 2>/dev/null; then
        local t1; t1=$(date +%s%N)
        elapsed=$(awk -v ns="$((t1 - t0))" 'BEGIN {printf "%.2f", ns/1e9}')
        response=$(python3 -c "import json; print(json.load(open('$response_file')).get('response',''))" 2>/dev/null)
        echo "$response" > "$reply_file"

        # Tokens/sec from Ollama's eval_count / eval_duration
        tokens_s=$(python3 -c "
import json
d = json.load(open('$response_file'))
ec = d.get('eval_count', 0)
ed = d.get('eval_duration', 0)
print(f'{ec/(ed/1e9):.1f}' if ed else '0')
" 2>/dev/null)
    else
        local t1; t1=$(date +%s%N)
        elapsed=$(awk -v ns="$((t1 - t0))" 'BEGIN {printf "%.2f", ns/1e9}')
        note="TIMEOUT/ERR after ${elapsed}s"
        echo "(no response)" > "$reply_file"
    fi

    local ram_after; ram_after=$(awk '/MemAvailable/ {print int($2/1024); exit}' /proc/meminfo 2>/dev/null)
    local ram_delta=$((ram_before - ram_after))

    # Score — check criteria patterns against the response
    local passed=0 failed=0 criteria_count=0 failed_labels=""
    if [ -n "$response" ]; then
        # Split AI-provided files into the artifact dir (intermediate/pro formats)
        if grep -q '===FILE:' "$reply_file"; then
            python3 - "$reply_file" "$art_dir" <<'PY'
import sys, re, pathlib
text = pathlib.Path(sys.argv[1]).read_text()
out  = pathlib.Path(sys.argv[2])
parts = re.split(r'===FILE:\s*([^=]+?)\s*===', text)
# parts: ['', 'filename1', 'body1', 'filename2', 'body2', ...]
i = 1
while i < len(parts) - 1:
    fname = parts[i].strip()
    body  = parts[i+1]
    # strip trailing ===END=== or next file marker residue
    body = re.sub(r'===END===.*$', '', body, flags=re.DOTALL).strip()
    if fname and body:
        (out / fname).write_text(body + '\n')
    i += 2
PY
        fi

        while IFS='|' read -r label regex; do
            [ -z "$label" ] && continue
            criteria_count=$((criteria_count + 1))
            if echo "$response" | grep -qE "$regex"; then
                passed=$((passed + 1))
            else
                failed=$((failed + 1))
                failed_labels="${failed_labels}${label},"
            fi
        done < <("$crit_fn")

        # Verdict
        if [ "$failed" -eq 0 ] && [ "$criteria_count" -gt 0 ]; then
            verdict="GREEN"
        elif [ "$passed" -gt 0 ] && [ $((passed * 2)) -ge "$criteria_count" ]; then
            verdict="YELLOW"
        else
            verdict="RED"
        fi

        # Truncation check — if response looks cut mid-stream, flag it
        if [ "$(python3 -c "import json,os; d=json.load(open('$response_file')); print('TRUNC' if d.get('done_reason')=='length' else 'OK')")" = "TRUNC" ]; then
            note="${note}${note:+ · }hit num_predict ceiling (truncated)"
            [ "$verdict" = "GREEN" ] && verdict="YELLOW"
        fi
    fi

    # Runnability check for pro tier — try to parse/python-compile the artifact
    if [ "$tier" = "pro" ] && [ -f "$art_dir/notes_server.py" ]; then
        if python3 -c "import ast; ast.parse(open('$art_dir/notes_server.py').read())" 2>/dev/null; then
            passed=$((passed + 1))
            criteria_count=$((criteria_count + 1))
        else
            failed=$((failed + 1))
            criteria_count=$((criteria_count + 1))
            failed_labels="${failed_labels}python_parse,"
            verdict="RED"
        fi
    fi
    if [ "$tier" = "intermediate" ] && [ -f "$art_dir/count.py" ]; then
        if python3 -c "import ast; ast.parse(open('$art_dir/count.py').read())" 2>/dev/null; then
            passed=$((passed + 1))
        else
            failed=$((failed + 1))
            failed_labels="${failed_labels}python_parse,"
            [ "$verdict" = "GREEN" ] && verdict="YELLOW"
        fi
    fi

    local color="${BR:-}"
    [ "$verdict" = "YELLOW" ] && color="${BY:-}"
    [ "$verdict" = "GREEN"  ] && color="${BG:-}"

    log ""
    log "  ${BW:-}── ${model} · ${tier} · ${mode} ──${X:-}"
    log "     elapsed:   ${elapsed}s  (budget ${max_sec}s)"
    log "     tokens/s:  ${tokens_s:-?}"
    log "     ram_delta: ${ram_delta} MB (${ram_before} → ${ram_after} avail)"
    log "     criteria:  ${passed}/${criteria_count} passed"
    [ -n "$failed_labels" ] && log "     missed:    ${failed_labels%,}"
    [ -n "$note" ]          && log "     note:      ${note}"
    log "     verdict:   ${color}${verdict}${X:-}"

    # Save row for summary
    local row
    row=$(python3 -c "
import json
print(json.dumps({
  'rep': ${BENCH_REP:-1},
  'model': '$model', 'tier': '$tier', 'mode': '$mode',
  'elapsed_s': '${elapsed}', 'tokens_s': '${tokens_s:-0}',
  'ram_before_mb': ${ram_before:-0}, 'ram_after_mb': ${ram_after:-0}, 'ram_delta_mb': ${ram_delta:-0},
  'passed': ${passed}, 'failed': ${failed}, 'criteria_count': ${criteria_count},
  'verdict': '${verdict}', 'missed': '${failed_labels%,}', 'note': '${note}'
}))
" 2>/dev/null)
    RESULTS+=("$row")
}

# ── Preflight ─────────────────────────────────────────────────
log ""
log "${BC:-}╔════════════════════════════════════════════════════════╗${X:-}"
log "${BC:-}║${X:-}  ${BW:-}🥷 MASTER AI BENCHMARK — nothing idle, nothing spared${X:-}  ${BC:-}║${X:-}"
log "${BC:-}║${X:-}  ${D:-}local + cloud + vision + services · pushed to limits${X:-}    ${BC:-}║${X:-}"
log "${BC:-}╚════════════════════════════════════════════════════════╝${X:-}"
log ""
log "  local models:  ${LOCAL_MODELS[*]}"
log "  cloud slots:   ${CLOUD_PROVIDERS[*]:-(none — no keys in ~/.master_ai_keys)}"
log "  tiers:         ${TIERS[*]}"
log "  modes:         ${MODES[*]}"
log "  vision tier:   $([ "$SKIP_VISION" = "0" ] && echo yes || echo skipped)"
log "  tts summary:   $([ "$SKIP_TTS" = "0" ] && echo yes || echo skipped)"
log "  output dir:    $OUT"
log ""

# Confirm Ollama is reachable
if ! curl -sf -m 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
    log "${BR:-}❌ Ollama not reachable on :11434 — aborting${X:-}"
    exit 1
fi

# Confirm local models exist
for m in "${LOCAL_MODELS[@]}"; do
    if ! curl -sf -m 3 http://localhost:11434/api/tags | grep -q "\"$m\""; then
        log "${BY:-}⚠ model $m not pulled — run: ollama pull $m${X:-}"
    fi
done

# ── Services preflight — every tool gets used ─────────────────
log ""
log "${BC:-}  ── services preflight (nothing idle) ──${X:-}"
SERVICES_OK=0
services_result() {
    local tag="$1" url="$2"
    if curl -sf -m 3 "$url" -o /dev/null 2>/dev/null; then
        log "     ${BG:-}✓${X:-} $tag reachable"
        SERVICES_OK=$((SERVICES_OK + 1))
    else
        log "     ${BY:-}⚠${X:-} $tag not reachable"
    fi
}
services_result "stt_server /profile"    "http://localhost:8080/profile"
services_result "stt_server /thoughts"   "http://localhost:8080/thoughts"
services_result "stt_server /peers"      "http://localhost:8080/peers"
services_result "stt_server /node_info"  "http://localhost:8080/node_info"
services_result "stt_server /sys"        "http://localhost:8080/sys"
services_result "stt_server /keys"       "http://localhost:8080/keys"
services_result "stt_server /sessions"   "http://localhost:8080/sessions"
services_result "ollama /api/tags"       "http://localhost:11434/api/tags"
if curl -sf -m 2 http://localhost:5050/ -o /dev/null 2>/dev/null \
    || curl -sf -m 2 -X POST http://localhost:5050/speak \
        -H 'Content-Type: application/json' -d '{"text":"probe"}' -o /dev/null 2>/dev/null; then
    log "     ${BG:-}✓${X:-} tts :5050 responding"
    SERVICES_OK=$((SERVICES_OK + 1))
else
    log "     ${BY:-}⚠${X:-} tts :5050 not reachable"
fi
MESH_TOKEN=$(python3 -c "import json; print(json.load(open('$HOME/.master_ai_mesh.json')).get('mesh_token',''))" 2>/dev/null)
if [ -n "$MESH_TOKEN" ]; then
    log "     ${BG:-}✓${X:-} mesh_token present (federated /ask ready)"
else
    log "     ${BY:-}⚠${X:-} mesh_token missing — /ask will 503"
fi
log "     services reachable: $SERVICES_OK / 9"

SINGLE_REP_RUNS=$(( (${#LOCAL_MODELS[@]} + ${#CLOUD_PROVIDERS[@]}) * ${#TIERS[@]} * ${#MODES[@]} ))
[ "$SKIP_VISION" = "0" ] && SINGLE_REP_RUNS=$((SINGLE_REP_RUNS + 1))
TOTAL_RUNS=$(( SINGLE_REP_RUNS * REPS ))
log ""
log "  reps:        $REPS  ($SINGLE_REP_RUNS runs per rep · $TOTAL_RUNS total)"
log ""
BENCH_START=$(date +%s)

# ── Cloud rescue (same scoring, different backend) ────────────
# Run the same prompt on a cloud provider. Returns a result row the same
# shape as run_one — just with model set to "cloud:<provider>".
run_cloud() {
    local provider="$1" tier="$2" mode="$3"
    local budget_var="budget_$tier"
    local budget="${!budget_var}"
    local max_sec="${budget%% *}"

    local prompt_fn="${tier}_prompt"
    local crit_fn="${tier}_criteria"
    local base_prompt; base_prompt=$("$prompt_fn")
    local full_prompt; full_prompt=$(wrap_mode "$mode" "$base_prompt")

    local art_dir="$OUT/artifacts/cloud_${provider}/$tier/$mode"
    mkdir -p "$art_dir"

    local url="" auth="" cloud_model=""
    case "$provider" in
        groq)
            [ -z "$GROQ_KEY" ] && return
            url="https://api.groq.com/openai/v1/chat/completions"
            auth="Authorization: Bearer $GROQ_KEY"
            cloud_model="llama-3.3-70b-versatile"
            ;;
        openrouter)
            [ -z "$OPENROUTER_KEY" ] && return
            url="https://openrouter.ai/api/v1/chat/completions"
            auth="Authorization: Bearer $OPENROUTER_KEY"
            cloud_model="deepseek/deepseek-r1:free"
            ;;
        *) return ;;
    esac

    local payload
    payload=$(python3 -c "
import json, sys
p = sys.stdin.read()
print(json.dumps({
    'model': '$cloud_model',
    'messages': [{'role':'user','content': p}],
    'temperature': 0.2
}))
" <<<"$full_prompt")

    local ram_before; ram_before=$(awk '/MemAvailable/ {print int($2/1024); exit}' /proc/meminfo)
    local t0; t0=$(date +%s%N)
    local response_file="$art_dir/raw.json"
    local response="" verdict="RED" note="" elapsed=""
    local tokens_s="n/a"   # cloud doesn't report tok/s the same way

    if curl -sf -m "$max_sec" -X POST "$url" \
        -H "Content-Type: application/json" -H "$auth" \
        -d "$payload" -o "$response_file" 2>/dev/null; then
        local t1; t1=$(date +%s%N)
        elapsed=$(awk -v ns="$((t1-t0))" 'BEGIN {printf "%.2f", ns/1e9}')
        response=$(python3 -c "
import json
d = json.load(open('$response_file'))
try: print(d['choices'][0]['message']['content'])
except Exception: print('')
" 2>/dev/null)
        echo "$response" > "$art_dir/reply.txt"
    else
        local t1; t1=$(date +%s%N)
        elapsed=$(awk -v ns="$((t1-t0))" 'BEGIN {printf "%.2f", ns/1e9}')
        note="cloud error or timeout"
        echo "(no response)" > "$art_dir/reply.txt"
    fi
    local ram_after; ram_after=$(awk '/MemAvailable/ {print int($2/1024); exit}' /proc/meminfo)
    local ram_delta=$((ram_before - ram_after))

    local passed=0 failed=0 criteria_count=0 failed_labels=""
    if [ -n "$response" ]; then
        if grep -q '===FILE:' "$art_dir/reply.txt"; then
            python3 - "$art_dir/reply.txt" "$art_dir" <<'PY'
import sys, re, pathlib
text = pathlib.Path(sys.argv[1]).read_text()
out  = pathlib.Path(sys.argv[2])
parts = re.split(r'===FILE:\s*([^=]+?)\s*===', text)
i = 1
while i < len(parts) - 1:
    fname = parts[i].strip(); body = parts[i+1]
    body = re.sub(r'===END===.*$', '', body, flags=re.DOTALL).strip()
    if fname and body: (out / fname).write_text(body + '\n')
    i += 2
PY
        fi

        while IFS='|' read -r label regex; do
            [ -z "$label" ] && continue
            criteria_count=$((criteria_count + 1))
            if echo "$response" | grep -qE "$regex"; then
                passed=$((passed + 1))
            else
                failed=$((failed + 1)); failed_labels="${failed_labels}${label},"
            fi
        done < <("$crit_fn")

        if   [ "$failed" -eq 0 ] && [ "$criteria_count" -gt 0 ]; then verdict="GREEN"
        elif [ "$passed" -gt 0 ] && [ $((passed * 2)) -ge "$criteria_count" ]; then verdict="YELLOW"
        else verdict="RED"; fi
    fi

    local color="${BR:-}"
    [ "$verdict" = "YELLOW" ] && color="${BY:-}"
    [ "$verdict" = "GREEN"  ] && color="${BG:-}"

    log ""
    log "  ${BW:-}── CLOUD RESCUE: $provider ($cloud_model) · ${tier} · ${mode} ──${X:-}"
    log "     elapsed: ${elapsed}s   verdict: ${color}${verdict}${X:-}  criteria: ${passed}/${criteria_count}"
    [ -n "$failed_labels" ] && log "     missed:  ${failed_labels%,}"
    [ -n "$note" ]          && log "     note:    ${note}"

    local row
    row=$(python3 -c "
import json
print(json.dumps({
  'rep': ${BENCH_REP:-1},
  'model': 'cloud:$provider', 'tier': '$tier', 'mode': '$mode',
  'elapsed_s': '${elapsed}', 'tokens_s': 'n/a',
  'ram_before_mb': ${ram_before:-0}, 'ram_after_mb': ${ram_after:-0}, 'ram_delta_mb': ${ram_delta:-0},
  'passed': ${passed}, 'failed': ${failed}, 'criteria_count': ${criteria_count},
  'verdict': '${verdict}', 'missed': '${failed_labels%,}', 'note': '${note}'
}))
" 2>/dev/null)
    RESULTS+=("$row")
}

# Inspect the last RESULTS row's verdict — returns 0 if RED or YELLOW
last_verdict_soft() {
    local last_row="${RESULTS[-1]:-}"
    [ -z "$last_row" ] && return 1
    local v; v=$(python3 -c "import json; print(json.loads('''$last_row''').get('verdict',''))" 2>/dev/null)
    case "$v" in RED|YELLOW) return 0 ;; *) return 1 ;; esac
}

# ── Run matrix (endurance-wrapped) ────────────────────────────
# Endurance: repeat the whole matrix $REPS times. Each row gets an extra
# `rep` key injected into the JSON row right before RESULTS+= so we can
# measure variance / drift across reps in the summary.
idx=0
for rep in $(seq 1 "$REPS"); do
    log ""
    log "${BC:-}┌──── REP ${rep} / ${REPS} ────┐${X:-}"

    for model in "${LOCAL_MODELS[@]}"; do
        for tier in "${TIERS[@]}"; do
            for mode in "${MODES[@]}"; do
                idx=$((idx + 1))
                log ""
                log "${BC:-}[$idx/$TOTAL_RUNS][rep ${rep}/${REPS}] ${model} · ${tier} · ${mode}${X:-}"
                BENCH_REP="$rep" run_one "$model" "$tier" "$mode"
            done
        done
    done

    for provider in "${CLOUD_PROVIDERS[@]}"; do
        for tier in "${TIERS[@]}"; do
            for mode in "${MODES[@]}"; do
                idx=$((idx + 1))
                log ""
                log "${BC:-}[$idx/$TOTAL_RUNS][rep ${rep}/${REPS}] cloud:${provider} · ${tier} · ${mode}${X:-}"
                BENCH_REP="$rep" run_cloud "$provider" "$tier" "$mode"
            done
        done
    done
done

# Vision tier — llava against a deterministic tiny red PNG
if [ "$SKIP_VISION" = "0" ] && curl -sf -m 3 http://localhost:11434/api/tags | grep -q '"llava'; then
    idx=$((idx + 1))
    log ""
    log "${BC:-}[$idx/$TOTAL_RUNS] starting: llava · vision · single-shot${X:-}"
    vart="$OUT/artifacts/llava/vision/single"
    mkdir -p "$vart"
    python3 - "$vart/red.png" <<'PY' 2>/dev/null
import base64, sys
png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFUlEQVR4nGP8z8DwH4gYGRgYGBgAJNQDAQAwsAKDkvC7wAAAAABJRU5ErkJggg==")
open(sys.argv[1], "wb").write(png)
PY
    vimg=$(base64 -w0 "$vart/red.png")
    vt0=$(date +%s%N)
    if curl -sf -m 180 -X POST http://localhost:11434/api/generate \
        -H 'Content-Type: application/json' \
        -d "{\"model\":\"llava\",\"prompt\":\"What color is this image? Reply with only one word.\",\"images\":[\"$vimg\"],\"stream\":false,\"options\":{\"num_predict\":10,\"temperature\":0}}" \
        -o "$vart/raw.json" 2>/dev/null; then
        vt1=$(date +%s%N)
        velapsed=$(awk -v ns="$((vt1-vt0))" 'BEGIN {printf "%.2f", ns/1e9}')
        vresp=$(python3 -c "import json; print(json.load(open('$vart/raw.json')).get('response',''))" 2>/dev/null)
        echo "$vresp" > "$vart/reply.txt"
        if echo "$vresp" | grep -qi "red"; then vverdict="GREEN"; vpass=1
        elif [ -n "$vresp" ]; then              vverdict="YELLOW"; vpass=0
        else                                     vverdict="RED"; vpass=0
        fi
        log "  ${BW:-}── llava · vision · single-shot ──${X:-}"
        log "     elapsed: ${velapsed}s   response: '${vresp:0:60}'"
        log "     verdict: $vverdict"
        vrow=$(python3 -c "
import json
print(json.dumps({
  'model':'llava','tier':'vision','mode':'single',
  'elapsed_s':'${velapsed}','tokens_s':'n/a',
  'ram_before_mb':0,'ram_after_mb':0,'ram_delta_mb':0,
  'passed':${vpass},'failed':$((1-vpass)),'criteria_count':1,
  'verdict':'${vverdict}','missed':'','note':'2x2 red PNG → asked for color'
}))")
        RESULTS+=("$vrow")
    else
        log "  ${BR:-}llava vision call failed${X:-}"
    fi
fi

BENCH_END=$(date +%s)
BENCH_ELAPSED=$((BENCH_END - BENCH_START))

# ── Summary: JSON + Markdown ──────────────────────────────────
{
    echo "["
    for i in "${!RESULTS[@]}"; do
        echo -n "${RESULTS[$i]}"
        [ "$i" -lt "$((${#RESULTS[@]} - 1))" ] && echo "," || echo ""
    done
    echo "]"
} > "$SUMMARY_JSON"

{
    echo "# Master AI benchmark — $(date -Iseconds)"
    echo ""
    echo "Runtime: ${BENCH_ELAPSED}s · Local: ${LOCAL_MODELS[*]:-none} · Cloud: ${CLOUD_PROVIDERS[*]:-none} · Tiers: ${TIERS[*]} · Modes: ${MODES[*]}"
    echo ""
    echo "| Model | Tier | Mode | Elapsed | Tok/s | Passed | Verdict | Note |"
    echo "|---|---|---|---|---|---|---|---|"
    for row in "${RESULTS[@]}"; do
        python3 -c "
import json, sys
d = json.loads('''$row''')
print(f\"| {d['model']} | {d['tier']} | {d['mode']} | {d['elapsed_s']}s | {d['tokens_s']} | {d['passed']}/{d['criteria_count']} | {d['verdict']} | {d.get('note','') or ''} |\")" 2>/dev/null
    done
    echo ""
    echo "## Verdict tally"
    python3 -c "
import json
rows = json.load(open('$SUMMARY_JSON'))
from collections import Counter
c = Counter(r['verdict'] for r in rows)
for v in ['GREEN','YELLOW','RED']:
    print(f'- {v}: {c.get(v,0)}')
" 2>/dev/null
    echo ""
    echo "## Qwen failure points (RED runs only)"
    python3 -c "
import json
rows = json.load(open('$SUMMARY_JSON'))
reds = [r for r in rows if r['verdict'] == 'RED']
if not reds: print('(none — all runs met enough criteria)')
for r in reds:
    print(f\"- **{r['model']} · {r['tier']} · {r['mode']}** — {r['passed']}/{r['criteria_count']}; missed: {r.get('missed','')}; {r.get('note','')}\")
" 2>/dev/null
} > "$SUMMARY_MD"

log ""
log "${BC:-}═══════════════════════════════════════════════${X:-}"
log "  total time: ${BENCH_ELAPSED}s"
log "  summary:    $SUMMARY_MD"
log "  json:       $SUMMARY_JSON"
log ""

# Compute a one-line verdict tally for the voice summary
greens=$(python3 -c "import json; print(sum(1 for r in json.load(open('$SUMMARY_JSON')) if r['verdict']=='GREEN'))" 2>/dev/null)
yellows=$(python3 -c "import json; print(sum(1 for r in json.load(open('$SUMMARY_JSON')) if r['verdict']=='YELLOW'))" 2>/dev/null)
reds=$(python3 -c "import json; print(sum(1 for r in json.load(open('$SUMMARY_JSON')) if r['verdict']=='RED'))" 2>/dev/null)
minutes=$(( BENCH_ELAPSED / 60 ))
log "  ${BG:-}GREEN ${greens:-0}${X:-} · ${BY:-}YELLOW ${yellows:-0}${X:-} · ${BR:-}RED ${reds:-0}${X:-}  in ${minutes}m"
log ""

# Voice the verdict if TTS is up — last step uses the last tool.
if [ "$SKIP_TTS" = "0" ]; then
    verdict_text="Benchmark complete. ${greens:-0} green, ${yellows:-0} yellow, ${reds:-0} red. Ran in ${minutes} minutes."
    if curl -sf -m 10 -X POST http://localhost:5050/speak \
        -H 'Content-Type: application/json' \
        -d "$(python3 -c "import json,sys;print(json.dumps({'text':sys.argv[1]}))" "$verdict_text")" \
        -o /dev/null 2>/dev/null; then
        log "  ${D:-}(tts spoke the verdict)${X:-}"
    fi
fi

if [ "$SHORT" = "0" ]; then
    cat "$SUMMARY_MD"
fi
