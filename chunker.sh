#!/bin/bash
# ============================================================
# CHUNKER — map-reduce for local AI
# Sensei's killer feature for apocalypse mode. Break a big task
# into model-sized chunks, save each chunk to disk as it completes
# (crash-safe, resumable), then merge.
#
# Usage:
#   bash ~/scripts/chunker.sh "write a 10000 word manual for restarting a coal power plant"
#   bash ~/scripts/chunker.sh resume <task_id>
#   bash ~/scripts/chunker.sh list
# ============================================================

set -u
source ~/scripts/brand.sh 2>/dev/null || true
: "${BC:=$(tput bold 2>/dev/null; tput setaf 4 2>/dev/null)}"
: "${BG:=$(tput bold 2>/dev/null; tput setaf 2 2>/dev/null)}"
: "${BY:=$(tput bold 2>/dev/null; tput setaf 3 2>/dev/null)}"
: "${BR:=$(tput bold 2>/dev/null; tput setaf 1 2>/dev/null)}"
: "${BW:=$(tput bold 2>/dev/null; tput setaf 0 2>/dev/null)}"
: "${D:=$(tput setaf 8 2>/dev/null)}"
: "${X:=$(tput sgr0 2>/dev/null)}"

CHUNKS_ROOT="$HOME/.sensei_chunks"
mkdir -p "$CHUNKS_ROOT"

# Default model (overridable with CHUNKER_MODEL env var).
# Use qwen2.5:7b until post-upgrade when qwen3:30b-a3b becomes the default.
MODEL="${CHUNKER_MODEL:-qwen2.5:7b}"
OLLAMA_URL="http://localhost:11434"

# ── helpers ──────────────────────────────────────────────────
slug() { echo "$1" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '_' | cut -c1-40; }

list_tasks() {
    echo ""
    echo -e "  ${BC}active chunked tasks${X}"
    for d in "$CHUNKS_ROOT"/*/; do
        [ -d "$d" ] || continue
        local name
        name=$(basename "$d")
        local plan="$d/plan.json"
        if [ -f "$plan" ]; then
            local done_count total task
            done_count=$(python3 -c "import json;d=json.load(open('$plan'));print(sum(1 for c in d['chunks'] if c.get('done')))" 2>/dev/null)
            total=$(python3 -c "import json;d=json.load(open('$plan'));print(len(d['chunks']))" 2>/dev/null)
            task=$(python3 -c "import json;d=json.load(open('$plan'));print(d['task'][:60])" 2>/dev/null)
            echo -e "  ${BG}·${X} ${BW}$name${X}   ${D}[${done_count}/${total}]${X}  $task"
        fi
    done
    echo ""
}

call_ollama() {
    # args: prompt (required), num_predict (optional, default 2048)
    local prompt="$1"
    local num_predict="${2:-2048}"
    python3 - "$prompt" "$num_predict" "$MODEL" "$OLLAMA_URL" <<'PY'
import sys, json, urllib.request
prompt, num_predict, model, url = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
req = urllib.request.Request(
    url + "/api/generate",
    data=json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "30m",
        "options": {"num_predict": num_predict, "temperature": 0.4},
    }).encode(),
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.loads(r.read().decode())
        print(data.get("response", "").strip())
except Exception as e:
    print(f"[CHUNKER_ERROR] {e}", file=sys.stderr)
    sys.exit(1)
PY
}

# ── plan: ask the model for an outline in JSON ──────────────
# Status messages go to STDERR so they're visible to the user live.
# Only the JSON goes to stdout (that's what $(...) captures).
plan_task() {
    local task="$1"
    echo -e "  ${BC}🥷 planning chunks for:${X} ${BW}${task:0:80}${X}" >&2
    echo -e "  ${D}(cold Ollama start takes 30-90s on CPU — stay patient, no output means it's working)${X}" >&2
    local plan_prompt="You are an outline planner.
Task: $task

Output ONLY a JSON array. No preamble. No closing text.
Each item is one chunk with fields: heading, summary (one sentence), target_words.
Target total output ≈ words implied by the task (default 10000 if unclear).
Per-chunk target_words should be between 1500 and 3500.
Between 4 and 12 chunks total.

Example format:
[
  {\"heading\": \"Introduction\", \"summary\": \"...\", \"target_words\": 2000},
  {\"heading\": \"Safety Procedures\", \"summary\": \"...\", \"target_words\": 3000}
]"
    local raw
    raw=$(call_ollama "$plan_prompt" 2048)
    # Extract the JSON array (first [ to last ])
    local json
    json=$(python3 -c "
import re, sys
s = sys.stdin.read()
m = re.search(r'\[.*\]', s, re.DOTALL)
print(m.group(0) if m else '[]')
" <<< "$raw")
    echo "$json"
}

# ── write a chunk ───────────────────────────────────────────
write_chunk() {
    local task="$1" plan_json="$2" index="$3" heading="$4" target_words="$5" prev_summary="$6"
    local prompt="You are writing chunk ${index} of a larger document.

[ORIGINAL TASK]
$task

[FULL OUTLINE]
$plan_json

[PREVIOUS CHUNKS SUMMARY]
$prev_summary

[YOUR CHUNK]
Heading: $heading
Target length: ~$target_words words.

Rules:
- Write ONLY this chunk. Do not repeat previous chunks.
- Do not write the full outline again.
- Start directly with your content.
- End with a single-sentence wrap-up so the next chunk picks up cleanly.
- Use markdown (## ### lists code blocks where appropriate)."

    local npredict=$(( target_words * 3 / 2 ))   # rough tokens ≈ 1.3× words, round up
    [ "$npredict" -gt 8000 ] && npredict=8000
    call_ollama "$prompt" "$npredict"
}

# ── merge: final smoothing pass ─────────────────────────────
merge_chunks() {
    local task_dir="$1"
    local task="$2"
    echo -e "  ${BC}🥷 merging chunks...${X}"
    local combined=""
    for f in "$task_dir"/chunk_*.md; do
        combined+=$'\n\n'"$(cat "$f")"
    done
    local merge_prompt="Original task: $task

Below are chunks written one at a time. Smooth transitions, fix any contradictions, keep all content. Do not drop material. Do not summarize. Output the full unified document.

$combined"
    # This is a big request — warn if it's likely to exceed context
    local wc
    wc=$(echo "$combined" | wc -w)
    if [ "$wc" -gt 12000 ]; then
        echo -e "  ${BY}⚠ merge input is ${wc} words — may exceed model context.${X}"
        echo -e "  ${BY}  Falling back to concatenation + transition pass instead.${X}"
        {
            echo "# $task"
            echo ""
            for f in "$task_dir"/chunk_*.md; do
                cat "$f"
                echo ""
            done
        } > "$task_dir/final.md"
    else
        call_ollama "$merge_prompt" 12000 > "$task_dir/final.md"
    fi
    echo -e "  ${BG}✅ final.md written:${X} $task_dir/final.md"
}

# ── execute: walk the plan ───────────────────────────────────
run_task() {
    local task_dir="$1"
    local plan_file="$task_dir/plan.json"
    [ ! -f "$plan_file" ] && { echo "no plan.json in $task_dir"; return 1; }

    local task
    task=$(python3 -c "import json;print(json.load(open('$plan_file'))['task'])")
    local chunks_count
    chunks_count=$(python3 -c "import json;print(len(json.load(open('$plan_file'))['chunks']))")

    echo -e "  ${BC}🥷 executing${X} ${BW}$chunks_count${X} chunks · model: ${BW}$MODEL${X}"
    echo ""

    local prev_summary=""
    for i in $(seq 0 $((chunks_count - 1))); do
        local chunk_file="$task_dir/chunk_$(printf '%02d' $((i + 1))).md"
        if [ -f "$chunk_file" ] && [ -s "$chunk_file" ]; then
            echo -e "  ${D}⚡ chunk $((i+1)) already done — skipping${X}"
            prev_summary+="Chunk $((i+1)): $(head -c 200 "$chunk_file")...\n"
            continue
        fi
        local heading target_words
        heading=$(python3 -c "import json;print(json.load(open('$plan_file'))['chunks'][$i].get('heading',''))")
        target_words=$(python3 -c "import json;print(json.load(open('$plan_file'))['chunks'][$i].get('target_words',2500))")

        echo -e "  ${BC}🥷 chunk $((i+1))/${chunks_count}:${X} ${BW}$heading${X} ${D}(~${target_words} words)${X}"
        local start=$(date +%s)
        local plan_json
        plan_json=$(cat "$plan_file")
        local output
        output=$(write_chunk "$task" "$plan_json" "$((i + 1))" "$heading" "$target_words" "$prev_summary")
        local elapsed=$(( $(date +%s) - start ))

        if [ -z "$output" ]; then
            echo -e "  ${BR}❌ chunk $((i+1)) failed — resume later with: ${BW}bash $0 resume $(basename "$task_dir")${X}"
            return 1
        fi

        echo "$output" > "$chunk_file"
        # Mark done in plan
        python3 -c "
import json
d = json.load(open('$plan_file'))
d['chunks'][$i]['done'] = True
json.dump(d, open('$plan_file','w'), indent=2)
"
        local chunk_words
        chunk_words=$(wc -w < "$chunk_file")
        echo -e "  ${BG}   ✓ ${chunk_words} words in ${elapsed}s${X} → $chunk_file"
        prev_summary+="Chunk $((i+1)) ($heading): first lines = $(head -c 150 "$chunk_file")...\n"
    done

    echo ""
    merge_chunks "$task_dir" "$task"
    echo ""
    echo -e "  ${BG}🥷 task complete!${X}"
    echo -e "  ${BW}Output:${X} $task_dir/final.md ($(wc -w < "$task_dir/final.md") words)"
    echo -e "  ${BW}Chunks:${X} $task_dir/chunk_*.md"
}

# ── CLI entry ────────────────────────────────────────────────
mode="${1:-}"

case "$mode" in
    list)
        list_tasks
        exit 0
        ;;
    resume)
        task_id="${2:-}"
        [ -z "$task_id" ] && { echo "usage: bash $0 resume <task_id | last | keyword>"; exit 1; }

        # Shortcut: 'last' = most recent task (by folder mtime)
        if [ "$task_id" = "last" ]; then
            task_id=$(ls -1t "$CHUNKS_ROOT/" 2>/dev/null | head -1)
            [ -z "$task_id" ] && { echo "no tasks found in $CHUNKS_ROOT"; exit 1; }
            echo "  → resuming last: $task_id"
        fi

        task_dir="$CHUNKS_ROOT/$task_id"

        # If not an exact match, try prefix / substring match — most-recent wins
        if [ ! -d "$task_dir" ]; then
            match=$(ls -1t "$CHUNKS_ROOT/" 2>/dev/null | grep -F "$task_id" | head -1)
            if [ -n "$match" ]; then
                task_id="$match"
                task_dir="$CHUNKS_ROOT/$task_id"
                echo "  → matched keyword: $task_id"
            fi
        fi

        [ ! -d "$task_dir" ] && { echo "no such task: $task_id"; list_tasks; exit 1; }
        run_task "$task_dir"
        ;;
    ""|"-h"|"--help")
        echo "usage:"
        echo "  bash $0 \"<big task>\"       # plan + run a new task"
        echo "  bash $0 resume <task_id>     # resume an interrupted task"
        echo "  bash $0 list                  # list in-progress tasks"
        exit 0
        ;;
    *)
        # New task
        task="$*"
        task_id="$(date +%Y%m%d_%H%M%S)_$(slug "$task")"
        task_dir="$CHUNKS_ROOT/$task_id"
        mkdir -p "$task_dir"
        echo ""
        echo -e "  ${BC}╔══════════════════════════════════════════════╗${X}"
        echo -e "  ${BC}║${X}  ${BW}🥷 CHUNKER — new task${X}                       ${BC}║${X}"
        echo -e "  ${BC}╚══════════════════════════════════════════════╝${X}"
        echo -e "  ${BW}Task:${X} $task"
        echo -e "  ${BW}Dir:${X}  $task_dir"
        echo -e "  ${BW}Model:${X} $MODEL"
        echo ""

        plan_json=$(plan_task "$task")
        if [ -z "$plan_json" ] || [ "$plan_json" = "[]" ]; then
            echo -e "  ${BR}❌ planner returned nothing. Is Ollama up? Is '$MODEL' pulled?${X}"
            exit 1
        fi

        # Save plan
        python3 -c "
import json, sys
chunks = json.loads('''$plan_json''')
# normalize — add 'done' flag to each chunk
for c in chunks:
    c.setdefault('done', False)
    c.setdefault('target_words', 2500)
plan = {'task': '''$task''', 'chunks': chunks, 'model': '$MODEL'}
json.dump(plan, open('$task_dir/plan.json', 'w'), indent=2)
"
        chunks_count=$(python3 -c "import json;print(len(json.load(open('$task_dir/plan.json'))['chunks']))")
        echo -e "  ${BG}✓ plan:${X} $chunks_count chunks"
        python3 -c "
import json
d = json.load(open('$task_dir/plan.json'))
for i, c in enumerate(d['chunks'], 1):
    print(f'    {i:2d}. {c[\"heading\"]} (~{c.get(\"target_words\", 2500)} words)')
"
        echo ""
        read -rp "  press Enter to start, or Ctrl-C to abort " _
        run_task "$task_dir"
        ;;
esac
