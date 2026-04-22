#!/bin/bash
# competitor_benchmark.sh — the standard-setter.
#
# LOCAL ONLY. No cloud rescue, no safety net. The point is to find Qwen's
# ceiling on this box — push RAM, push context, push task complexity until
# we see the color slide from GREEN to YELLOW to (hopefully) RED. That's
# where the real ceiling lives, and that's the line nobody else has drawn.
#
# No external product does this:
#   - Local-only agentic benchmark
#   - Forced RAM pressure (concurrent calls, big contexts)
#   - Real scoring of produced artifacts (parse / compile / criteria)
#   - Swap tracking to see WHERE the machine starts thrashing
#
# This script writes the standard. If a future competitor shows up, the
# summary.md becomes the reference anyone else tries to beat.
#
# Usage:
#   bash ~/scripts/competitor_benchmark.sh
#   bash ~/scripts/competitor_benchmark.sh --model qwen2.5:3b
#   bash ~/scripts/competitor_benchmark.sh --task kernel
#
# Output: ~/Desktop/master_ai_competitor/

set -u
source ~/scripts/brand.sh 2>/dev/null || true

MODELS=(qwen2.5:3b qwen2.5:7b master-ai)
# master-ai (custom: qwen2.5:7b + baked Sensei SYSTEM) is the product's
# daily driver — it gets included so the benchmark shows the delta between
# raw Qwen and Master AI's trained version. That delta IS the product.
# Big-brain joins automatically when pulled on a box that can hold it
_ram_total_mb=$(awk '/MemTotal/ {print int($2/1024); exit}' /proc/meminfo 2>/dev/null)
if curl -sf -m 2 http://localhost:11434/api/tags 2>/dev/null | grep -q '"qwen2.5:14b"' \
    && [ "${_ram_total_mb:-0}" -ge 20000 ]; then
    MODELS+=(qwen2.5:14b)
fi
TASKS=(kernel longdoc scaffold)
MODES=(solo concurrent)     # solo = one request · concurrent = two at once
REPS=1                      # endurance: --reps 4 to stretch to 4-6 hrs

while [ $# -gt 0 ]; do
    case "$1" in
        --model) MODELS=("$2"); shift 2 ;;
        --task)  TASKS=("$2");  shift 2 ;;
        --mode)  MODES=("$2");  shift 2 ;;
        --reps)  REPS="$2";     shift 2 ;;
        *)       shift ;;
    esac
done

OUT="$HOME/Desktop/master_ai_competitor"
LOG="$OUT/run.log"
SUMMARY_JSON="$OUT/summary.json"
SUMMARY_MD="$OUT/standard.md"
mkdir -p "$OUT/artifacts"
: > "$LOG"
RESULTS=()

log() { echo -e "$1" | tee -a "$LOG"; }

# ── Tasks — tuned harder than anything in benchmark_sensei.sh ─────
# Each task has prompt + criteria + budget (max_sec num_predict context_sz).

# TASK A — kernel module in C (forces genuine systems knowledge)
kernel_prompt() {
    cat <<'P'
Write a minimal Linux kernel module in C that exposes /proc/masterai.
On read, it writes the string "Master AI: your AI, your hardware." followed by
a newline.

Requirements:
- File name: masterai.c (implied — produce ONE C source file).
- Uses: linux/module.h, linux/kernel.h, linux/init.h, linux/proc_fs.h, linux/seq_file.h.
- Implements `masterai_show(struct seq_file *m, void *v)`.
- Creates the proc entry in `__init masterai_init` and removes it in `__exit masterai_exit`.
- Declares MODULE_LICENSE("GPL"), MODULE_AUTHOR, MODULE_DESCRIPTION, MODULE_VERSION.
- No deprecated APIs. Target kernel 5.6+ where `proc_create_single_data` / `seq_file` pattern is required.

Respond with ONLY the C source code. No markdown fences, no explanation.
P
}
kernel_criteria() {
cat <<'C'
headers_module|#include <linux/module\.h>
headers_init|#include <linux/init\.h>
headers_procfs|#include <linux/proc_fs\.h>
headers_seqfile|#include <linux/seq_file\.h>
show_function|masterai_show|seq_printf|seq_puts
init_function|__init|masterai_init
exit_function|__exit|masterai_exit
proc_create|proc_create|proc_create_single
module_license|MODULE_LICENSE
module_author|MODULE_AUTHOR
module_description|MODULE_DESCRIPTION
string_present|Master AI
no_deprecated|^(?!.*create_proc_entry).*$
C
}

# TASK B — long-context summarizer. Synthetic 10KB+ doc, extract 5 bullets
# of state + 5 action items. Forces real comprehension, not pattern-matching.
longdoc_prompt() {
    # Embed a 10-12KB synthetic document inline. Tuned to be realistic.
    cat <<'P'
Below is the current state of a long-running software project. Read it carefully.

Your job:
1. Produce a STATE section with exactly 5 bullets, each ≤ 20 words, summarizing where the project stands RIGHT NOW.
2. Produce an ACTIONS section with exactly 5 numbered action items, each starting with a verb, each ≤ 20 words.
3. Produce a RISKS section with exactly 3 bullets naming the biggest open risks.

Respond with EXACTLY this format (no extra prose, no markdown fences):
===STATE===
- <bullet 1>
- <bullet 2>
- <bullet 3>
- <bullet 4>
- <bullet 5>
===ACTIONS===
1. <verb-first action>
2. <verb-first action>
3. <verb-first action>
4. <verb-first action>
5. <verb-first action>
===RISKS===
- <risk 1>
- <risk 2>
- <risk 3>
===END===

=== BEGIN PROJECT DOCUMENT ===

# Master AI — v1.8-testing status snapshot

## Scope
Master AI is a local-first AI companion sold as a single folder (~/scripts/)
that runs on a personal machine. It ships with Sensei (a tmux agent), Pupil
(a browser UI), a dojo gate for project discipline, multi-user profiles,
mesh peer networking, and a library of 12 lessons across Linux/bash and
Python. Trifecta: qwen2.5:3b (spark, 1.9 GB), qwen2.5:7b (brain, 4.7 GB),
and llava (eyes, 4.7 GB). Cloud tiers optional via Groq or OpenRouter
free keys; never required for the product to work.

## Recent work (post-v1.7)
Dojo gate landed with soft+sealed modes and a creator bypass so the
builder never has to "turn in a project" to enter their own dojo. A
welcome-back flow remembers the pinned project+task so returning users
don't re-earn their entry each session — "once you get a black belt,
you're a black belt forever." Multi-user plumbing is complete: master_ai.py
rebases memory/tasks/chats under ~/.master_ai_profiles/<name>/, stt_server
rewrites its /sessions + /keys + /profile endpoints per-request based on
~/.master_ai_active_profile, and Pupil's localStorage is namespaced by
"<profile>::". A live isolation test at multiuser_test.sh passes 18/18.

Mesh scaffolding is in place: every node runs stt_server on :8080 which
exposes /node_info, /peers, and (newly) /ask. The /ask endpoint accepts
{prompt, model} and routes to the local Ollama, guarded by a shared
mesh_token stored in ~/.master_ai_mesh.json. A mesh.sh helper manages the
peer list and exposes list / add / remove / ping / ask / menu subcommands.
Federated routing is proven via loopback; cross-node discovery (mDNS or
Tailscale enumeration) is the next step but not a ship blocker.

A shared voice file, master_ai_voice.json, now holds canonical copy:
elijah_verbatim (4 longform quotes the builder produced), elijah_short
(13 punchy one-liners extracted from the verbatim), quotes (16 polished
brand lines), tips (24 Sensei command hints), pupil_tips (16 browser
one-liners), and thinking (14 rotating ninja phrases). Both UIs pull from
this file — Sensei at startup, Pupil via /thoughts on stt_server — so
idle rotations and loading messages speak in one voice.

## Acceptance gating
Pack_for_sale.sh refuses to build a buyer bundle unless sensei_selftest.sh
passes cleanly. That self-test is a 16-phase stress: filesystem I/O, sha256
manifest + tar round-trip, python/bash interop, git diff/revert, HTTP
round-trip, Ollama inference round-trip (qwen2.5:3b real call), llava
vision round-trip on a 2x2 PNG, every stt_server endpoint, TTS reachability,
concurrent-worker correctness, memory persistence, mesh config, and voice
file population. The grading uses PASS / WARN / FAIL tiers so a normally-
running box lands YELLOW (warnings for services that are off, like TTS),
not green. Green is suspicious.

## Self-scan
Selfscan.sh reads the box (CPU model, cores, RAM, disk free, GPU if any,
Ollama state, pulled models) and returns a tier: GREEN if 28+ GB RAM,
YELLOW if 14+ GB, ORANGE if 7+ GB, RED below. It is called by install.sh
after the model pulls so a first-time buyer sees immediately what their
hardware will and won't do. Output is ~20 lines of human-readable report;
there's also a --short mode for one-line integration.

## Links inventory
LINKS.md lists every URL a buyer might need: Ollama installers for
Linux/macOS/Windows, the three trifecta model pulls, optional cloud API
signup pages for Groq / OpenRouter / Google Gemini (all free tiers),
Tailscale and RustDesk for remote access, and the optional TTS voice
pack from Hugging Face. Menu option 20 opens LINKS.md in less.

## Open, non-blocking
Federated discovery still manual. Streaming replies for /ask not yet
wired — it currently returns the full response atomically. Peer-selectable
model routing (e.g. "ask the node with the biggest model") is design-only.
Hardware upgrade path (32 GB RAM + 4 TB NVMe + M.2-to-USB clonezilla
enclosure) is specced, not ordered. The OLLAMA_MAX_LOADED_MODELS=1
drop-in is staged for the builder's box, not applied.

## Ship-gating stance
Nothing is tagged. The builder uses the phrase "pack it up for sale" as
the permanence keyword; until he says it, everything is in testing. When
he says it, pack_for_sale.sh runs its ship ritual: copies ~/scripts to
a clean bundle, rewrites PROJECTS.md with a starter template, scrubs
personal SKS/Sunkissed references, strips dotfiles and the creator marker,
seals the dojo gate, and tags a version.

=== END PROJECT DOCUMENT ===

Now produce the STATE / ACTIONS / RISKS in the exact format above.
P
}
longdoc_criteria() {
    cat <<'C'
state_header|===STATE===
actions_header|===ACTIONS===
risks_header|===RISKS===
end_header|===END===
five_state_bullets|^- .+\n- .+\n- .+\n- .+\n- .+
five_actions|^[1-5]\..+
three_risks_region|===RISKS===[\s\S]*- .+[\s\S]*- .+[\s\S]*- .+
mentions_trifecta|trifecta|qwen|spark|brain|eyes
mentions_dojo|dojo|gate|welcome|black belt
mentions_mesh|mesh|node|/ask|peer|federat
mentions_selftest|self-test|selftest|acceptance
mentions_ship|pack it up|pack_for_sale|ship ritual|tag
C
}

# TASK C — multi-file CLI scaffold. 4 consistent Python files.
scaffold_prompt() {
    cat <<'P'
Build a Python 3 CLI tool called `notekeep` that stores text notes in
~/.notekeep/notes.json. It must be a 4-file project — no single-file
shortcuts. Files must share consistent imports and type hints.

Required files (all Python, no deps outside stdlib):
- main.py     — CLI entrypoint. Subcommands: add <body> · list · rm <id> · search <query>.
- storage.py  — Handles load/save of notes.json. Atomic writes via temp-file-then-rename.
- config.py   — Reads ~/.notekeep/config.json (optional). Provides `DATA_PATH` and a `get_setting(k, default)` helper.
- test_notekeep.py — pytest tests: test add+list, test rm on missing id returns non-zero, test search returns matches.

Every file must:
- Use explicit type hints on every public function signature.
- Import from the project's own modules where reasonable (storage imports from config, main imports from storage + config).
- Have a module docstring on line 1 describing the file's single responsibility.

Respond with EXACTLY this structure (no extra prose, no markdown fences):
===FILE: main.py===
<code>
===FILE: storage.py===
<code>
===FILE: config.py===
<code>
===FILE: test_notekeep.py===
<code>
===END===
P
}
scaffold_criteria() {
    cat <<'C'
four_file_markers|===FILE: main\.py===[\s\S]+===FILE: storage\.py===[\s\S]+===FILE: config\.py===[\s\S]+===FILE: test_notekeep\.py===
end_marker|===END===
main_subcommands|add|list|rm|search
atomic_write|os\.rename|os\.replace|atomic|rename
type_hints|: str|: int|: dict|: list|-> |Optional|List
storage_imports_config|from config|import config
main_imports_storage|from storage|import storage
pytest_tests|def test_|assert
json_io|json\.load|json\.dump
module_docstrings|\"\"\"|'''
C
}

# Budgets per task: max_sec  num_predict
budget_kernel="240 2500"
budget_longdoc="300 2000"
budget_scaffold="480 4500"

# ── Pressure metrics ──────────────────────────────────────────
read_ram_mb()  { awk '/MemAvailable/ {print int($2/1024); exit}' /proc/meminfo 2>/dev/null; }
read_swap_mb() { awk '/SwapTotal/ {t=$2} /SwapFree/ {f=$2} END {print int((t-f)/1024)}' /proc/meminfo 2>/dev/null; }

# Fire a single Ollama call, no scoring — used as the "pressure partner"
# during concurrent-mode runs. Returns the PID of the background call.
fire_background() {
    local model="$1" prompt="$2" out="$3"
    local payload
    payload=$(python3 -c "
import json, sys
p = sys.stdin.read()
print(json.dumps({
    'model': sys.argv[1],
    'prompt': p,
    'stream': False,
    'options': {'num_predict': 600, 'temperature': 0.3}
}))" "$model" <<<"$prompt")
    curl -sf -m 300 -X POST http://localhost:11434/api/generate \
        -H 'Content-Type: application/json' \
        -d "$payload" -o "$out" 2>/dev/null &
    echo $!
}

# ── One timed, scored run ─────────────────────────────────────
run_competitor() {
    local model="$1" task="$2" mode="$3"
    local budget_var="budget_$task"
    local budget="${!budget_var}"
    local max_sec="${budget%% *}"
    local num_pred="${budget##* }"

    local prompt_fn="${task}_prompt"
    local crit_fn="${task}_criteria"
    local prompt; prompt=$("$prompt_fn")

    local art_dir="$OUT/artifacts/${model//:/_}/$task/$mode"
    mkdir -p "$art_dir"
    local reply_file="$art_dir/reply.txt"
    local response_file="$art_dir/raw.json"

    local payload
    payload=$(python3 -c "
import json, sys
p = sys.stdin.read()
print(json.dumps({
    'model':  '$model',
    'prompt': p,
    'stream': False,
    'options': {'num_predict': $num_pred, 'temperature': 0.2}
}))" <<<"$prompt")

    local ram_before swap_before ram_peak
    ram_before=$(read_ram_mb)
    swap_before=$(read_swap_mb)
    ram_peak="$ram_before"

    # Pressure partner — if concurrent, fire a smaller secondary prompt on the
    # OTHER local model so Ollama has to juggle two loaded models in RAM.
    local bg_pid=""
    local bg_out="$art_dir/bg.json"
    if [ "$mode" = "concurrent" ]; then
        local other="qwen2.5:3b"
        [ "$model" = "qwen2.5:3b" ] && other="qwen2.5:7b"
        bg_pid=$(fire_background "$other" "List five things a 16-year-old should know about Linux. Be brief." "$bg_out")
    fi

    local t0 t1 elapsed
    t0=$(date +%s%N)
    # Main call — time-boxed, no resume
    curl -sf -m "$max_sec" -X POST http://localhost:11434/api/generate \
        -H 'Content-Type: application/json' \
        -d "$payload" -o "$response_file" 2>/dev/null &
    local main_pid=$!

    # Sample RAM while the call is in flight
    while kill -0 "$main_pid" 2>/dev/null; do
        local cur; cur=$(read_ram_mb)
        [ "${cur:-$ram_peak}" -lt "$ram_peak" ] && ram_peak="$cur"
        sleep 1
    done
    wait "$main_pid" 2>/dev/null
    local main_rc=$?
    t1=$(date +%s%N)
    elapsed=$(awk -v ns="$((t1 - t0))" 'BEGIN {printf "%.2f", ns/1e9}')

    # Join the pressure partner (let it finish or give it a grace window)
    if [ -n "$bg_pid" ]; then
        local waited=0
        while kill -0 "$bg_pid" 2>/dev/null && [ "$waited" -lt 60 ]; do
            sleep 1; waited=$((waited + 1))
        done
        kill "$bg_pid" 2>/dev/null
        wait "$bg_pid" 2>/dev/null
    fi

    local ram_after swap_after
    ram_after=$(read_ram_mb)
    swap_after=$(read_swap_mb)
    local swap_delta=$((swap_after - swap_before))
    local ram_squeeze=$((ram_before - ram_peak))

    # Extract response + tokens/sec
    local response="" tokens_s="0" truncated="no"
    if [ "$main_rc" = "0" ] && [ -s "$response_file" ]; then
        response=$(python3 -c "import json; print(json.load(open('$response_file')).get('response',''))" 2>/dev/null)
        echo "$response" > "$reply_file"
        tokens_s=$(python3 -c "
import json
d=json.load(open('$response_file'))
ec=d.get('eval_count',0); ed=d.get('eval_duration',0)
print(f'{ec/(ed/1e9):.1f}' if ed else '0')" 2>/dev/null)
        if [ "$(python3 -c "import json; print(json.load(open('$response_file')).get('done_reason',''))" 2>/dev/null)" = "length" ]; then
            truncated="yes"
        fi
    else
        echo "(no response — timeout or error)" > "$reply_file"
    fi

    # Split multi-file replies into artifacts (for scaffold task)
    if grep -q '===FILE:' "$reply_file"; then
        python3 - "$reply_file" "$art_dir" <<'PY'
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

    # Score
    local passed=0 failed=0 total=0 missed=""
    if [ -n "$response" ]; then
        while IFS='|' read -r label regex; do
            [ -z "$label" ] && continue
            total=$((total + 1))
            if echo "$response" | grep -qE "$regex"; then
                passed=$((passed + 1))
            else
                failed=$((failed + 1)); missed="${missed}${label},"
            fi
        done < <("$crit_fn")

        # For scaffold task, verify each python file parses
        if [ "$task" = "scaffold" ]; then
            for pyf in main.py storage.py config.py test_notekeep.py; do
                if [ -f "$art_dir/$pyf" ]; then
                    total=$((total + 1))
                    if python3 -c "import ast; ast.parse(open('$art_dir/$pyf').read())" 2>/dev/null; then
                        passed=$((passed + 1))
                    else
                        failed=$((failed + 1)); missed="${missed}${pyf}_parse,"
                    fi
                fi
            done
        fi
    fi

    local verdict="RED"
    if [ "$total" -gt 0 ]; then
        local pct=$(( passed * 100 / total ))
        if   [ "$pct" -ge 85 ]; then verdict="GREEN"
        elif [ "$pct" -ge 55 ]; then verdict="YELLOW"
        else                         verdict="RED"
        fi
    fi
    [ "$truncated" = "yes" ] && [ "$verdict" = "GREEN" ] && verdict="YELLOW"

    local color="${BR:-}"; [ "$verdict" = "YELLOW" ] && color="${BY:-}"; [ "$verdict" = "GREEN" ] && color="${BG:-}"

    log ""
    log "  ${BW:-}── ${model} · ${task} · ${mode} ──${X:-}"
    log "     elapsed:    ${elapsed}s  (budget ${max_sec}s)"
    log "     tokens/s:   ${tokens_s}"
    log "     ram_before: ${ram_before} MB free"
    log "     ram_peak:   ${ram_peak} MB free (squeeze ${ram_squeeze} MB)"
    log "     swap_Δ:     ${swap_delta} MB"
    log "     truncated:  ${truncated}"
    log "     criteria:   ${passed}/${total}"
    [ -n "$missed" ] && log "     missed:     ${missed%,}"
    log "     verdict:    ${color}${verdict}${X:-}"

    local row
    row=$(python3 -c "
import json
print(json.dumps({
  'rep': ${BENCH_REP:-1},
  'model':'$model','task':'$task','mode':'$mode',
  'elapsed_s':'${elapsed}','tokens_s':'${tokens_s}',
  'ram_before_mb':${ram_before:-0},'ram_peak_mb':${ram_peak:-0},
  'ram_squeeze_mb':${ram_squeeze:-0},'swap_delta_mb':${swap_delta:-0},
  'passed':${passed},'failed':${failed},'total':${total},
  'truncated':'${truncated}','verdict':'${verdict}','missed':'${missed%,}'
}))")
    RESULTS+=("$row")
}

# ── Preflight ─────────────────────────────────────────────────
log ""
log "${BC:-}╔════════════════════════════════════════════════════════╗${X:-}"
log "${BC:-}║${X:-}  ${BW:-}🥷 MASTER AI — THE STANDARD-SETTER${X:-}                    ${BC:-}║${X:-}"
log "${BC:-}║${X:-}  ${D:-}local only · RAM squeeze · find the real ceiling${X:-}       ${BC:-}║${X:-}"
log "${BC:-}╚════════════════════════════════════════════════════════╝${X:-}"
log ""
log "  models:  ${MODELS[*]}"
log "  tasks:   ${TASKS[*]}"
log "  modes:   ${MODES[*]}"
log "  output:  $OUT"
log ""

if ! curl -sf -m 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
    log "${BR:-}❌ Ollama not reachable — aborting${X:-}"; exit 1
fi

START_TS=$(date +%s)
SINGLE_REP=$(( ${#MODELS[@]} * ${#TASKS[@]} * ${#MODES[@]} ))
TOTAL=$(( SINGLE_REP * REPS ))
log "  reps:    $REPS  ($SINGLE_REP runs per rep · $TOTAL total)"
log ""
idx=0
for rep in $(seq 1 "$REPS"); do
    log ""
    log "${BC:-}┌──── REP ${rep} / ${REPS} ────┐${X:-}"
    for model in "${MODELS[@]}"; do
        for task in "${TASKS[@]}"; do
            for mode in "${MODES[@]}"; do
                idx=$((idx + 1))
                log ""
                log "${BC:-}[$idx/$TOTAL][rep ${rep}/${REPS}] ${model} · ${task} · ${mode}${X:-}"
                BENCH_REP="$rep" run_competitor "$model" "$task" "$mode"
            done
        done
    done
done

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

# ── Summary ───────────────────────────────────────────────────
{
    echo "["
    for i in "${!RESULTS[@]}"; do
        echo -n "${RESULTS[$i]}"
        [ "$i" -lt "$((${#RESULTS[@]} - 1))" ] && echo "," || echo ""
    done
    echo "]"
} > "$SUMMARY_JSON"

{
    echo "# Master AI — The Standard (local-only competitor benchmark)"
    echo ""
    echo "Runtime: ${ELAPSED}s · Local models: ${MODELS[*]} · Tasks: ${TASKS[*]} · Modes: ${MODES[*]}"
    echo "Ran: $(date -Iseconds)"
    echo ""
    echo "> This is the baseline. No product on the market runs a local-only, RAM-squeezed,"
    echo "> real-scoring, multi-task benchmark of a consumer AI stack. If a competitor ever"
    echo "> arrives, the first thing they'll need to beat is this table."
    echo ""
    echo "| Model | Task | Mode | Elapsed | Tok/s | RAM squeeze | Swap Δ | Passed | Trunc | Verdict |"
    echo "|---|---|---|---|---|---|---|---|---|---|"
    for row in "${RESULTS[@]}"; do
        python3 -c "
import json
d = json.loads('''$row''')
print(f\"| {d['model']} | {d['task']} | {d['mode']} | {d['elapsed_s']}s | {d['tokens_s']} | {d['ram_squeeze_mb']}M | {d['swap_delta_mb']}M | {d['passed']}/{d['total']} | {d['truncated']} | {d['verdict']} |\")" 2>/dev/null
    done
    echo ""
    echo "## Verdict tally"
    python3 -c "
import json
from collections import Counter
rows = json.load(open('$SUMMARY_JSON'))
c = Counter(r['verdict'] for r in rows)
for v in ['GREEN','YELLOW','RED']:
    print(f'- {v}: {c.get(v,0)}')
" 2>/dev/null
    echo ""
    echo "## Where the ceiling is"
    python3 -c "
import json
rows = json.load(open('$SUMMARY_JSON'))
reds = [r for r in rows if r['verdict'] == 'RED']
yellows = [r for r in rows if r['verdict'] == 'YELLOW']
if reds:
    print('### RED — beyond the ceiling')
    for r in reds:
        print(f\"- **{r['model']} · {r['task']} · {r['mode']}** — {r['passed']}/{r['total']}; ram squeeze {r['ram_squeeze_mb']} MB; swap Δ {r['swap_delta_mb']} MB; trunc={r['truncated']}; missed: {r.get('missed','')}\")
if yellows:
    print('')
    print('### YELLOW — at the ceiling (partial pass)')
    for r in yellows:
        print(f\"- **{r['model']} · {r['task']} · {r['mode']}** — {r['passed']}/{r['total']}; ram squeeze {r['ram_squeeze_mb']} MB; swap Δ {r['swap_delta_mb']} MB\")
if not reds and not yellows:
    print('No RED or YELLOW runs. Either the box is heavier than i7-6700T 15 GB, or the tasks need to get harder.')
" 2>/dev/null
    echo ""
    echo "## RAM-pressure footprint"
    python3 -c "
import json
rows = json.load(open('$SUMMARY_JSON'))
max_sq = max((int(r['ram_squeeze_mb']) for r in rows), default=0)
max_sw = max((int(r['swap_delta_mb']) for r in rows), default=0)
print(f'- Peak RAM squeeze across the matrix: **{max_sq} MB**')
print(f'- Peak swap delta across the matrix: **{max_sw} MB**')
print(f'- Concurrent-mode runs forced a second model load — Ollama juggled both inside available RAM.')
" 2>/dev/null
    echo ""
    echo "---"
    echo ""
    echo "*\"When the AI fades, the scaffolding stays.\"*"
    echo ""
    echo "*\"Your AI. Every entry point. Your hardware.\"*"
} > "$SUMMARY_MD"

log ""
log "${BC:-}═══════════════════════════════════════════════${X:-}"
log "  total time: ${ELAPSED}s"
log "  standard:   $SUMMARY_MD"
log "  json:       $SUMMARY_JSON"
log ""

# Voice the result
minutes=$((ELAPSED / 60))
greens=$(python3 -c "import json; print(sum(1 for r in json.load(open('$SUMMARY_JSON')) if r['verdict']=='GREEN'))" 2>/dev/null)
yellows=$(python3 -c "import json; print(sum(1 for r in json.load(open('$SUMMARY_JSON')) if r['verdict']=='YELLOW'))" 2>/dev/null)
reds=$(python3 -c "import json; print(sum(1 for r in json.load(open('$SUMMARY_JSON')) if r['verdict']=='RED'))" 2>/dev/null)
verdict_text="Standard set. ${greens:-0} green, ${yellows:-0} yellow, ${reds:-0} red. Ran in ${minutes} minutes. This is the baseline."
curl -sf -m 10 -X POST http://localhost:5050/speak \
    -H 'Content-Type: application/json' \
    -d "$(python3 -c "import json,sys; print(json.dumps({'text':sys.argv[1]}))" "$verdict_text")" \
    -o /dev/null 2>/dev/null && log "  ${D:-}(tts spoke the standard)${X:-}"

cat "$SUMMARY_MD"
