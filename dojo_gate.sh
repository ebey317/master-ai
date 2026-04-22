#!/bin/bash
# ============================================================
# DOJO GATE — entry ritual for Sensei
# Reads PROJECTS.md → shows project picker → pins active project + task
# Writes: ~/.master_ai_active_project  (project name)
#         ~/.master_ai_active_task     (current task text)
# Testing mode (default): gate is SOFT — Elijah can skip.
# Sealed mode (~/.dojo_gate_sealed exists): gate is HARD — no project+task, no entry.
# Triggered by master.sh menu option 4. Chains into launch_master_ai.sh.
# ============================================================

source ~/scripts/brand.sh 2>/dev/null || true

PROJECTS_FILE="$HOME/scripts/PROJECTS.md"
ACTIVE_PROJECT_FILE="$HOME/.master_ai_active_project"
ACTIVE_TASK_FILE="$HOME/.master_ai_active_task"
ACTIVE_MODEL_FILE="$HOME/.master_ai_active_model"
SEALED_FLAG="$HOME/.dojo_gate_sealed"

# Color fallbacks if brand.sh didn't load
: "${BC:=$(tput bold 2>/dev/null; tput setaf 4 2>/dev/null)}"
: "${BG:=$(tput bold 2>/dev/null; tput setaf 2 2>/dev/null)}"
: "${BW:=$(tput bold 2>/dev/null; tput setaf 0 2>/dev/null)}"
: "${BR:=$(tput bold 2>/dev/null; tput setaf 1 2>/dev/null)}"
: "${BY:=$(tput bold 2>/dev/null; tput setaf 3 2>/dev/null)}"
: "${X:=$(tput sgr0 2>/dev/null)}"

is_sealed() { [ -f "$SEALED_FLAG" ]; }

# ── Creator bypass ─────────────────────────────────────────────
# Elijah built Master AI. He doesn't take a test to enter his own dojo.
# When ~/.master_ai_creator exists, the hard SEALED mode softens back to
# "you can skip" for him — the gate still opens, the creator still picks
# a project if they want, but they are never blocked.
# pack_for_sale.sh does NOT copy this file (it lives in $HOME, not ~/scripts),
# so a buyer machine never has it — the hard gate stays hard for buyers.
CREATOR_FILE="$HOME/.master_ai_creator"
is_creator() { [ -f "$CREATOR_FILE" ]; }

# True only when the gate is sealed AND the user is NOT the creator.
# This is the check main() uses to decide "hard-block or allow skip."
is_sealed_for_user() { is_sealed && ! is_creator; }

# ── "Once you're in, you're in" — entrance flag ────────────────
# Elijah's rule (2026-04-19): *"Once you pass the test one time to get
# into Sensei, that is unlocked for you — you do have your projects
# and task pinned above it. Once you're in, you're in."*
#
# First pass through the dojo writes DOJO_ENTERED_FLAG with a timestamp.
# On subsequent entries, the gate shows the user's last-pinned project +
# task ABOVE the banner and offers a welcome-back shortcut: continue
# with what's pinned, pick something new, or skip.
# Creators always have the flag (implicit — they built it).
DOJO_ENTERED_FLAG="$HOME/.dojo_entered"
has_entered_before() { [ -f "$DOJO_ENTERED_FLAG" ] || is_creator; }
mark_entered() { [ -f "$DOJO_ENTERED_FLAG" ] || date -Iseconds > "$DOJO_ENTERED_FLAG"; }

# ── Parse project H3 headings from the "## Project Boards" section ──
list_projects() {
    awk '
        /^## Project Boards/ { in_boards = 1; next }
        /^## / && in_boards  { in_boards = 0 }
        /^### / && in_boards { sub(/^### /, ""); print }
    ' "$PROJECTS_FILE"
}

# ── Parse unchecked tasks for a given project ──
#    Usage: unchecked_tasks "Sensei"
unchecked_tasks() {
    local proj="$1"
    awk -v p="$proj" '
        $0 == "### " p { in_proj = 1; next }
        /^### /        { in_proj = 0 }
        /^## /         { in_proj = 0 }
        in_proj && /^[[:space:]]*- \[ \]/ {
            sub(/^[[:space:]]*- \[ \][[:space:]]*/, "")
            print
        }
    ' "$PROJECTS_FILE"
}

# ── Parse the Goal line for a project (used when asking AI for tasks) ──
project_goal() {
    local proj="$1"
    awk -v p="$proj" '
        $0 == "### " p { in_proj = 1; next }
        /^### /        { in_proj = 0 }
        in_proj && /^- \*\*Goal:\*\*/ {
            sub(/^- \*\*Goal:\*\* */, "")
            print
            exit
        }
    ' "$PROJECTS_FILE"
}

# ── Parse the Model line (e.g. "master-ai", "qwen2.5-coder:7b", "auto") ──
#    Missing Model: line → "" → gate leaves model unpinned (auto-router stays active)
project_model() {
    local proj="$1"
    awk -v p="$proj" '
        $0 == "### " p { in_proj = 1; next }
        /^### /        { in_proj = 0 }
        in_proj && /^- \*\*Model:\*\*/ {
            sub(/^- \*\*Model:\*\* */, "")
            sub(/[[:space:]]+←.*$/, "")
            sub(/[[:space:]]+$/, "")
            print
            exit
        }
    ' "$PROJECTS_FILE"
}

# ── Parse the Type line (master-bound | training) ──
project_type() {
    local proj="$1"
    awk -v p="$proj" '
        $0 == "### " p { in_proj = 1; next }
        /^### /        { in_proj = 0 }
        in_proj && /^- \*\*Type:\*\*/ {
            # Take first word after "**Type:**" and before any comment arrow
            sub(/^- \*\*Type:\*\* */, "")
            sub(/[[:space:]]+←.*$/, "")
            sub(/[[:space:]]+$/, "")
            print
            exit
        }
    ' "$PROJECTS_FILE"
}

# ── Banner ──
gate_banner() {
    clear
    echo ""
    echo "   ${BC}╔════════════════════════════════════╗${X}"
    echo "   ${BC}║${X}  ${BW}🥷  DOJO GATE  🥷${X}                  ${BC}║${X}"
    echo "   ${BC}║${X}  ${BW}turn in your project to enter${X}     ${BC}║${X}"
    echo "   ${BC}╚════════════════════════════════════╝${X}"
    if is_sealed; then
        if is_creator; then
            echo "   ${BG}[CREATOR PASS — gate honors you, you may skip]${X}"
        else
            echo "   ${BR}[SEALED MODE — hard gate active]${X}"
        fi
    else
        echo "   ${BY}[testing mode — gate is soft; you can skip]${X}"
    fi
    echo ""
}

# ── Project picker ──
pick_project() {
    gate_banner
    local -a projects
    mapfile -t projects < <(list_projects)

    if [ ${#projects[@]} -eq 0 ]; then
        echo "   ${BR}No projects found in PROJECTS.md.${X}"
        if is_sealed_for_user; then
            echo "   ${BR}Gate is sealed — add a project via menu option 9 first.${X}"
            read -rp "   press Enter to return..."
            return 1
        fi
        echo "   ${BY}Entering Sensei without a project (testing mode).${X}"
        : > "$ACTIVE_PROJECT_FILE"
        : > "$ACTIVE_TASK_FILE"
        return 0
    fi

    echo "   ${BW}Projects:${X}"
    local i=1
    for p in "${projects[@]}"; do
        local unchecked_count ptype type_tag
        unchecked_count=$(unchecked_tasks "$p" | wc -l)
        ptype=$(project_type "$p")
        type_tag=""
        [ "$ptype" = "training" ] && type_tag=" ${BY}[training]${X}"
        local marker="${BG}● ${unchecked_count} open${X}"
        [ "$unchecked_count" -eq 0 ] && marker="${BY}● empty${X}"
        echo "   ${BC}$i)${X} ${BW}$p${X}$type_tag   $marker"
        i=$((i + 1))
    done
    echo ""
    if ! is_sealed_for_user; then
        echo "   ${BY}s)${X} skip gate (enter Sensei unrestricted)"
    fi
    echo "   ${BC}x)${X} exit back to menu"
    echo ""

    while true; do
        read -rp "   ${BW}pick:${X} " choice
        case "$choice" in
            x|X|q|Q) return 1 ;;
            s|S)
                if is_sealed_for_user; then
                    echo "   ${BR}gate is sealed — cannot skip${X}"
                    continue
                fi
                : > "$ACTIVE_PROJECT_FILE"
                : > "$ACTIVE_TASK_FILE"
                if is_creator && is_sealed; then
                    echo "   ${BG}creator pass — entering Sensei unrestricted${X}"
                else
                    echo "   ${BY}skipped — entering Sensei unrestricted${X}"
                fi
                sleep 1
                return 0
                ;;
            ''|*[!0-9]*) echo "   ${BR}enter a number, s, or x${X}" ;;
            *)
                if [ "$choice" -ge 1 ] && [ "$choice" -le "${#projects[@]}" ]; then
                    SELECTED_PROJECT="${projects[$((choice - 1))]}"
                    return 0
                fi
                echo "   ${BR}out of range${X}"
                ;;
        esac
    done
}

# ── Task picker for a selected project ──
pick_task() {
    local proj="$1"
    local -a tasks
    mapfile -t tasks < <(unchecked_tasks "$proj")

    echo ""
    echo "   ${BW}Project:${X} ${BC}$proj${X}"
    local goal
    goal=$(project_goal "$proj")
    [ -n "$goal" ] && echo "   ${BW}Goal:${X} $goal"
    echo ""

    if [ ${#tasks[@]} -eq 0 ]; then
        echo "   ${BY}no open tasks on this project.${X}"
        echo ""
        if is_sealed_for_user; then
            echo "   ${BR}sealed gate requires a task. generate one now? [Y/n]${X}"
        else
            echo "   ${BW}options:${X}"
            echo "   ${BC}g)${X} generate tasks with AI (reads project goal + recent sessions)"
            echo "   ${BC}m)${X} enter manually"
            echo "   ${BC}e)${X} enter Sensei without a task (testing)"
            echo "   ${BC}x)${X} back to project picker"
        fi
        while true; do
            read -rp "   ${BW}pick:${X} " c
            case "$c" in
                g|G|y|Y|'')
                    generate_tasks_for "$proj" && return 0 || return 1
                    ;;
                m|M)
                    read -rp "   ${BW}task:${X} " manual_task
                    if [ -n "$manual_task" ]; then
                        append_task "$proj" "$manual_task"
                        SELECTED_TASK="$manual_task"
                        return 0
                    fi
                    ;;
                e|E)
                    if is_sealed_for_user; then
                        echo "   ${BR}sealed — task required${X}"
                        continue
                    fi
                    SELECTED_TASK=""
                    return 0
                    ;;
                x|X|n|N)
                    return 1
                    ;;
                *) echo "   ${BR}?${X}" ;;
            esac
        done
    fi

    echo "   ${BW}Open tasks:${X}"
    local i=1
    for t in "${tasks[@]}"; do
        echo "   ${BC}$i)${X} $t"
        i=$((i + 1))
    done
    echo ""
    echo "   ${BC}a)${X} add a new task"
    echo "   ${BC}x)${X} back"
    echo ""

    while true; do
        read -rp "   ${BW}pick task:${X} " c
        case "$c" in
            x|X) return 1 ;;
            a|A)
                read -rp "   ${BW}new task:${X} " new_task
                if [ -n "$new_task" ]; then
                    append_task "$proj" "$new_task"
                    SELECTED_TASK="$new_task"
                    return 0
                fi
                ;;
            ''|*[!0-9]*) echo "   ${BR}?${X}" ;;
            *)
                if [ "$c" -ge 1 ] && [ "$c" -le "${#tasks[@]}" ]; then
                    SELECTED_TASK="${tasks[$((c - 1))]}"
                    return 0
                fi
                echo "   ${BR}out of range${X}"
                ;;
        esac
    done
}

# ── Append a task as unchecked under a project's Tasks: block ──
append_task() {
    local proj="$1"
    local task="$2"
    python3 - "$PROJECTS_FILE" "$proj" "$task" <<'PY'
import sys, re
path, proj, task = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(path).read().splitlines(True)
out = []
i = 0
in_proj = False
tasks_block = False
inserted = False
while i < len(src):
    line = src[i]
    if line.strip() == f"### {proj}":
        in_proj = True
        out.append(line)
        i += 1
        continue
    if in_proj and (line.startswith("### ") or line.startswith("## ")):
        if not inserted:
            # project had no Tasks: block — add one
            out.append("- **Tasks:**\n")
            out.append(f"  - [ ] {task}\n")
            inserted = True
        in_proj = False
    if in_proj and line.strip().startswith("- **Tasks:**"):
        out.append(line)
        i += 1
        # Skip any existing task items then insert
        while i < len(src) and re.match(r"\s*- \[[ x]\]", src[i]):
            out.append(src[i])
            i += 1
        out.append(f"  - [ ] {task}\n")
        inserted = True
        continue
    out.append(line)
    i += 1
if in_proj and not inserted:
    out.append("- **Tasks:**\n")
    out.append(f"  - [ ] {task}\n")
open(path, "w").writelines(out)
PY
}

# ── Ask local Ollama for 3-5 tasks given project goal + recent session tail ──
generate_tasks_for() {
    local proj="$1"
    local goal
    goal=$(project_goal "$proj")
    [ -z "$goal" ] && goal="(no goal set)"

    local recent=""
    local latest_session
    latest_session=$(ls -t "$HOME/scripts/sessions/"*.log 2>/dev/null | head -1)
    if [ -n "$latest_session" ] && [ -r "$latest_session" ]; then
        recent=$(tail -c 4000 "$latest_session" 2>/dev/null)
    fi

    echo ""
    echo "   ${BW}🥷 I've read your project. Thinking of starter tasks...${X}"

    local prompt="You are Sensei. A project needs a starter task list.
Project: $proj
Goal: $goal

Recent session context (may be empty):
$recent

Output exactly 3-5 short concrete tasks, one per line, each starting with '- [ ] '. No preamble, no numbering, no extra prose."

    local resp
    resp=$(curl -s --max-time 90 http://localhost:11434/api/generate \
        -d "$(python3 -c 'import json,sys; print(json.dumps({"model":"master-ai","prompt":sys.argv[1],"stream":False,"keep_alive":"30m"}))' "$prompt")" \
        | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("response",""))' 2>/dev/null)

    if [ -z "$resp" ]; then
        echo "   ${BR}Ollama did not respond — enter a task manually.${X}"
        read -rp "   ${BW}task:${X} " manual_task
        if [ -n "$manual_task" ]; then
            append_task "$proj" "$manual_task"
            SELECTED_TASK="$manual_task"
            return 0
        fi
        return 1
    fi

    # Filter to only '- [ ] ...' lines
    local -a generated
    mapfile -t generated < <(echo "$resp" | grep -E '^\s*- \[ \] ' | sed -E 's/^\s*- \[ \]\s*//')
    if [ ${#generated[@]} -eq 0 ]; then
        echo "   ${BY}AI reply didn't match checkbox format. Raw output:${X}"
        echo "$resp" | sed 's/^/     /'
        read -rp "   ${BW}enter one task manually:${X} " manual_task
        if [ -n "$manual_task" ]; then
            append_task "$proj" "$manual_task"
            SELECTED_TASK="$manual_task"
            return 0
        fi
        return 1
    fi

    echo ""
    echo "   ${BW}Proposed tasks:${X}"
    local i=1
    for t in "${generated[@]}"; do
        echo "   ${BC}$i)${X} $t"
        i=$((i + 1))
    done
    echo ""
    read -rp "   ${BW}accept all? [Y/n]${X} " accept
    if [[ "$accept" =~ ^[nN] ]]; then
        echo "   ${BY}discarded.${X}"
        return 1
    fi

    for t in "${generated[@]}"; do
        append_task "$proj" "$t"
    done
    SELECTED_TASK="${generated[0]}"
    echo ""
    echo "   ${BG}✅ tasks added. starting on:${X} ${BW}$SELECTED_TASK${X}"
    sleep 1
    return 0
}

# ── Welcome-back shortcut (returning users only) ────────────────
# Shown ABOVE the regular gate banner when the user has entered before
# AND has a pinned project + task. They see what they were working on
# and can pick up right where they left off.
# Returns 0 when the shortcut fully handled entry (skip pick_project/pick_task).
# Returns 1 when the user chose "new pick" or no pinned state exists — fall
# through to normal gate flow.
welcome_back() {
    has_entered_before || return 1

    local pinned_proj="" pinned_task=""
    [ -f "$ACTIVE_PROJECT_FILE" ] && pinned_proj=$(cat "$ACTIVE_PROJECT_FILE" 2>/dev/null | tr -d '\n')
    [ -f "$ACTIVE_TASK_FILE"    ] && pinned_task=$(cat "$ACTIVE_TASK_FILE"    2>/dev/null | tr -d '\n')

    # If there's nothing pinned yet, fall through to the normal flow.
    [ -z "$pinned_proj" ] && [ -z "$pinned_task" ] && return 1

    clear
    echo ""
    echo "   ${BC}╔════════════════════════════════════════╗${X}"
    echo "   ${BC}║${X}  ${BW}🥋  WELCOME BACK TO THE DOJO${X}            ${BC}║${X}"
    echo "   ${BC}║${X}  ${D}once you get a black belt,${X}                ${BC}║${X}"
    echo "   ${BC}║${X}  ${D}you're a black belt forever${X}               ${BC}║${X}"
    echo "   ${BC}╚════════════════════════════════════════╝${X}"
    echo ""
    echo "   ${BW}pinned above the gate:${X}"
    [ -n "$pinned_proj" ] && echo "     ${BC}project:${X} ${BW}$pinned_proj${X}"
    [ -n "$pinned_task" ] && echo "     ${BC}task:${X}    ${BW}$pinned_task${X}"
    echo ""
    echo "   ${BC}c)${X} continue where you left off"
    echo "   ${BC}n)${X} pick a new project + task"
    if ! is_sealed_for_user; then
        echo "   ${BC}s)${X} skip the gate, enter unrestricted"
    fi
    echo "   ${BC}x)${X} back to menu"
    echo ""

    while true; do
        read -rp "   ${BW}pick:${X} " c
        case "$c" in
            c|C|'')
                SELECTED_PROJECT="$pinned_proj"
                SELECTED_TASK="$pinned_task"
                return 0
                ;;
            n|N) return 1 ;;
            s|S)
                if is_sealed_for_user; then
                    echo "   ${BR}gate is sealed — cannot skip${X}"
                    continue
                fi
                : > "$ACTIVE_PROJECT_FILE"
                : > "$ACTIVE_TASK_FILE"
                SELECTED_PROJECT=""
                SELECTED_TASK=""
                return 0
                ;;
            x|X|q|Q) exit 0 ;;
            *) echo "   ${BR}enter c, n, s, or x${X}" ;;
        esac
    done
}

# ── Main gate flow ──
main() {
    [ ! -f "$PROJECTS_FILE" ] && {
        echo "${BR}PROJECTS.md not found at $PROJECTS_FILE${X}"
        exit 1
    }

    # Returning user? Offer the welcome-back shortcut before the full ritual.
    if welcome_back; then
        # welcome_back handled it — jump straight to state write.
        :
    else
        # Full turn-in ritual (first-time users or "pick new")
        while true; do
            pick_project || exit 0
            if [ -z "${SELECTED_PROJECT:-}" ]; then
                break
            fi
            pick_task "$SELECTED_PROJECT" || { unset SELECTED_PROJECT; continue; }
            break
        done
    fi

    # Write active state
    if [ -n "${SELECTED_PROJECT:-}" ]; then
        echo "$SELECTED_PROJECT" > "$ACTIVE_PROJECT_FILE"
    else
        : > "$ACTIVE_PROJECT_FILE"
    fi
    if [ -n "${SELECTED_TASK:-}" ]; then
        echo "$SELECTED_TASK" > "$ACTIVE_TASK_FILE"
    else
        : > "$ACTIVE_TASK_FILE"
    fi
    # Resolve project's preferred model.
    # Rules:
    #   - Missing **Model:** line  → "" → Sensei's auto-router stays on
    #   - "auto"                   → "" → auto-router
    #   - anything else            → pinned as-is (e.g. "qwen2.5-coder:7b")
    SELECTED_MODEL=""
    if [ -n "${SELECTED_PROJECT:-}" ]; then
        local _m
        _m=$(project_model "$SELECTED_PROJECT")
        if [ -n "$_m" ] && [ "$_m" != "auto" ]; then
            SELECTED_MODEL="$_m"
        fi
    fi
    if [ -n "$SELECTED_MODEL" ]; then
        echo "$SELECTED_MODEL" > "$ACTIVE_MODEL_FILE"
    else
        : > "$ACTIVE_MODEL_FILE"
    fi

    echo ""
    if [ -n "${SELECTED_PROJECT:-}" ]; then
        echo "   ${BG}🥷 project in:${X} ${BW}$SELECTED_PROJECT${X}"
        [ -n "${SELECTED_TASK:-}" ]  && echo "   ${BG}🥷 task pinned:${X}  ${BW}$SELECTED_TASK${X}"
        if [ -n "$SELECTED_MODEL" ]; then
            echo "   ${BG}🥷 model pinned:${X} ${BW}$SELECTED_MODEL${X}"
        else
            echo "   ${BG}🥷 model:${X}        ${BW}auto-router${X}"
        fi
    else
        echo "   ${BY}🥷 entering dojo unrestricted (testing)${X}"
    fi
    echo "   ${BC}launching Sensei...${X}"
    # Mark that this dojo has been entered at least once. On next visit,
    # welcome_back() kicks in and skips the full turn-in ritual.
    mark_entered
    sleep 1

    exec bash "$HOME/scripts/launch_master_ai.sh"
}

# Only run main when executed directly. When sourced (e.g. by dojo_gate_test.sh)
# the functions load but the gate doesn't open — lets tests exercise parsers.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
