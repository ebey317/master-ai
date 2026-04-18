#!/bin/bash
# ============================================================
# SENSEI — AI Agent with Memory + 4-Option Confirm
# (File name stays pc_control.sh for backward compat with master.sh)
# Run: bash ~/scripts/pc_control.sh
# ============================================================

source ~/scripts/brand.sh

MEMORY_FILE="$HOME/.master_ai_memory"
APPROVED_FILE="$HOME/.master_ai_approved"
KEYS_FILE="$HOME/.master_ai_keys"
OLLAMA_URL="http://localhost:11434"
MODEL="master-ai:latest"
CODER_MODEL="qwen2.5-coder:7b"
LOG="$HOME/scripts/master.log"
HIST_FILE="/tmp/pc_control_hist.json"
CACHE_FILE="$HOME/.master_ai_cache.json"
TTS_OK=0
PLAN_CHOICE=""
ACTIVE_PROJECT=""
CLOUD_ENABLED=0
WEB_ENABLED=0
MODE="safe"
PENDING_PLAN_TEXT=""
PENDING_PLAN_REQUEST=""
TUTORIAL_FILE="$HOME/.master_ai_tutorial_done"
PERMS_FILE="$HOME/.master_ai_perms_granted"
HINTS_FILE="$HOME/.master_ai_hints_off"
HINTS=1
[ -f "$HINTS_FILE" ] && HINTS=0

# ── ACCESSIBILITY SETTINGS ────────────────────────────────────
SETTINGS_FILE="$HOME/.master_ai_settings"
NO_MOUSE=0
PHONE_MODE=0
if [ -f "$SETTINGS_FILE" ]; then
    source "$SETTINGS_FILE" 2>/dev/null
fi

touch "$MEMORY_FILE" "$APPROVED_FILE" 2>/dev/null
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

# ── ARROW-KEY MENU NAVIGATOR ──────────────────────────────────
# Usage: nav_menu "Option label" "Option label" ...
# Result stored in NAV_RESULT (1-based number)
NAV_RESULT=1
nav_menu() {
    local options=("$@")
    local count=${#options[@]}
    local selected=0
    local key k2 k3

    _nav_draw() {
        local i
        for i in "${!options[@]}"; do
            if [ "$i" -eq "$selected" ]; then
                echo -e "  ${Y}┃${W} $((i+1))  ${W}${options[$i]} ${Y}◀${X}"
            else
                echo -e "  ${BC}  $((i+1))  ${W}${options[$i]}${X}"
            fi
        done
        echo -e "  ${BC}  ↑↓ move · Tab next · Enter select · 1-$count direct${X}"
    }

    printf '\033[?25l'
    _nav_draw

    local draw_lines=$(( count + 1 ))

    while true; do
        IFS= read -rsn1 key 2>/dev/null
        case "$key" in
            $'\x1b')
                IFS= read -rsn1 -t 0.05 k2 2>/dev/null
                IFS= read -rsn1 -t 0.05 k3 2>/dev/null
                case "${k2}${k3}" in
                    '[A'|'OA') [ "$selected" -gt 0 ] && ((selected--)) ;;
                    '[B'|'OB') [ "$selected" -lt $((count-1)) ] && ((selected++)) ;;
                esac
                printf '\033[%dA' "$draw_lines"
                _nav_draw
                ;;
            $'\t')
                selected=$(( (selected + 1) % count ))
                printf '\033[%dA' "$draw_lines"
                _nav_draw
                ;;
            '')
                break
                ;;
            [1-9])
                local num=$(( key - 1 ))
                if [ "$num" -ge 0 ] && [ "$num" -lt "$count" ]; then
                    selected="$num"
                    printf '\033[%dA' "$draw_lines"
                    _nav_draw
                    break
                fi
                ;;
        esac
    done

    printf '\033[?25h'
    NAV_RESULT=$(( selected + 1 ))
}

# ── SMART PROMPT: nav if NO_MOUSE, else read ──────────────────
prompt_choice() {
    if [ "$NO_MOUSE" -eq 1 ]; then
        nav_menu "$@"
        CHOICE="$NAV_RESULT"
    else
        echo -ne "  ${BC}[MAI]${X} ${Y}▸ ${X}"
        read -r CHOICE
    fi
}

# ── HINT SYSTEM ───────────────────────────────────────────────
show_hint() {
    [ "$HINTS" -eq 0 ] && return
    local title="$1"
    local body="$2"
    echo ""
    echo -e "  ${BC}◈ ${Y}${title}${X}"
    echo -e "  ${BC}─────────────────────────────────────────────────────────${X}"
    while IFS= read -r line; do
        [ -n "$line" ] && echo -e "  ${W}▸ ${line}${X}"
    done <<< "$body"
    echo -e "  ${BC}─────────────────────────────────────────────────────────${X}"
    echo -e "  ${W}type ${Y}hints off${W} to disable tips${X}"
    echo ""
}

# ── TUTORIAL ──────────────────────────────────────────────────
run_tutorial() {
    local -a TITLES=(
        "Welcome to Master AI — PC Control"
        "How to Talk to It"
        "What Happens When AI Wants to Act"
        "The 4-Option Confirm"
        "Memory — Teaching Your AI"
        "Modes — Plan, Auto, and Safe"
        "The Status Bar"
        "Quick Tips"
        "You're Ready"
    )
    local -a BODIES=(
"Master AI is your personal AI agent running
RIGHT HERE on your own computer.
No cloud required. No subscription. Your data stays local.

You talk to it in plain English.
It thinks. It acts. It remembers.
This tutorial will show you exactly how."

"Just type what you want — like texting a smart assistant.

Examples:
  → 'check if ollama is running'
  → 'create a new folder called Projects'
  → 'what files are in my Downloads folder?'
  → 'search latest news on Linux AI tools'

You do NOT need to know bash or code.
The AI translates your words into actions."

"When the AI decides it needs to DO something on your PC,
it will propose a command.

You will see a box like this:
  ╔══════════════════════════╗
  ║ AI wants to run:         ║
  ║  mkdir ~/Projects        ║
  ╚══════════════════════════╝

Nothing runs until YOU decide. You are always in control."

"Every time AI wants to run a command, you get 4 choices:

  1) Yes       — run it this one time
  2) Always    — run it forever without asking again
  3) No        — skip it, don't run
  4) Edit      — you change the command before it runs

Start with Yes (1). Use Always (2) once you trust a command.
You can clear all Always approvals any time with: clear approved"

"The AI can remember facts between sessions.

  remember: I use Python 3.11
  remember: my project folder is ~/Projects/myapp

To see what it remembers:  memory
To make it forget:         forget: python

Memory is stored in: ~/.master_ai_memory
Everything in memory gets included in every AI response."

"There are 3 modes. Switch any time by typing:

  mode safe  (default)
    Every command asks for permission. Best when learning.

  mode plan
    AI thinks first, shows you a plan.
    Nothing runs until you type: go
    Type cancel to throw the plan away.

  mode auto
    Commands run immediately without asking.
    Use when you trust the task. Switch back with: mode safe"

"The green bar at the top shows your system status:

  MODE:SAFE  — which mode you're in (SAFE / PLAN / AUTO)
  MEM:3      — how many facts AI remembers
  APPROVED:5 — how many commands auto-run without asking
  TTS:ON     — voice output is active
  LOCAL+CLOUD — AI can use both local Ollama and cloud models
  WEB:ON     — web search is available
  PRJ:myapp  — you have an active project set"

"Useful commands to know:

  search <question>    — search the web directly
  project <path>       — set your active codebase folder
  cache                — show how many answers are cached
  clear cache          — clear cached answers
  clear history        — start a fresh conversation
  hints off            — turn off these tip boxes
  hints on             — turn them back on
  tutorial             — replay this walkthrough any time
  help                 — quick command reference card
  ! <question>         — force a fresh answer (skip cache)
  x                    — exit"

"You have completed the Master AI tutorial.

Tips will still appear as you use new features.
They explain what's happening in real time.

To turn tips off:   hints off
To turn tips on:    hints on
To replay this:     tutorial

The more you use it, the smarter it gets about your setup.
Start by typing anything — just try it."
    )

    local total=${#TITLES[@]}
    local step=0

    while [ "$step" -lt "$total" ]; do
        clear
        banner_master_ai
        echo ""
        echo -e "${W}  ────────────────────────────────────────────────────────────${X}"
        echo -e "  ${C}Tutorial  —  Step $(( step + 1 )) of ${total}${X}"
        echo ""
        echo -e "  ${W}${TITLES[$step]}${X}"
        echo ""
        while IFS= read -r line; do
            echo -e "  ${W}${line}${X}"
        done <<< "${BODIES[$step]}"
        echo ""
        echo -e "${W}  ────────────────────────────────────────────────────────────${X}"
        echo ""

        if [ "$step" -eq $(( total - 1 )) ]; then
            echo -ne "  \e[5m${G}Press ENTER to finish tutorial...${X}\e[0m"
            read -r
            break
        else
            echo -e "  ${Y}n)${W} Next     ${W}— continue${X}"
            echo -e "  ${Y}b)${W} Back     ${W}— previous step${X}"
            echo -e "  ${Y}s)${W} Skip     ${W}— exit tutorial now${X}"
            echo ""
            echo -ne "  \e[5m${C}Choose (n/b/s): ${X}\e[0m"
            read -r NAV
            case "$NAV" in
                b|B) [ "$step" -gt 0 ] && (( step-- )) ;;
                s|S) break ;;
                *)   (( step++ )) ;;
            esac
        fi
    done

    touch "$TUTORIAL_FILE"
    clear
    banner_master_ai
    echo ""
    echo -e "  ${G}✅ Tutorial complete. You're ready to go.${X}"
    echo -e "  ${W}Type ${W}tutorial${W} any time to replay it.${X}"
    echo ""
    sleep 1
}

# ── QUICK HELP CARD ───────────────────────────────────────────
show_help() {
    clear
    banner_master_ai
    echo ""
    echo -e "${W}  ╔══════════════════════════════════════════════════════════════╗${X}"
    echo -e "${W}  ║${X}  ${C}MASTER AI — Quick Reference${X}"
    echo -e "${W}  ╠══════════════════════════════════════════════════════════════╣${X}"
    echo -e "${W}  ║${X}  ${Y}TALKING TO IT${X}"
    echo -e "${W}  ║${X}  ${W}Just type in plain English.${W} No commands needed.${X}"
    echo -e "${W}  ║${X}"
    echo -e "${W}  ║${X}  ${Y}MODES${X}"
    echo -e "${W}  ║${X}  ${W}mode safe${W}    ask before every command (default)${X}"
    echo -e "${W}  ║${X}  ${W}mode plan${W}    AI plans first, you approve with ${W}go${X}"
    echo -e "${W}  ║${X}  ${W}mode auto${W}    commands run without asking${X}"
    echo -e "${W}  ║${X}"
    echo -e "${W}  ║${X}  ${Y}MEMORY${X}"
    echo -e "${W}  ║${X}  ${W}remember: <fact>${W}   teach the AI something${X}"
    echo -e "${W}  ║${X}  ${W}forget: <word>${W}     remove facts matching a word${X}"
    echo -e "${W}  ║${X}  ${W}memory${W}             show all stored facts${X}"
    echo -e "${W}  ║${X}"
    echo -e "${W}  ║${X}  ${Y}COMMANDS${X}"
    echo -e "${W}  ║${X}  ${W}search <q>${W}         web search${X}"
    echo -e "${W}  ║${X}  ${W}project <path>${W}     set active codebase folder${X}"
    echo -e "${W}  ║${X}  ${W}approved${W}           list auto-run commands${X}"
    echo -e "${W}  ║${X}  ${W}clear approved${W}     remove all auto-approvals${X}"
    echo -e "${W}  ║${X}  ${W}cache${W}              show cache stats${X}"
    echo -e "${W}  ║${X}  ${W}clear cache${W}        wipe cached answers${X}"
    echo -e "${W}  ║${X}  ${W}clear history${W}      fresh conversation${X}"
    echo -e "${W}  ║${X}  ${W}! <question>${W}       bypass cache, force fresh answer${X}"
    echo -e "${W}  ║${X}  ${W}hints on/off${W}       toggle learning tips${X}"
    echo -e "${W}  ║${X}  ${W}tutorial${W}           replay the full walkthrough${X}"
    echo -e "${W}  ║${X}  ${W}help${W}               this screen${X}"
    echo -e "${W}  ║${X}  ${W}x${W}                  exit${X}"
    echo -e "${W}  ╚══════════════════════════════════════════════════════════════╝${X}"
    echo ""
    echo -ne "${W}  Press ENTER to continue...${X}"
    read -r
}

permissions_wizard() {
    [ -f "$PERMS_FILE" ] && return
    clear
    banner_master_ai

    local -a NAMES=(
        "Shell Command Execution"
        "Network: Ollama API  (localhost:11434)"
        "Network: TTS Server  (localhost:5050)"
        "Audio Playback  (aplay)"
        "File: Memory Store  (~/.master_ai_memory)"
        "File: Approved Commands  (~/.master_ai_approved)"
        "File: Session Log  (~/scripts/master.log)"
        "Network: Cloud AI (Groq / OpenAI / OpenRouter)"
        "Web Search (DuckDuckGo)"
    )
    local -a WHYS=(
        "The AI translates your requests into bash commands and runs them on this machine."
        "Sends your prompts to the local Ollama model to generate AI responses."
        "Forwards AI replies to the TTS server so responses can be spoken aloud."
        "Plays the audio files produced by the TTS server through your speakers."
        "Reads and writes facts you teach the AI so it remembers them across sessions."
        "Saves commands you mark as always-approved so it never prompts for them again."
        "Records every command and AI response to a local file for your review."
        "Routes complex and web queries to cloud models when local AI is insufficient."
        "Searches the web and injects results into AI context for current information."
    )
    local -a REQUIRED=(1 1 0 0 1 1 1 0 0)

    local total=${#NAMES[@]}

    echo ""
    echo -e "${BC}  ┌─────────────────────────────────────────────────────────┐${X}"
    echo -e "${BC}  │${X}  ${BC}🔐  Permissions Walkthrough${X}"
    echo -e "${BC}  │${X}  ${BW}Review each permission before PC Control starts.${X}"
    echo -e "${BC}  └─────────────────────────────────────────────────────────┘${X}"
    echo ""
    sleep 1

    local grant_all=0
    local denied_required=0

    for (( i=0; i<total; i++ )); do
        local num=$(( i + 1 ))
        local req_label
        [[ "${REQUIRED[$i]}" -eq 1 ]] && req_label="${R}[required]${X}" || req_label="${BW}[optional]${X}"

        clear
        banner_master_ai
        echo ""
        echo -e "${BC}  ────────────────────────────────────────────────────────────${X}"
        echo -e "  ${BC}Permission ${num} of ${total}${X}   ${req_label}"
        echo ""
        echo -e "  ${BW}${NAMES[$i]}${X}"
        echo ""
        echo -e "  ${BC}Why:${X} ${Y}${WHYS[$i]}${X}"
        echo ""
        echo -e "${BC}  ────────────────────────────────────────────────────────────${X}"
        echo ""

        if [ "$grant_all" -eq 1 ]; then
            echo -e "  \e[5m${BG}✅ Granted (Yes to All)${X}\e[0m"
            echo ""
            sleep 0.5
            continue
        fi

        echo -e "  ${Y}1)${BW} Yes          ${BC}— grant this permission${X}"
        echo -e "  ${Y}2)${BW} Yes to All   ${BC}— grant this and all remaining${X}"
        echo -e "  ${Y}3)${BW} No           ${BC}— deny this permission${X}"
        echo ""
        echo -ne "  ${BC}[MAI]${X} ${Y}▸ ${X}"
        read -r PERM_CHOICE

        case "$PERM_CHOICE" in
            2)
                grant_all=1
                echo -e "\n  ${G}✅ Granted — all remaining permissions also granted.${X}"
                ;;
            3)
                if [[ "${REQUIRED[$i]}" -eq 1 ]]; then
                    echo -e "\n  ${R}⚠  This permission is required. PC Control may not work correctly.${X}"
                    (( denied_required++ ))
                else
                    echo -e "\n  ${Y}⏭  Skipped — optional feature will be disabled.${X}"
                fi
                ;;
            *)
                echo -e "\n  ${G}✅ Granted.${X}"
                ;;
        esac
        echo ""
        sleep 0.4
    done

    clear
    banner_master_ai
    echo ""
    echo -e "${BC}  ────────────────────────────────────────────────────────────${X}"
    echo -e "  ${BC}Permission Review Complete${X}"
    echo ""

    if [ "$denied_required" -gt 0 ]; then
        echo -e "  ${R}⚠  ${denied_required} required permission(s) denied.${X}"
        echo -e "  ${Y}  Some features may not function correctly.${X}"
        echo ""
        echo -ne "  ${Y}Continue anyway? (y/N): ${X}"
        read -r CONT
        if [[ "$CONT" != "y" && "$CONT" != "Y" ]]; then
            echo -e "${BW}  Exiting.${X}"
            exit 0
        fi
    else
        echo -e "  ${BG}✅ All permissions granted.${X}"
        touch "$PERMS_FILE"
        sleep 1
    fi
    echo ""
}

# ── STARTUP CHECK ─────────────────────────────────────────────
startup_check() {
    local errors=0

    echo ""
    echo -e "${W}  ┌─────────────────────────────────────────────┐${X}"
    echo -e "${W}  │${X}  ${C}⚙  System Check${X}"
    echo -e "${W}  └─────────────────────────────────────────────┘${X}"
    echo ""

    if curl -s --max-time 3 "$OLLAMA_URL/api/tags" &>/dev/null; then
        echo -e "  ${G}✅ Ollama       ${W}running at ${OLLAMA_URL}${X}"
    else
        echo -e "  ${R}❌ Ollama       ${W}not running${X}"
        echo -e "  ${Y}     → Starting Ollama in background...${X}"
        nohup ollama serve &>/dev/null &
        sleep 3
        if curl -s --max-time 3 "$OLLAMA_URL/api/tags" &>/dev/null; then
            echo -e "  ${G}✅ Ollama       ${W}started successfully${X}"
        else
            echo -e "  ${R}     ✗ Could not start Ollama.${X}"
            echo -e "  ${Y}     → Run manually: ${W}ollama serve${X}"
            (( errors++ ))
        fi
    fi

    local models
    models=$(curl -s --max-time 5 "$OLLAMA_URL/api/tags" 2>/dev/null)
    if echo "$models" | grep -q 'master-ai'; then
        echo -e "  ${G}✅ master-ai    ${W}model loaded${X}"
    else
        echo -e "  ${R}❌ master-ai    ${W}model not found${X}"
        echo -e "  ${Y}     → Create it: ${W}cd ~/scripts && ollama create master-ai -f Modelfile-master-ai${X}"
        (( errors++ ))
    fi

    if curl -s --max-time 2 "http://localhost:5050" &>/dev/null || \
       curl -s --max-time 2 "http://localhost:5050/tts" &>/dev/null 2>&1 | grep -qiv "refused"; then
        echo -e "  ${G}✅ TTS server   ${W}running on port 5050${X}"
        TTS_OK=1
    elif ss -tlnp 2>/dev/null | grep -q ':5050' || netstat -tlnp 2>/dev/null | grep -q ':5050'; then
        echo -e "  ${G}✅ TTS server   ${W}running on port 5050${X}"
        TTS_OK=1
    else
        echo -e "  ${Y}⚠  TTS server   ${W}not running (voice output disabled)${X}"
        echo -e "  ${W}     → Start it: ${W}python3 ~/scripts/tts_server.py &${X}"
    fi

    local mem_count app_count
    mem_count=$(wc -l < "$MEMORY_FILE" 2>/dev/null || echo 0)
    app_count=$(wc -l < "$APPROVED_FILE" 2>/dev/null || echo 0)
    echo -e "  ${G}✅ Memory       ${W}${mem_count} facts | ${app_count} auto-approved commands${X}"

    if python3 -c "import json; d=json.load(open('$KEYS_FILE')); assert d.get('anthropic') or d.get('gemini') or d.get('groq') or d.get('openai') or d.get('openrouter')" 2>/dev/null; then
        CLOUD_ENABLED=1
        echo -e "  ${G}✅ Cloud AI     ${W}keys loaded (Groq / OpenAI / OpenRouter)${X}"
    else
        echo -e "  ${Y}⚠  Cloud AI     ${W}no keys found — local Ollama only${X}"
    fi

    if python3 -c "from duckduckgo_search import DDGS" 2>/dev/null; then
        WEB_ENABLED=1
        echo -e "  ${G}✅ Web search   ${W}duckduckgo_search available${X}"
    else
        echo -e "  ${Y}⚠  Web search   ${W}pip install duckduckgo-search to enable${X}"
    fi

    echo ""

    if [ "$errors" -gt 0 ]; then
        echo -e "  ${R}⚠  Fix the issues above before using PC Control.${X}"
        echo -ne "  ${Y}  Continue anyway? (y/N): ${X}"
        read -r CONT
        if [[ "$CONT" != "y" && "$CONT" != "Y" ]]; then
            echo -e "${W}  Exiting.${X}"
            exit 0
        fi
    else
        echo -e "  ${G}  All systems ready. Entering PC Control...${X}"
        sleep 1
    fi
    echo ""
}

# ── SAFETY BLOCK ─────────────────────────────────────────────
is_blocked() {
    local cmd="$1"
    local blocked=("rm -rf /" "rm -rf ~" "rm -rf \$HOME" "mkfs" "dd if=" ":(){:|:&};:")
    for b in "${blocked[@]}"; do
        if [[ "$cmd" == *"$b"* ]]; then
            return 0
        fi
    done
    return 1
}

# ── TTS ──────────────────────────────────────────────────────
speak() {
    local text="$1"
    curl -s -X POST "http://localhost:5050/tts" \
        -H "Content-Type: application/json" \
        -d "{\"text\": \"$text\"}" \
        -o /tmp/tts_out.wav 2>/dev/null && \
    aplay /tmp/tts_out.wav 2>/dev/null &
}

# ── WEB SEARCH ───────────────────────────────────────────────
web_search() {
    local query="$1"
    [ "$WEB_ENABLED" -eq 0 ] && return 1
    echo -e "${W}  🌐 Searching: ${query}${X}"
    python3 -c "
from duckduckgo_search import DDGS
import sys
try:
    with DDGS() as d:
        results = list(d.text(sys.argv[1], max_results=4))
    for r in results:
        print(f\"• {r.get('title','')}: {r.get('body','')[:200]}\")
except Exception as e:
    print(f'Search error: {e}', file=sys.stderr)
    sys.exit(1)
" "$query" 2>/dev/null
}

# ── GIT CONTEXT ──────────────────────────────────────────────
git_context() {
    local dir="${ACTIVE_PROJECT:-$PWD}"
    git -C "$dir" rev-parse --git-dir &>/dev/null 2>&1 || return
    local branch status
    branch=$(git -C "$dir" branch --show-current 2>/dev/null)
    status=$(git -C "$dir" status --short 2>/dev/null | head -10)
    echo "Git repo: $dir | Branch: $branch"
    [ -n "$status" ] && echo "Modified files:" && echo "$status"
}

# ── CLOUD AI ─────────────────────────────────────────────────
ask_ai_cloud() {
    local messages_json="$1"
    [ "$CLOUD_ENABLED" -eq 0 ] && return 1
    python3 -c "
import json, sys, urllib.request, datetime, os

KEYS_FILE = '$KEYS_FILE'
try:
    keys = json.load(open(KEYS_FILE))
except Exception:
    sys.exit(1)
messages = json.loads(sys.argv[1])

def accumulate_tokens(service, total):
    try:
        with open(KEYS_FILE) as f: kd = json.load(f)
    except: kd = {}
    today = datetime.date.today().isoformat()
    if kd.get(f'{service}_tokens_date') != today:
        kd[f'{service}_tokens_today'] = 0
        kd[f'{service}_tokens_date'] = today
    kd[f'{service}_tokens_today'] = kd.get(f'{service}_tokens_today', 0) + total
    with open(KEYS_FILE, 'w') as f: json.dump(kd, f, indent=2)
    os.chmod(KEYS_FILE, 0o600)

def try_groq(msgs):
    key = keys.get('groq','')
    if not key: return None
    payload = json.dumps({'model':'llama-3.3-70b-versatile','messages':msgs,'max_tokens':1024,'stream':False}).encode()
    req = urllib.request.Request('https://api.groq.com/openai/v1/chat/completions', data=payload,
        headers={'Content-Type':'application/json','Authorization':f'Bearer {key}','User-Agent':'python-requests/2.31.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            tokens = data.get('usage',{}).get('total_tokens', 0)
            if tokens: accumulate_tokens('groq', tokens)
            return data['choices'][0]['message']['content']
    except: return None

def try_deepseek(msgs):
    key = keys.get('deepseek','')
    if not key: return None
    payload = json.dumps({'model':'deepseek-reasoner','messages':msgs,'max_tokens':1024,'stream':False}).encode()
    req = urllib.request.Request('https://api.deepseek.com/v1/chat/completions', data=payload,
        headers={'Content-Type':'application/json','Authorization':f'Bearer {key}'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
            tokens = data.get('usage',{}).get('total_tokens', 0)
            if tokens: accumulate_tokens('deepseek', tokens)
            return data['choices'][0]['message']['content']
    except: return None

def try_openai(msgs):
    key = keys.get('openai','')
    if not key: return None
    try:
        from openai import OpenAI
        r = OpenAI(api_key=key).chat.completions.create(model='gpt-4o',messages=msgs,max_tokens=1024)
        tokens = getattr(r.usage, 'total_tokens', 0) or 0
        if tokens: accumulate_tokens('openai', tokens)
        return r.choices[0].message.content
    except: return None

def try_gemini(msgs):
    key = keys.get('gemini','')
    if not key: return None
    text = '\n'.join(m['content'] for m in msgs if m['role'] != 'system')
    payload = json.dumps({'contents':[{'parts':[{'text':text}]}]}).encode()
    url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}'
    req = urllib.request.Request(url, data=payload, headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())['candidates'][0]['content']['parts'][0]['text']
    except: return None

def try_anthropic(msgs):
    key = keys.get('anthropic','')
    if not key: return None
    system = next((m['content'] for m in msgs if m['role']=='system'), '')
    user_msgs = [m for m in msgs if m['role'] != 'system']
    payload = json.dumps({'model':'claude-sonnet-4-6','max_tokens':1024,'system':system,'messages':user_msgs}).encode()
    req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=payload,
        headers={'Content-Type':'application/json','x-api-key':key,'anthropic-version':'2023-06-01'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            tokens = data.get('usage',{}).get('input_tokens',0) + data.get('usage',{}).get('output_tokens',0)
            if tokens: accumulate_tokens('anthropic', tokens)
            return data['content'][0]['text']
    except: return None

def _try_openrouter(msgs, model, timeout=60):
    key = keys.get('openrouter','')
    if not key: return None
    payload = json.dumps({'model':model,'messages':msgs}).encode()
    req = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions', data=payload,
        headers={'Content-Type':'application/json','Authorization':f'Bearer {key}',
                 'HTTP-Referer':'http://localhost','X-Title':'master-ai'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
            tokens = data.get('usage',{}).get('total_tokens', 0)
            if tokens: accumulate_tokens('openrouter', tokens)
            return data['choices'][0]['message']['content']
    except: return None

def try_openrouter_405b(msgs):   return _try_openrouter(msgs, 'nousresearch/hermes-3-llama-3.1-405b:free', 90)
def try_openrouter_r1(msgs):     return _try_openrouter(msgs, 'deepseek/deepseek-r1:free', 90)
def try_openrouter_gptoss(msgs): return _try_openrouter(msgs, 'openai/gpt-oss-120b:free', 60)
def try_openrouter_nemotron(msgs):return _try_openrouter(msgs, 'nvidia/nemotron-3-super-120b-a12b:free', 60)
def try_openrouter_qwen3(msgs):  return _try_openrouter(msgs, 'qwen/qwen3-coder:free', 60)
def try_openrouter(msgs):        return _try_openrouter(msgs, 'meta-llama/llama-3.3-70b-instruct:free', 30)

reply = (try_groq(messages) or try_openrouter_405b(messages) or try_openrouter_r1(messages)
         or try_gemini(messages) or try_openrouter_nemotron(messages)
         or try_openrouter_gptoss(messages) or try_openrouter(messages))
if reply: print(reply)
else: sys.exit(1)
" "$messages_json" 2>/dev/null
}

# ── ROUTE DETECTION ──────────────────────────────────────────
detect_route() {
    local input_lower
    input_lower=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    local web_words="latest today current news search find weather price recently 2025 2026"
    local complex_words="explain analyze compare difference pros cons strategy why detailed thorough"
    for w in $web_words; do [[ "$input_lower" == *"$w"* ]] && { echo "web"; return; }; done
    for w in $complex_words; do [[ "$input_lower" == *"$w"* ]] && { echo "cloud"; return; }; done
    echo "local"
}

# ── MODES ────────────────────────────────────────────────────
mode_label() {
    case "$MODE" in
        plan) echo "${C}[PLAN]${X}" ;;
        auto) echo "${Y}[AUTO]${X}" ;;
        *)    echo "${G}[SAFE]${X}" ;;
    esac
}

show_mode_status() {
    echo ""
    echo -e "${W}  ────────────────────────────────────────────────────────────${X}"
    case "$MODE" in
        plan)
            echo -e "  ${C}MODE: PLAN${X}   ${W}AI formulates a plan first — nothing runs until you say ${W}go${X}"
            ;;
        auto)
            echo -e "  ${Y}MODE: AUTO${X}   ${W}Non-blocked commands run without prompting. Type ${W}mode safe${W} to go back.${X}"
            ;;
        safe)
            echo -e "  ${G}MODE: SAFE${X}   ${W}4-option confirm for every command (default)${X}"
            ;;
    esac
    echo -e "${W}  ────────────────────────────────────────────────────────────${X}"
    echo ""
}

display_pending_plan() {
    [ -z "$PENDING_PLAN_TEXT" ] && return
    echo ""
    echo -e "${W}  ╔══════════════════════════════════════════════════════╗${X}"
    echo -e "${W}  ║${X}  ${C}📋 Pending Plan${X}"
    echo -e "${W}  ╠══════════════════════════════════════════════════════╣${X}"
    while IFS= read -r line; do
        echo -e "${W}  ║${X}  ${W}${line}${X}"
    done <<< "$PENDING_PLAN_TEXT"
    echo -e "${W}  ╠══════════════════════════════════════════════════════╣${X}"
    echo -e "${W}  ║${X}  Type ${G}go${X} to execute  │  ${Y}plan <new request>${X} to re-plan  │  ${R}cancel${X} to clear"
    echo -e "${W}  ╚══════════════════════════════════════════════════════╝${X}"
    echo ""
}

ask_ai_plan_mode() {
    local user_input="$1"
    local memory_content
    memory_content=$(cat "$MEMORY_FILE" 2>/dev/null)
    local git_ctx
    git_ctx=$(git_context)
    local how_we_work
    how_we_work=$(cat "$HOME/scripts/howwework.txt" 2>/dev/null)

    local system_prompt="You are Master AI — a planning assistant on Elijah's Linux PC.

In PLAN MODE your job is to think through the user's request and output a clear numbered plan.
Do NOT output RUN:, READ:, or CREATE: directives. Do NOT execute anything.
Output ONLY a numbered list of steps describing exactly what you will do.

Format:
STEP 1: <what you'll do>
STEP 2: <what you'll do>
...

Keep each step concise. After the steps, add one line: READY: <one sentence summary of the full plan>.

[HOW WE WORK]
${how_we_work}

[MEMORY]
${memory_content}

[GIT CONTEXT]
${git_ctx}"

    local result
    result=$(python3 -c "
import json, sys, urllib.request
system = sys.argv[1]; user = sys.argv[2]; model = sys.argv[3]
url = sys.argv[4]
messages = [{'role':'system','content':system},{'role':'user','content':user}]
payload = json.dumps({'model':model,'messages':messages,'stream':False}).encode()
try:
    req = urllib.request.Request(url+'/api/chat', data=payload, headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        print(json.loads(r.read())['message']['content'])
except Exception as e:
    sys.stderr.write(str(e)+'\n'); sys.exit(1)
" "$system_prompt" "$user_input" "$MODEL" "$OLLAMA_URL" 2>/dev/null)

    if [ -z "$result" ] && [ "$CLOUD_ENABLED" -eq 1 ]; then
        local cloud_msgs
        cloud_msgs=$(python3 -c "
import json,sys
print(json.dumps([{'role':'system','content':sys.argv[1]},{'role':'user','content':sys.argv[2]}]))
" "$system_prompt" "$user_input" 2>/dev/null)
        result=$(ask_ai_cloud "$cloud_msgs")
    fi

    echo "$result"
}

# ── RESPONSE CACHE ───────────────────────────────────────────
cache_key() {
    echo "$1" | tr '[:upper:]' '[:lower:]' | tr -s ' ' | md5sum | cut -d' ' -f1
}

cache_lookup() {
    local key="$1"
    [ ! -f "$CACHE_FILE" ] && return 1
    python3 -c "
import json, sys, time
key = sys.argv[1]
try:
    with open('$CACHE_FILE') as f:
        cache = json.load(f)
except:
    sys.exit(1)
entry = cache.get(key)
if not entry: sys.exit(1)
if time.time() - entry.get('ts', 0) > 86400: sys.exit(1)
entry['hits'] = entry.get('hits', 0) + 1
with open('$CACHE_FILE', 'w') as f:
    json.dump(cache, f)
print(entry['response'])
" "$key" 2>/dev/null
}

cache_store() {
    local key="$1" response="$2"
    python3 -c "
import json, sys, time
key = sys.argv[1]; response = sys.argv[2]
try:
    with open('$CACHE_FILE') as f:
        cache = json.load(f)
except:
    cache = {}
if len(cache) >= 500:
    for k in sorted(cache, key=lambda k: cache[k].get('ts', 0))[:50]:
        del cache[k]
cache[key] = {'response': response, 'ts': time.time(), 'hits': 0}
with open('$CACHE_FILE', 'w') as f:
    json.dump(cache, f)
" "$key" "$response" 2>/dev/null
}

# ── RUN COMMAND ──────────────────────────────────────────────
run_command() {
    local cmd="$1"
    echo -e "\n${W}  ▶ Running: ${W}${cmd}${X}"
    local output
    output=$(bash -c "$cmd" 2>&1)
    local exit_code=$?
    if [ -n "$output" ]; then
        echo -e "${G}${output}${X}"
    fi
    if [ $exit_code -eq 0 ]; then
        echo -e "${G}  ✅ Done.${X}"
    else
        echo -e "${R}  ❌ Exit code: ${exit_code}${X}"
    fi
    log "PC_CMD: $cmd"
    echo "$output"
}

# ── 4-OPTION PROMPT ──────────────────────────────────────────
confirm_run() {
    local cmd="$1"

    if grep -qxF "$cmd" "$APPROVED_FILE" 2>/dev/null; then
        echo -e "${W}  ⚡ Auto-approved: ${W}${cmd}${X}"
        run_command "$cmd"
        return
    fi

    if is_blocked "$cmd"; then
        echo -e "${R}  🚫 BLOCKED — dangerous command refused.${X}"
        log "BLOCKED: $cmd"
        return
    fi

    if [[ "$MODE" == "auto" ]]; then
        echo -e "${Y}  ⚡ AUTO: ${W}${cmd}${X}"
        run_command "$cmd"
        return
    fi

    local next_mode
    case "$MODE" in
        safe) next_mode="plan" ;;
        plan) next_mode="auto" ;;
        auto) next_mode="safe" ;;
        *)    next_mode="safe" ;;
    esac

    echo ""
    echo -e "  ${BC}┌─ ${Y}💻 AI wants to run ${BC}────────────────────────────────────${X}"
    echo -e "  ${BC}│${X}  ${W}${cmd}${X}"
    echo -e "  ${BC}├─────────────────────────────────────────────────────────${X}"
    if [ "$NO_MOUSE" -eq 1 ] || [ "$PHONE_MODE" -eq 1 ]; then
        echo -e "  ${BC}│${X}  ${Y}↑↓/Tab${W} navigate  ${Y}Enter${W} select  ${Y}1-5${W} direct${X}"
    fi
    echo -e "  ${BC}└─────────────────────────────────────────────────────────${X}"
    prompt_choice "Yes — run once" "Always — never ask again" "No — skip" "Edit — modify before run" "Mode: ${MODE} → ${next_mode}"

    case "$CHOICE" in
        1)
            run_command "$cmd"
            ;;
        2)
            echo "$cmd" >> "$APPROVED_FILE"
            echo -e "${G}  ✅ Added to approved list.${X}"
            run_command "$cmd"
            ;;
        3)
            echo -e "${Y}  ⏭  Skipped.${X}"
            ;;
        4)
            echo -ne "${C}  Edit command: ${X}"
            read -e -i "$cmd" EDITED_CMD
            if [ -n "$EDITED_CMD" ]; then
                if is_blocked "$EDITED_CMD"; then
                    echo -e "${R}  🚫 BLOCKED — dangerous command refused.${X}"
                else
                    run_command "$EDITED_CMD"
                fi
            fi
            ;;
        5)
            MODE="$next_mode"
            echo -e "${G}  ✅ Mode switched to: ${W}${MODE}${X}"
            confirm_run "$cmd"
            ;;
        *)
            echo -e "${Y}  ⏭  Skipped.${X}"
            ;;
    esac
}

# ── FILE CREATE CONFIRM ───────────────────────────────────────
confirm_create() {
    local filepath="$1"
    local content="$2"
    local dir
    dir=$(dirname "$filepath")
    local line_count
    line_count=$(echo "$content" | wc -l)

    echo ""
    echo -e "  ${BC}┌─ ${Y}📝 AI wants to create a file ${BC}────────────────────────────${X}"
    echo -e "  ${BC}│${X}  ${W}${filepath}${X}  ${C}(${line_count} lines)${X}"
    echo -e "  ${BC}├─────────────────────────────────────────────────────────${X}"
    if [ "$NO_MOUSE" -eq 1 ] || [ "$PHONE_MODE" -eq 1 ]; then
        echo -e "  ${BC}│${X}  ${Y}↑↓/Tab${W} navigate  ${Y}Enter${W} select  ${Y}1-4${W} direct${X}"
    fi
    echo -e "  ${BC}└─────────────────────────────────────────────────────────${X}"
    prompt_choice "Create — write file now" "Review — preview first" "Edit — open in editor" "No — skip"

    case "$CHOICE" in
        1)
            mkdir -p "$dir" 2>/dev/null
            printf '%s' "$content" > "$filepath"
            echo -e "${G}  ✅ Created: ${W}${filepath}${X}"
            log "PC_CREATE: $filepath"
            ;;
        2)
            echo -e "\n  ${BC}◈ File Preview${X}"
            echo -e "  ${BC}─────────────────────────────────────────────────${X}"
            echo "$content" | head -50
            [ "$line_count" -gt 50 ] && echo -e "  ${C}... (truncated at 50 lines)${X}"
            echo -e "  ${BC}─────────────────────────────────────────────────${X}"
            echo -ne "  ${BC}[MAI]${X} ${Y}▸ ${X}Create this file? (y/N): "
            read -r CONF
            if [[ "$CONF" == "y" || "$CONF" == "Y" ]]; then
                mkdir -p "$dir" 2>/dev/null
                printf '%s' "$content" > "$filepath"
                echo -e "${G}  ✅ Created: ${W}${filepath}${X}"
                log "PC_CREATE: $filepath"
            else
                echo -e "${Y}  ⏭  Skipped.${X}"
            fi
            ;;
        3)
            local tmpfile="/tmp/pc_create_$$.tmp"
            printf '%s' "$content" > "$tmpfile"
            ${EDITOR:-nano} "$tmpfile"
            mkdir -p "$dir" 2>/dev/null
            cp "$tmpfile" "$filepath"
            rm -f "$tmpfile"
            echo -e "${G}  ✅ Created (edited): ${W}${filepath}${X}"
            log "PC_CREATE_EDITED: $filepath"
            ;;
        *)
            echo -e "${Y}  ⏭  Skipped.${X}"
            ;;
    esac
}

# ── AI ENGINE ────────────────────────────────────────────────
ask_ai() {
    local user_input="$1"

    local bypass=0
    if [[ "$user_input" == !* ]]; then
        bypass=1
        user_input="${user_input#!}"
        user_input="${user_input## }"
    fi

    local ck
    ck=$(cache_key "$user_input")

    if [[ "$bypass" -eq 0 && "${#INJECTED_FILES[@]}" -eq 0 ]]; then
        local cached
        cached=$(cache_lookup "$ck")
        if [ -n "$cached" ]; then
            echo -e "${W}  ⚡ Cache hit${X}" >&2
            show_hint "Instant Answer (Cache)" \
"This answer was stored from a previous session.
No AI was called — the response is instant.
To force a fresh answer, type  !  before your question:
  ! check if ollama is running
To clear all cached answers: clear cache" >&2
            echo "$cached"
            return
        fi
    fi

    local memory_content
    memory_content=$(cat "$MEMORY_FILE" 2>/dev/null)

    local git_ctx
    git_ctx=$(git_context)

    local how_we_work
    how_we_work=$(cat "$HOME/scripts/howwework.txt" 2>/dev/null)

    local injected_block=""
    if [ "${#INJECTED_FILES[@]}" -gt 0 ]; then
        for path in "${!INJECTED_FILES[@]}"; do
            injected_block+="--- ${path} ---"$'\n'
            injected_block+="${INJECTED_FILES[$path]}"$'\n\n'
        done
    fi

    local system_prompt="You are Master AI — an AI agent running on Elijah's Linux PC (Madam-Mary, Ubuntu).

You control this machine. Available directives:

RUN: <bash command>
  Execute shell commands. Use for: git ops, file ops, installs, system tasks.
  For multi-step tasks emit one RUN: per step covering the FULL task.

READ: <filepath or directory>
  Request a file or directory be injected into context before you proceed.
  Always READ before editing existing files. You may emit multiple READ: lines.

CREATE: <filepath>
<<<CONTENT
<complete file content here>
>>>CONTENT
  Write a new file. Provide complete content — no placeholders or TODOs.
  For editing existing files use RUN: with sed or tee.

Git workflow via RUN::
  RUN: git -C <dir> status
  RUN: git -C <dir> add <files>
  RUN: git -C <dir> commit -m \"<message>\"
  RUN: git -C <dir> push origin <branch>
  RUN: gh pr create --title \"...\" --body \"...\"

Never emit: rm -rf / | rm -rf ~ | mkfs | dd if= | fork bombs

If just chatting with no action needed, reply normally — no directives.

[HOW WE WORK]
${how_we_work}

[MEMORY]
${memory_content}

[GIT CONTEXT]
${git_ctx}

[INJECTED FILES]
${injected_block}"

    local route
    route=$(detect_route "$user_input")
    local augmented_input="$user_input"

    if [[ "$route" == "web" && "$WEB_ENABLED" -eq 1 ]]; then
        local search_results
        search_results=$(web_search "$user_input")
        if [ -n "$search_results" ]; then
            augmented_input="${user_input}

[Web search results]
${search_results}"
        fi
        route="cloud"
    fi

    if [[ "$route" == "cloud" && "$CLOUD_ENABLED" -eq 1 ]]; then
        local cloud_messages
        cloud_messages=$(python3 -c "
import json, sys
system = sys.argv[1]
user   = sys.argv[2]
hfile  = sys.argv[3]
try:
    with open(hfile) as f:
        history = json.load(f)
except Exception:
    history = []
messages = [{'role':'system','content':system}] + history + [{'role':'user','content':user}]
print(json.dumps(messages))
" "$system_prompt" "$augmented_input" "$HIST_FILE" 2>/dev/null)

        local cloud_reply
        cloud_reply=$(ask_ai_cloud "$cloud_messages")

        if [ -n "$cloud_reply" ]; then
            python3 -c "
import json, sys
hfile = sys.argv[1]; user = sys.argv[2]; reply = sys.argv[3]
try:
    with open(hfile) as f: history = json.load(f)
except: history = []
history.append({'role':'user','content':user})
history.append({'role':'assistant','content':reply})
if len(history) > 40: history = history[-40:]
with open(hfile,'w') as f: json.dump(history,f)
" "$HIST_FILE" "$augmented_input" "$cloud_reply" 2>/dev/null
            echo "$cloud_reply"
            return
        fi
    fi

    local result
    result=$(python3 -c "
import json, sys, urllib.request

system = sys.argv[1]
user   = sys.argv[2]
model  = sys.argv[3]
hfile  = sys.argv[4]
url    = sys.argv[5]

try:
    with open(hfile) as f:
        history = json.load(f)
except Exception:
    history = []

messages = [{'role': 'system', 'content': system}] + history + [{'role': 'user', 'content': user}]
payload  = json.dumps({'model': model, 'messages': messages, 'stream': False}).encode()

try:
    req = urllib.request.Request(url + '/api/chat', data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data  = json.loads(resp.read())
        reply = data['message']['content']
except Exception as e:
    sys.stderr.write(str(e) + '\n')
    sys.exit(1)

history.append({'role': 'user',      'content': user})
history.append({'role': 'assistant', 'content': reply})
if len(history) > 40:
    history = history[-40:]
with open(hfile, 'w') as f:
    json.dump(history, f)

print(reply)
" "$system_prompt" "$augmented_input" "$MODEL" "$HIST_FILE" "$OLLAMA_URL" 2>/dev/null)

    if [ -n "$result" ]; then
        cache_store "$ck" "$result"
    fi

    echo "$result"
}

# ── COLLABORATOR MODE ─────────────────────────────────────────

is_code_task() {
    local lower
    lower=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    echo "$lower" | grep -qE '\b(code|script|function|python|bash|javascript|html|css|def |class |import |\.py|\.sh|\.html|\.js|debug|syntax|error in|bug|program|loop|variable|array|json|parse)\b'
}

is_complex_task() {
    local input="$1"
    local lower
    lower=$(echo "$input" | tr '[:upper:]' '[:lower:]')
    echo "$input" | grep -qE '(~/|/home/|\.sh|\.py|\.html|\.json|\.txt)' && return 0
    echo "$lower" | grep -qE '\b(fix|edit|update|change|why|debug|create|build|write|add|remove|rewrite|check.*error|look at|read|open|what.*wrong|broken|not working|help me|explain)\b' && return 0
    return 1
}

ask_ai_collab() {
    local user_input="$1"
    local extra_context="$2"
    local memory_content
    memory_content=$(cat "$MEMORY_FILE" 2>/dev/null)

    local system_prompt="You are Master AI — a collaborator on Elijah's Linux PC (Madam-Mary, Ubuntu).
You work like a skilled engineer: think before acting, read before editing, verify after running.

DIRECTIVES — output exactly one per response:
  THINK: <reasoning>      — show your thinking before acting (auto-continues, not shown to user)
  READ: <filepath>        — read a file to get context before making changes
  RUN: <bash command>     — run a command (output will be fed back to you)
  ASK: <question>         — you need input from Elijah before continuing
  DONE: <summary>         — task complete, summarize what you did

RULES:
- For file edits: always READ the file first, then RUN a targeted sed/patch command
- After every RUN: you will see the output — use it to verify success or diagnose failure
- If a command fails, THINK about why, then try a different approach
- Never say 'I can't' — find another way
- One directive per response only
- For simple questions with no action needed, reply in plain text (no directive)

Machine: Madam-Mary | User: elijah | Scripts: ~/scripts/ | Home: /home/elijah

[MEMORY]
${memory_content}
${extra_context}"

    local result
    result=$(python3 -c "
import json, sys, urllib.request
system = sys.argv[1]
user   = sys.argv[2]
url    = sys.argv[3]

try:
    with open('$HIST_FILE') as f:
        history = json.load(f)
except:
    history = []

messages = [{'role':'system','content':system}] + history[-10:] + [{'role':'user','content':user}]
payload  = json.dumps({'model':'llama-3.3-70b-versatile','messages':messages,'max_tokens':512,'stream':False}).encode()

try:
    import os
    keys = json.load(open('$KEYS_FILE'))
except: keys = {}

def _or(msgs, model, timeout=60):
    key = keys.get('openrouter','')
    if not key: return None
    p = json.dumps({'model':model,'messages':msgs}).encode()
    req = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions', data=p,
        headers={'Content-Type':'application/json','Authorization':f'Bearer {key}',
                 'HTTP-Referer':'http://localhost','X-Title':'master-ai'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())['choices'][0]['message']['content']
    except: return None

# Free cloud chain — biggest/best first, fastest last
chains = [
    lambda: __import__('json') and None or (lambda: (lambda k,p,req: (lambda r: json.loads(r.read())['choices'][0]['message']['content'])(urllib.request.urlopen(req,timeout=20)) if k else None)(keys.get('groq',''), json.dumps({'model':'llama-3.3-70b-versatile','messages':messages,'max_tokens':512,'stream':False}).encode(), urllib.request.Request('https://api.groq.com/openai/v1/chat/completions',data=json.dumps({'model':'llama-3.3-70b-versatile','messages':messages,'max_tokens':512,'stream':False}).encode(),headers={'Content-Type':'application/json','Authorization':f'Bearer {keys.get(\"groq\",\"\")}','User-Agent':'python-requests/2.31.0'})))(),
]

# Groq (fast, free)
reply = None
try:
    key = keys.get('groq','')
    if key:
        req = urllib.request.Request('https://api.groq.com/openai/v1/chat/completions', data=payload,
            headers={'Content-Type':'application/json','Authorization':f'Bearer {key}','User-Agent':'python-requests/2.31.0'})
        with urllib.request.urlopen(req, timeout=20) as r:
            reply = json.loads(r.read())['choices'][0]['message']['content']
except: pass
if not reply: reply = _or(messages,'nousresearch/hermes-3-llama-3.1-405b:free',90)
if not reply: reply = _or(messages,'deepseek/deepseek-r1:free',90)
if not reply:
    try:
        key = keys.get('gemini','')
        if key:
            text = '\n'.join(m['content'] for m in messages if m['role'] != 'system')
            gp = json.dumps({'contents':[{'parts':[{'text':text}]}]}).encode()
            url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}'
            req = urllib.request.Request(url, data=gp, headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req, timeout=20) as r:
                reply = json.loads(r.read())['candidates'][0]['content']['parts'][0]['text']
    except: pass
if not reply: reply = _or(messages,'nvidia/nemotron-3-super-120b-a12b:free',60)
if not reply: reply = _or(messages,'openai/gpt-oss-120b:free',60)
if not reply: reply = _or(messages,'meta-llama/llama-3.3-70b-instruct:free',30)
if reply: print(reply); sys.exit(0)

# fallback to local
try:
    payload2 = json.dumps({'model':'$MODEL','messages':messages,'stream':False}).encode()
    req2 = urllib.request.Request('$OLLAMA_URL/api/chat', data=payload2,
        headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req2, timeout=60) as r:
        print(json.loads(r.read())['message']['content'])
except Exception as e:
    sys.stderr.write(str(e)+'\n'); sys.exit(1)
" "$system_prompt" "$user_input" "$OLLAMA_URL" 2>/dev/null)

    echo "$result"
}

run_collab_loop() {
    local user_input="$1"
    local iteration=0
    local context=""
    local current_input="$user_input"

    while [ $iteration -lt 10 ]; do
        ((iteration++))

        local reply
        reply=$(ask_ai_collab "$current_input" "$context")

        if [ -z "$reply" ]; then
            echo -e "${R}  ❌ No response from AI.${X}"
            return
        fi

        # Save to history
        python3 -c "
import json
try:
    h = json.load(open('$HIST_FILE'))
except: h = []
h.append({'role':'user','content':'$current_input'})
h.append({'role':'assistant','content':$(echo "$reply" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')})
if len(h) > 40: h = h[-40:]
json.dump(h, open('$HIST_FILE','w'))
" 2>/dev/null

        # ── THINK: ──
        if echo "$reply" | grep -qiE '^\s*THINK:'; then
            local thought
            thought=$(echo "$reply" | sed 's/^[[:space:]]*THINK:[[:space:]]*//')
            echo -e "${D}  ◌ ${thought}${X}"
            context="${context}
[THOUGHT]: ${thought}"
            current_input="continue"
            continue
        fi

        # ── READ: ──
        if echo "$reply" | grep -qiE '^\s*READ:'; then
            local rpath
            rpath=$(echo "$reply" | grep -iE '^\s*READ:' | head -1 | sed 's/^[[:space:]]*READ:[[:space:]]*//')
            local exp_path
            exp_path=$(eval echo "$rpath" 2>/dev/null)
            if [ -f "$exp_path" ]; then
                echo -e "${D}  📖 Reading: ${exp_path}${X}"
                local file_content
                file_content=$(cat "$exp_path")
                context="${context}
[FILE: ${exp_path}]
${file_content}
[END FILE]"
                current_input="I have read the file. Continue."
            else
                context="${context}
[FILE NOT FOUND: ${rpath}]"
                current_input="That file was not found. Try a different approach."
            fi
            continue
        fi

        # ── RUN: ──
        if echo "$reply" | grep -qiE '^\s*RUN:'; then
            local cmd
            cmd=$(echo "$reply" | grep -iE '^\s*RUN:' | head -1 | sed 's/^[[:space:]]*RUN:[[:space:]]*//')
            local non_run
            non_run=$(echo "$reply" | grep -viE '^\s*RUN:' | sed '/^[[:space:]]*$/d')
            [ -n "$non_run" ] && echo -e "\n${W}  ${non_run}${X}"
            confirm_run "$cmd"
            local cmd_output
            cmd_output=$(bash -c "$cmd" 2>&1)
            context="${context}
[RUN]: ${cmd}
[OUTPUT]: ${cmd_output}"
            current_input="The command ran. Output: ${cmd_output}. Verify it worked or continue."
            continue
        fi

        # ── ASK: ──
        if echo "$reply" | grep -qiE '^\s*ASK:'; then
            local question
            question=$(echo "$reply" | sed 's/^[[:space:]]*ASK:[[:space:]]*//')
            echo -e "\n${C}  🥷 AI: ${W}${question}${X}"
            echo -ne "${C}  You: ${X}"
            read -r user_answer
            context="${context}
[ASK]: ${question}
[ANSWER]: ${user_answer}"
            current_input="$user_answer"
            continue
        fi

        # ── DONE: ──
        if echo "$reply" | grep -qiE '^\s*DONE:'; then
            local summary
            summary=$(echo "$reply" | sed 's/^[[:space:]]*DONE:[[:space:]]*//')
            echo ""
            echo -e "  ${G}┌─ ✅ Done ────────────────────────────────────────────${X}"
            echo -e "  ${G}│${X}  ${W}${summary}${X}"
            echo -e "  ${G}└─────────────────────────────────────────────────────${X}"
            echo ""
            log "COLLAB_DONE: $summary"
            return
        fi

        # ── plain text (conversational) ──
        echo -e "\n${C}  🥷 AI: ${W}${reply}${X}\n"
        log "AI: $reply"
        return
    done

    echo -e "${Y}  ⚠ Reached max steps. Type your next instruction.${X}"
}

draw_status_bar() {
    local mem_count app_count tts_label model_label web_label proj_label cols pad
    mem_count=$(wc -l < "$MEMORY_FILE" 2>/dev/null || echo 0)
    app_count=$(wc -l < "$APPROVED_FILE" 2>/dev/null || echo 0)
    [ "$TTS_OK"       -eq 1 ] && tts_label="TTS:ON"       || tts_label="TTS:OFF"
    [ "$CLOUD_ENABLED" -eq 1 ] && model_label="LOCAL+CLOUD" || model_label="LOCAL"
    [ "$WEB_ENABLED"   -eq 1 ] && web_label="WEB:ON"       || web_label="WEB:OFF"
    [ -n "$ACTIVE_PROJECT" ]   && proj_label=" │  PRJ:$(basename $ACTIVE_PROJECT)" || proj_label=""
    cols=$(tput cols 2>/dev/null || echo 80)
    local mode_bar
    case "$MODE" in
        plan) mode_bar="MODE:PLAN" ;;
        auto) mode_bar="MODE:AUTO" ;;
        *)    mode_bar="MODE:SAFE" ;;
    esac
    echo -e "\n${BC}  🥷 SENSEI${X}  ${W}│${X}  ${G}${mode_bar}${X}  ${W}│  MEM:${mem_count}  │  APPROVED:${app_count}  │  ${tts_label}  │  ${model_label}  │  ${web_label}${proj_label}  │  x=exit${X}\n"
}

show_plan_preview() {
    local -a cmds=("$@")
    local total=${#cmds[@]}
    echo ""
    echo -e "  ${BC}┌─ ${Y}📋 Plan  ${W}${total} steps ${BC}──────────────────────────────────────${X}"
    for (( i=0; i<total; i++ )); do
        echo -e "  ${BC}│${X}  ${BC}▸${X} ${W}${cmds[$i]}${X}"
    done
    echo -e "  ${BC}├─────────────────────────────────────────────────────────${X}"
    echo -e "  ${BC}│${X}  ${Y}1  ${W}Approve All   ${BC}run every step${X}"
    echo -e "  ${BC}│${X}  ${Y}2  ${W}Step by Step  ${BC}confirm each one${X}"
    echo -e "  ${BC}│${X}  ${Y}3  ${W}Cancel        ${BC}skip everything${X}"
    echo -e "  ${BC}└─────────────────────────────────────────────────────────${X}"
    echo -ne "  ${BC}[MAI]${X} ${Y}▸ ${X}"
    read -r PLAN_CHOICE
}

# ── BUILT-IN COMMANDS ─────────────────────────────────────────
handle_builtin() {
    local input="$1"
    local lower
    lower=$(echo "$input" | tr '[:upper:]' '[:lower:]')

    # help: <command> — show system manual + real usage in scripts
    if [[ "$lower" == help:* ]]; then
        local cmd="${input#*: }"
        cmd=$(echo "$cmd" | xargs)
        echo -e "${BC}  ── help: $cmd ──────────────────────────────────────${X}"
        local wdesc
        wdesc=$(whatis "$cmd" 2>/dev/null | head -1)
        [ -n "$wdesc" ] && echo -e "${W}  $wdesc${X}" || echo -e "${D}  (no whatis entry for '$cmd')${X}"
        echo ""
        local hlp
        hlp=$("$cmd" --help 2>&1 | head -15)
        if [ -n "$hlp" ]; then
            echo -e "${Y}  --help:${X}"
            echo "$hlp" | while IFS= read -r line; do
                echo -e "${D}  $line${X}"
            done
            echo ""
        fi
        local hits
        hits=$(grep -rn "\b${cmd}\b" ~/scripts/ --include="*.sh" --include="*.py" 2>/dev/null \
            | grep -v "^Binary" | head -6)
        if [ -n "$hits" ]; then
            echo -e "${Y}  Used in your scripts:${X}"
            echo "$hits" | while IFS= read -r line; do
                echo -e "${D}  $line${X}"
            done
        else
            echo -e "${D}  (not found in ~/scripts/)${X}"
        fi
        echo -e "${BC}  ─────────────────────────────────────────────────────${X}"
        return 0
    fi

    # task: <description> — save active task (case-sensitive, preserve text)
    if [[ "$lower" == task:* ]]; then
        local task_text="${input#*: }"
        echo "$task_text" > "$HOME/.master_ai_active_task"
        echo -e "${G}  ✅ Active task saved: ${W}${task_text}${X}"
        bash "$HOME/scripts/save_context.sh" > /dev/null 2>&1 &
        bash "$HOME/scripts/inject_memory.sh" > /dev/null 2>&1 &
        return 0
    fi

    case "$lower" in
        memory)
            echo ""
            local count
            count=$(wc -l < "$MEMORY_FILE" 2>/dev/null || echo 0)
            echo -e "${C}  📧 Memory (${count} entries):${X}"
            if [ "$count" -eq 0 ]; then
                echo -e "${W}  (empty)${X}"
            else
                while IFS= read -r line; do
                    echo -e "${W}  • ${line}${X}"
                done < "$MEMORY_FILE"
            fi
            echo ""
            return 0
            ;;
        approved)
            echo ""
            local count
            count=$(wc -l < "$APPROVED_FILE" 2>/dev/null || echo 0)
            echo -e "${C}  ⚡ Auto-approved commands (${count}):${X}"
            if [ "$count" -eq 0 ]; then
                echo -e "${W}  (none)${X}"
            else
                while IFS= read -r line; do
                    echo -e "${G}  ✅ ${line}${X}"
                done < "$APPROVED_FILE"
            fi
            echo ""
            return 0
            ;;
        "clear approved")
            > "$APPROVED_FILE"
            echo -e "${Y}  ✅ Approved list cleared.${X}"
            return 0
            ;;
        "reset permissions")
            rm -f "$PERMS_FILE"
            echo -e "${Y}  ✅ Permissions reset — wizard will run on next start.${X}"
            return 0
            ;;
        "clear history")
            echo "[]" > "$HIST_FILE"
            echo -e "${Y}  ✅ Conversation history cleared.${X}"
            return 0
            ;;
        cache)
            echo ""
            if [ ! -f "$CACHE_FILE" ]; then
                echo -e "${W}  Cache is empty.${X}"
            else
                python3 -c "
import json, time
try:
    with open('$CACHE_FILE') as f:
        cache = json.load(f)
    total = len(cache)
    hits = sum(e.get('hits',0) for e in cache.values())
    now = time.time()
    fresh = sum(1 for e in cache.values() if now - e.get('ts',0) < 86400)
    print(f'  Entries: {total}  |  Fresh (24h): {fresh}  |  Total hits: {hits}')
except: print('  (empty or unreadable)')
" 2>/dev/null
            fi
            echo ""
            return 0
            ;;
        "clear cache")
            rm -f "$CACHE_FILE"
            echo -e "${Y}  ✅ Cache cleared.${X}"
            return 0
            ;;
        tutorial)
            run_tutorial
            return 0
            ;;
        help)
            show_help
            return 0
            ;;
        "hints off")
            touch "$HINTS_FILE"
            HINTS=0
            echo -e "${Y}  ✅ Hints off. Type ${W}hints on${Y} to bring them back.${X}"
            return 0
            ;;
        "hints on")
            rm -f "$HINTS_FILE"
            HINTS=1
            echo -e "${G}  ✅ Hints on. Tips will appear as you use new features.${X}"
            return 0
            ;;
        hints)
            [ "$HINTS" -eq 1 ] && echo -e "${G}  Hints are ON.${X}" || echo -e "${Y}  Hints are OFF. Type ${W}hints on${Y} to enable.${X}"
            return 0
            ;;
        "no mouse"|"nomouse"|"no-mouse"|"keyboard mode"|"keyboard on")
            NO_MOUSE=1
            echo "NO_MOUSE=1" > "$SETTINGS_FILE"
            echo "PHONE_MODE=$PHONE_MODE" >> "$SETTINGS_FILE"
            echo -e "${G}  ✅ No-mouse mode ON. Menus now use ${Y}↑↓ arrows + Tab + Enter${G} to navigate.${X}"
            return 0
            ;;
        "mouse on"|"mouse mode"|"keyboard off")
            NO_MOUSE=0
            echo "NO_MOUSE=0" > "$SETTINGS_FILE"
            echo "PHONE_MODE=$PHONE_MODE" >> "$SETTINGS_FILE"
            echo -e "${G}  ✅ Mouse mode restored. Type a number to choose menu options.${X}"
            return 0
            ;;
        "phone mode"|"phone on"|"phone")
            PHONE_MODE=1
            echo "NO_MOUSE=$NO_MOUSE" > "$SETTINGS_FILE"
            echo "PHONE_MODE=1" >> "$SETTINGS_FILE"
            echo -e "${G}  ✅ Phone mode ON. Compact layout with navigation hints shown.${X}"
            return 0
            ;;
        "phone off"|"desktop mode")
            PHONE_MODE=0
            echo "NO_MOUSE=$NO_MOUSE" > "$SETTINGS_FILE"
            echo "PHONE_MODE=0" >> "$SETTINGS_FILE"
            echo -e "${G}  ✅ Phone mode OFF.${X}"
            return 0
            ;;
        task)
            if [ -f "$HOME/.master_ai_active_task" ] && [ -s "$HOME/.master_ai_active_task" ]; then
                echo -e "  ${BC}◈ Active Task:${X}"
                cat "$HOME/.master_ai_active_task" | while IFS= read -r line; do
                    echo -e "  ${W}${line}${X}"
                done
            else
                echo -e "  ${Y}No active task set. Type: ${W}task: <description>${X}"
            fi
            return 0
            ;;
        "task clear")
            rm -f "$HOME/.master_ai_active_task"
            echo -e "${G}  ✅ Active task cleared.${X}"
            return 0
            ;;
        "accessibility"|"access")
            echo -e "  ${BC}◈ Accessibility Settings${X}"
            echo -e "  ${W}No-mouse mode:  ${Y}$([ $NO_MOUSE -eq 1 ] && echo ON || echo OFF)${X}"
            echo -e "  ${W}Phone mode:     ${Y}$([ $PHONE_MODE -eq 1 ] && echo ON || echo OFF)${X}"
            echo -e "  ${W}Commands:${X}"
            echo -e "  ${Y}  no mouse${W}     — arrow keys + Tab + Enter navigate menus${X}"
            echo -e "  ${Y}  mouse on${W}     — back to typing numbers${X}"
            echo -e "  ${Y}  phone mode${W}   — compact layout with nav hints${X}"
            echo -e "  ${Y}  phone off${W}    — full desktop layout${X}"
            return 0
            ;;
        keys)
            python3 -c "
import json
KNOWN = [
    ('groq',        'Groq',             'console.groq.com/keys'),
    ('gemini',      'Gemini (free)',    'aistudio.google.com/app/apikey'),
    ('anthropic',   'Anthropic/Claude', 'console.anthropic.com/settings/api-keys'),
    ('openai',      'OpenAI',           'platform.openai.com/api-keys'),
    ('openrouter',  'OpenRouter',       'openrouter.ai/keys'),
    ('anthropic',   'Anthropic/Claude', 'console.anthropic.com/settings/keys'),
    ('gumroad',     'Gumroad',          'app.gumroad.com/settings/advanced'),
    ('huggingface', 'HuggingFace',      'huggingface.co/settings/tokens'),
    ('xai',         'xAI/Grok',         'console.x.ai'),
]
G='\033[92m';R='\033[91m';C='\033[96m';W='\033[97m';Y='\033[33m';D='\033[90m';X='\033[0m'
import os
keys_file = os.path.expanduser('~/.master_ai_keys')
try:
    saved = json.load(open(keys_file))
except:
    saved = {}
known_fields = {f for f,_,_ in KNOWN}
print()
print(f'  {D}{chr(9472)*60}{X}')
print(f'  {C}{\"SERVICE\":<18}{W}{\"STATUS\":<20}{D}GET KEY AT{X}')
print(f'  {D}{chr(9472)*60}{X}')
for field, label, url in KNOWN:
    val = saved.get(field, '')
    if val:
        masked = val[:6]+\"...\"+val[-4:] if len(val)>10 else \"(set)\"
        print(f'  {G}✅{X}  {W}{label:<18}{G}{masked:<20}{D}{url}{X}')
    else:
        print(f'  {R}○{X}   {D}{label:<18}{Y}{\"(not saved)\":<20}{D}{url}{X}')
extras = {k:v for k,v in saved.items() if k not in known_fields}
for k,v in extras.items():
    masked = v[:6]+\"...\"+v[-4:] if len(v)>10 else \"(set)\"
    print(f'  {G}✅{X}  {W}{k:<18}{G}{masked}{X}')
print(f'  {D}{chr(9472)*60}{X}')
n_saved=len(saved); n_miss=sum(1 for f,_,_ in KNOWN if not saved.get(f))
print(f'  {D}Saved: {G}{n_saved}{D}  Missing: {Y}{n_miss}{D}  |  update with: bash ~/scripts/update_keys.sh{X}')
print()
" 2>/dev/null
            return 0
            ;;
        "mode safe"|"mode plan"|"mode auto")
            MODE="${lower#mode }"
            show_mode_status
            return 0
            ;;
        mode)
            show_mode_status
            return 0
            ;;
        go|proceed|execute|"go ahead")
            if [ -z "$PENDING_PLAN_TEXT" ]; then
                echo -e "${Y}  No pending plan. Use ${W}mode plan${Y} then describe your task.${X}"
            else
                display_pending_plan
                echo -ne "  ${BC}[MAI]${X} ${Y}Execute plan? (y/N): ${X}"
                read -r CONF
                if [[ "$CONF" == "y" || "$CONF" == "Y" ]]; then
                    local saved_mode="$MODE"
                    MODE="safe"
                    echo -e "${W}  thinking...${X}"
                    local exec_reply
                    exec_reply=$(ask_ai "$PENDING_PLAN_REQUEST")
                    local saved_request="$PENDING_PLAN_REQUEST"
                    PENDING_PLAN_TEXT=""
                    PENDING_PLAN_REQUEST=""
                    MODE="$saved_mode"
                    EXECUTE_REPLY="$exec_reply"
                    log "USER: go — executing plan for: $saved_request"
                    log "AI: $exec_reply"
                else
                    echo -e "${Y}  Plan kept. Type ${W}go${Y} again when ready or ${W}cancel${Y} to clear.${X}"
                fi
            fi
            return 0
            ;;
        cancel)
            if [ -n "$PENDING_PLAN_TEXT" ]; then
                PENDING_PLAN_TEXT=""
                PENDING_PLAN_REQUEST=""
                echo -e "${Y}  ✅ Plan cleared.${X}"
            else
                echo -e "${W}  Nothing to cancel.${X}"
            fi
            return 0
            ;;
        project)
            if [ -n "$ACTIVE_PROJECT" ]; then
                echo -e "${C}  Active project: ${W}${ACTIVE_PROJECT}${X}"
            else
                echo -e "${W}  No active project set. Use: ${W}project <path>${X}"
            fi
            return 0
            ;;
        x|exit|quit)
            echo -e "${G}\n  Goodbye.\n${X}"
            log "PC_CONTROL exited"
            exit 0
            ;;
        kick|"force restart"|"hard restart")
            echo -e "\n${R}  💥 KICKING PC CONTROL — re-launching...${X}\n"
            log "PC_CONTROL kick — re-exec"
            sleep 0.5
            exec bash "$HOME/scripts/pc_control.sh"
            ;;
        refresh|reload|restart)
            echo -e "\n${C}  🔄 REFRESHING PC CONTROL — re-launching...${X}\n"
            log "PC_CONTROL refresh — re-exec"
            sleep 0.3
            exec bash "$HOME/scripts/pc_control.sh"
            ;;
    esac

    if [[ "$lower" == project\ * ]]; then
        local proj_path="${input#* }"
        proj_path=$(eval echo "$proj_path")
        if [ -d "$proj_path" ]; then
            ACTIVE_PROJECT="$proj_path"
            echo -e "${G}  ✅ Active project set: ${W}${proj_path}${X}"
            echo -e "${W}  Scanning structure...${X}"
            local structure
            structure=$(find "$proj_path" -type f | grep -v -E '(node_modules|\.git|__pycache__|\.pyc)' | head -60 2>/dev/null)
            echo -e "${C}  Files:${X}"
            echo "$structure" | while read -r f; do echo -e "${W}    ${f}${X}"; done
            INJECTED_FILES["$proj_path (structure)"]="$structure"
        else
            echo -e "${R}  ❌ Directory not found: ${proj_path}${X}"
        fi
        return 0
    fi

    if [[ "$lower" == search\ * ]]; then
        local query="${input#* }"
        local results
        results=$(web_search "$query")
        if [ -n "$results" ]; then
            echo -e "\n${W}${results}${X}\n"
        else
            echo -e "${Y}  ⚠  No results or web search not available.${X}"
        fi
        return 0
    fi

    if [[ "$lower" == gdrive\ * ]]; then
        local gdrive_query="${input#* }"
        echo -e "${W}  Routing to Claude Code (Google Drive MCP)...${X}"
        if command -v claude &>/dev/null; then
            claude "$gdrive_query" 2>/dev/null || echo -e "${R}  ❌ Claude CLI returned an error.${X}"
        else
            echo -e "${R}  ❌ Claude CLI not found. Is Claude Code installed?${X}"
        fi
        return 0
    fi

    if [[ "$input" == remember:* ]]; then
        local fact="${input#remember: }"
        fact="${fact#remember:}"
        fact="${fact## }"
        echo "$fact" >> "$MEMORY_FILE"
        echo -e "${G}  ✅ Remembered: ${W}${fact}${X}"
        log "MEMORY_SAVED: $fact"
        return 0
    fi

    if [[ "$input" == forget:* ]]; then
        local keyword="${input#forget: }"
        keyword="${keyword#forget:}"
        keyword="${keyword## }"
        local before
        before=$(wc -l < "$MEMORY_FILE")
        grep -v "$keyword" "$MEMORY_FILE" > /tmp/mem_tmp && mv /tmp/mem_tmp "$MEMORY_FILE"
        local after
        after=$(wc -l < "$MEMORY_FILE")
        local removed=$(( before - after ))
        echo -e "${Y}  ✅ Removed ${removed} line(s) matching: ${W}${keyword}${X}"
        return 0
    fi

    return 1
}

# ── MAIN ─────────────────────────────────────────────────────
main() {
    clear
    banner_master_ai
    echo ""
    echo -e "${BC}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
    echo -e "  ${Y}PC CONTROL${X} — ${W}AI agent that runs commands on this machine${X}"
    echo ""
    echo -e "  ${W}Talk to it in plain English. It thinks, acts, and remembers.${X}"
    echo -e "  ${W}Runs locally on Madam-Mary. No cloud required.${X}"
    echo ""
    echo -e "  ${Y}Modes:${X}  ${W}safe${X} ${BC}(ask before every command)${X}  ${W}plan${X} ${BC}(preview first)${X}  ${W}auto${X} ${BC}(runs without asking)${X}"
    echo -e "  ${Y}Memory:${X} ${W}remember: <fact>${X}   ${Y}Approved:${X} ${W}approved${X} ${BC}(list auto-run commands)${X}"
    echo ""
    echo -e "${BC}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
    echo ""
    echo -ne "  \e[5m${Y}Press ENTER to continue...${X}\e[0m"
    read -r

    if [ ! -f "$TUTORIAL_FILE" ]; then
        run_tutorial
    fi

    permissions_wizard
    startup_check

    declare -A INJECTED_FILES
    EXECUTE_REPLY=""
    local HINT_RUN_SHOWN=0
    local HINT_CHAT_SHOWN=0
    local HINT_CACHE_SHOWN=0
    local HINT_MODE_SHOWN=0

    local mem_count
    mem_count=$(wc -l < "$MEMORY_FILE" 2>/dev/null || echo 0)
    local app_count
    app_count=$(wc -l < "$APPROVED_FILE" 2>/dev/null || echo 0)

    echo -e "${W}  Memory: ${W}${mem_count} facts${W} | Auto-approved: ${W}${app_count} commands${X}"
    echo ""
    echo -e "${W}  Type ${W}help${W} for a command reference  |  ${W}keys${W} to view API key status  |  ${W}tutorial${W} to replay the walkthrough${X}"
    echo -e "${W}  Modes: ${W}mode safe${W} (default) · ${W}mode plan${W} (think first, then ${W}go${W}) · ${W}mode auto${W} (no prompts)${X}"
    echo -e "${W}  ──────────────────────────────────────────────────────────────────${X}"
    echo ""

    echo "[]" > "$HIST_FILE"
    log "=== PC CONTROL STARTED ==="
    [ -f "$HOME/scripts/check_key_expiry.sh" ] && bash "$HOME/scripts/check_key_expiry.sh" &

    while true; do
        draw_status_bar
        echo -ne "${C}  🥷 You: ${X}"
        read -er USER_INPUT

        [ -z "$USER_INPUT" ] && continue

        handle_builtin "$USER_INPUT"
        if [ $? -eq 0 ]; then
            if [ -n "$EXECUTE_REPLY" ]; then
                REPLY="$EXECUTE_REPLY"
                EXECUTE_REPLY=""
            else
                continue
            fi
        else

        # Direct bash command detection — if first word is a real executable, run it
        local _first_word="${USER_INPUT%% *}"
        if command -v "$_first_word" &>/dev/null 2>&1; then
            log "DIRECT_CMD: $USER_INPUT"
            confirm_run "$USER_INPUT"
            continue
        fi

        if [[ "$MODE" == "plan" ]]; then
            stty -echo 2>/dev/null
            echo -e "${W}  planning...${X}"
            PLAN_REPLY=$(ask_ai_plan_mode "$USER_INPUT")
            stty echo 2>/dev/null
            if [ -z "$PLAN_REPLY" ]; then
                echo -e "${R}  ❌ No response. Is Ollama running?${X}"
                continue
            fi
            PENDING_PLAN_TEXT="$PLAN_REPLY"
            PENDING_PLAN_REQUEST="$USER_INPUT"
            display_pending_plan
            log "USER: $USER_INPUT"
            log "PLAN: $PLAN_REPLY"
            continue
        fi

        if is_code_task "$USER_INPUT"; then
            echo -e "${D}  ◌ coding... (qwen2.5-coder)${X}"
            local _saved_model="$MODEL"
            MODEL="$CODER_MODEL"
            run_collab_loop "$USER_INPUT"
            MODEL="$_saved_model"
            continue
        fi

        if is_complex_task "$USER_INPUT"; then
            echo -e "${D}  ◌ collaborating...${X}"
            run_collab_loop "$USER_INPUT"
            continue
        fi

        stty -echo 2>/dev/null
        echo -e "${W}  thinking...${X}"
        REPLY=$(ask_ai "$USER_INPUT")
        stty echo 2>/dev/null

        fi

        if [ -z "$REPLY" ]; then
            echo -e "${R}  ❌ No response. Is Ollama running?${X}"
            continue
        fi

        if echo "$REPLY" | grep -qiE '^\s*READ:'; then
            show_hint "AI is Reading Files" \
"The AI asked to read a file before answering.
This gives it the context it needs to help you accurately.
The file content is injected into the conversation — not uploaded anywhere.
After reading, the AI will respond with its answer or next action."
            mapfile -t READ_PATHS < <(echo "$REPLY" | grep -iE '^\s*READ:' | sed 's/^[[:space:]]*READ:[[:space:]]*//')
            local NON_READ
            NON_READ=$(echo "$REPLY" | grep -viE '^\s*READ:' | sed '/^[[:space:]]*$/d')
            [ -n "$NON_READ" ] && echo -e "\n${W}  AI: ${NON_READ}${X}"
            for rpath in "${READ_PATHS[@]}"; do
                local exp_path
                exp_path=$(eval echo "$rpath" 2>/dev/null)
                if [ -f "$exp_path" ]; then
                    INJECTED_FILES["$exp_path"]=$(head -c 8000 "$exp_path" 2>/dev/null)
                    local char_count=${#INJECTED_FILES["$exp_path"]}
                    echo -e "${W}  📄 Injected: ${W}${exp_path}${W} (${char_count} chars)${X}"
                elif [ -d "$exp_path" ]; then
                    INJECTED_FILES["$exp_path"]=$(ls -la "$exp_path" 2>/dev/null)
                    echo -e "${W}  📁 Dir injected: ${W}${exp_path}${X}"
                else
                    echo -e "${R}  ❌ READ: path not found: ${exp_path}${X}"
                fi
            done
            log "USER: $USER_INPUT"
            log "AI: $REPLY"
            continue
        fi

        if echo "$REPLY" | grep -qiE '^\s*CREATE:'; then
            show_hint "AI Wants to Create a File" \
"The AI will write a new file to your computer.
You have 4 options before anything is written:
  1) Create  — write the file now
  2) Review  — see the full contents first, then decide
  3) Edit    — open it in a text editor to modify before saving
  4) No      — skip it entirely
Nothing is written until you choose."
            local NON_CREATE
            NON_CREATE=$(echo "$REPLY" | grep -viE '^\s*(CREATE:|<<<CONTENT|>>>CONTENT)' | sed '/^[[:space:]]*$/d' | grep -v '^---')
            [ -n "$NON_CREATE" ] && echo -e "\n${W}  AI: ${NON_CREATE}${X}"
            local in_block=0
            local current_path=""
            local current_content=""
            while IFS= read -r line; do
                if [[ "$line" =~ ^[[:space:]]*CREATE:[[:space:]]*(.*) ]]; then
                    current_path=$(eval echo "${BASH_REMATCH[1]}" 2>/dev/null | xargs)
                    current_content=""
                    in_block=0
                elif [[ "$line" == "<<<CONTENT" && -n "$current_path" ]]; then
                    in_block=1
                elif [[ "$line" == ">>>CONTENT" && "$in_block" -eq 1 ]]; then
                    in_block=0
                    confirm_create "$current_path" "$current_content"
                    current_path=""
                    current_content=""
                elif [[ "$in_block" -eq 1 ]]; then
                    current_content+="$line"$'\n'
                fi
            done <<< "$REPLY"
            log "USER: $USER_INPUT"
            log "AI: $REPLY"
            continue
        fi

        if echo "$REPLY" | grep -qiE '^\s*RUN:'; then
            mapfile -t CMDS < <(echo "$REPLY" | grep -iE '^\s*RUN:' | sed 's/^[[:space:]]*RUN:[[:space:]]*//')
            local NON_RUN
            NON_RUN=$(echo "$REPLY" | grep -viE '^\s*RUN:' | sed '/^[[:space:]]*$/d')
            [ -n "$NON_RUN" ] && echo -e "\n${W}  AI: ${NON_RUN}${X}"

            local total_cmds=${#CMDS[@]}

            if [ "$HINT_RUN_SHOWN" -eq 0 ]; then
                show_hint "AI Wants to Run a Command" \
"The AI translated your request into a bash command.
You have 4 choices:
  1) Yes    — run it once
  2) Always — run it automatically from now on (never ask again)
  3) No     — skip, don't run it
  4) Edit   — you change the command before it runs
Nothing happens on your PC until you choose. You are in control."
                HINT_RUN_SHOWN=1
            fi

            if [ "$total_cmds" -gt 1 ]; then
                show_hint "Multi-Step Plan" \
"The AI has a plan with ${total_cmds} steps.
  1) Approve All  — run all steps without asking again
  2) Step by Step — you approve each command one at a time
  3) Cancel       — don't run anything
Tip: Use Step by Step the first time, Approve All once you trust it."
                show_plan_preview "${CMDS[@]}"
                case "$PLAN_CHOICE" in
                    1)
                        for (( s=0; s<total_cmds; s++ )); do
                            echo -e "\n${W}  ── Step $(( s+1 )) of ${total_cmds} ───────────────────────────────${X}"
                            is_blocked "${CMDS[$s]}" && { echo -e "${R}  🚫 BLOCKED.${X}"; log "BLOCKED: ${CMDS[$s]}"; continue; }
                            run_command "${CMDS[$s]}"
                        done
                        ;;
                    2)
                        for (( s=0; s<total_cmds; s++ )); do
                            echo -e "\n${W}  ── Step $(( s+1 )) of ${total_cmds} ───────────────────────────────${X}"
                            confirm_run "${CMDS[$s]}"
                        done
                        ;;
                    *)
                        echo -e "${Y}  ⏭  Plan cancelled.${X}"
                        ;;
                esac
            else
                confirm_run "${CMDS[0]}"
            fi
        else
            echo -e "\n${W}  AI: ${REPLY}${X}\n"
            speak "$REPLY"
            if [ "$HINT_CHAT_SHOWN" -eq 0 ]; then
                show_hint "Just Chatting" \
"The AI responded without running any commands — just a conversation.
You can ask it anything: questions, explanations, advice, ideas.
When you want it to DO something on your PC, ask directly:
  'create a folder called Projects'
  'check if ollama is running'
  'search for the latest Python news'"
                HINT_CHAT_SHOWN=1
            fi
        fi

        log "USER: $USER_INPUT"
        log "AI: $REPLY"
    done
}

main
