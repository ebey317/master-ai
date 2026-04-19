#!/bin/bash
source ~/scripts/brand.sh

LOG_FILE="$HOME/scripts/master.log"
SESSION_DIR="$HOME/scripts/sessions"
OLLAMA_URL="http://localhost:11434"
mkdir -p "$SESSION_DIR" "$HOME/scripts"
touch "$LOG_FILE"

log() {
    TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
    echo "[$TIMESTAMP] $1" | tee -a "$LOG_FILE"
}

# open_once <url> <title-keyword>
# Launches URL in Firefox only if no existing window title contains <keyword>.
# Avoids duplicate tabs — reuses/focuses the existing window instead.
open_once() {
    local url="$1" key="$2"
    if command -v wmctrl >/dev/null 2>&1 && wmctrl -l 2>/dev/null | grep -qi "$key"; then
        wmctrl -a "$key" 2>/dev/null || true
        echo "  ↺ already open: $key (focused existing window)"
    else
        firefox "$url" >/dev/null 2>&1 &
        echo "  ↗ opened: $url"
    fi
}

check_ollama() {
    log "--- Ollama Health Check ---"
    if curl -s --max-time 5 "$OLLAMA_URL" > /dev/null 2>&1; then
        log "OK — Ollama responding"
        echo "✅ Ollama is running."
    else
        log "ALERT — Ollama NOT responding"
        echo "⚠️  Ollama is DOWN."
    fi
}

check_rustdesk() {
    log "--- RustDesk Health Check ---"
    if systemctl is-active --quiet rustdesk; then
        RDID=$(rustdesk --get-id 2>/dev/null || echo "unknown")
        echo "✅ RustDesk running — ID: $RDID"
        log "OK — RustDesk active, ID: $RDID"
    else
        echo "⚠️  RustDesk is NOT running."
        log "ALERT — RustDesk NOT running"
    fi
}

launch_master_ai_terminal() {
    log "--- Launching Master AI ---"
    if ! pgrep -f "stt_server.py" > /dev/null; then
        bash "$HOME/scripts/serve_ui.sh" > /tmp/ui_server.log 2>&1 &
        sleep 1
    fi
    open_once "http://localhost:8080/master_ai.html" "Master AI"
    cd "$HOME/scripts"
    bash "$HOME/scripts/launch_master_ai.sh"
}

open_firefox_tabs() {
    log "--- Opening Firefox tabs ---"
    open_once "http://localhost:8080/master_ai.html" "Master AI"
    open_once "http://localhost:4040" "ngrok"
    echo "✅ Firefox tabs ready."
}

save_session() {
    local FILENAME="${1:-session}"
    local SAVE_PATH="$SESSION_DIR/${FILENAME}_$(date +%Y%m%d_%H%M%S).log"
    cp "$LOG_FILE" "$SAVE_PATH"
    log "SESSION SAVED: $SAVE_PATH"
    echo "✅ Session saved: $SAVE_PATH"
}

load_session() {
    local FILENAME="$1"
    local MATCH=$(ls "$SESSION_DIR" 2>/dev/null | grep "^$FILENAME" | tail -1)
    if [ -n "$MATCH" ]; then
        log "SESSION LOADED: $MATCH"
        echo "--- SESSION: $MATCH ---"
        cat "$SESSION_DIR/$MATCH"
        echo "--- END SESSION ---"
    else
        echo "⚠️  No session found for: $FILENAME"
    fi
}

PROJECTS_FILE="$HOME/scripts/PROJECTS.md"

prompt_idea() {
    local TITLE DESC STATUS TODAY
    TODAY=$(date "+%Y-%m-%d")

    echo -ne "${BC}Title:${X} "
    read -r TITLE
    [ -z "$TITLE" ] && { echo "  (cancelled — empty title)"; return 1; }

    echo -ne "${BC}Description:${X} "
    read -r DESC
    [ -z "$DESC" ] && { echo "  (cancelled — empty description)"; return 1; }

    echo -ne "${BC}Status${X} [idea/built/live] (default: idea): "
    read -r STATUS
    STATUS="${STATUS:-idea}"
    case "$STATUS" in idea|built|live) ;; *) STATUS="idea" ;; esac

    # Show alert/preview first — user decides whether to persist
    echo
    echo -e "${Y}╔══════════════════════════════════════════╗${X}"
    echo -e "${Y}║  🚨 IDEA ALERT — review before saving    ║${X}"
    echo -e "${Y}║${X}  [$TODAY] ${BC}$TITLE${X} (_${STATUS}_)"
    echo -e "${Y}║${X}  $DESC"
    echo -e "${Y}╚══════════════════════════════════════════╝${X}"
    echo
    echo -ne "${BC}Add to PROJECTS.md?${X} [y/N]: "
    read -r CONFIRM
    case "$CONFIRM" in
        y|Y|yes|YES) ;;
        *)
            log "IDEA DISCARDED: $TITLE"
            echo -e "${D}  ✗ not added. Idea discarded.${X}"
            return 0
            ;;
    esac

    # Ensure PROJECTS.md exists with the Ideas/POCs section
    if [ ! -f "$PROJECTS_FILE" ]; then
        log "WARN — PROJECTS.md missing, creating stub"
        {
            echo "# Elijah's Projects"
            echo
            echo "## Ideas / POCs"
            echo "<!-- auto-appended by master.sh option 9 -->"
        } > "$PROJECTS_FILE"
    fi
    grep -q "^## Ideas / POCs" "$PROJECTS_FILE" || {
        printf '\n## Ideas / POCs\n<!-- auto-appended by master.sh option 9 -->\n' >> "$PROJECTS_FILE"
    }

    printf -- '- [%s] **%s** (_%s_) — %s\n' "$TODAY" "$TITLE" "$STATUS" "$DESC" >> "$PROJECTS_FILE"

    log "NEW IDEA: [$STATUS] $TITLE — $DESC"
    echo -e "${BG}  ✅ added to ~/scripts/PROJECTS.md${X}"
}

startup() {
    clear
    banner_master_ai
    log "=== FULL STARTUP BEGIN ==="

    echo -e "${C}  1/3 Starting TTS server...${X}"
    if ! pgrep -f "tts_server.py" > /dev/null; then
        python3 "$HOME/scripts/tts_server.py" > /tmp/tts_server.log 2>&1 &
        sleep 2
        echo -e "${G}  ✅ TTS server started (port 5050).${X}"
    else
        echo -e "${G}  ✅ TTS server already running.${X}"
    fi

    echo -e "${C}  2/2 Starting SKS Hub (Vite dev server on :5173)...${X}"
    if ! pgrep -f "npm run dev" > /dev/null; then
        (cd "$HOME/Downloads/sunkissed-soul" && nohup npm run dev > /tmp/sks_hub.log 2>&1 &)
        sleep 2
        echo -e "${G}  ✅ SKS Hub started.${X}"
    else
        echo -e "${G}  ✅ SKS Hub already running.${X}"
    fi

    echo -e "${G}  ✅ All services launched!${X}"
    echo -e "${D}  (Skipping :8080 stt_server — Pupil replaces it. Run serve_ui.sh manually if you want Web Chat.)${X}"
    log "=== FULL STARTUP COMPLETE ==="
}

launch_master_ai() {
    clear
    banner_master_ai
    log "=== MASTER AI LAUNCH BEGIN ==="

    echo -e "${C}  1/2 Starting TTS server...${X}"
    if ! pgrep -f "tts_server.py" > /dev/null; then
        python3 "$HOME/scripts/tts_server.py" > /tmp/tts_server.log 2>&1 &
        sleep 2
        echo -e "${G}  ✅ TTS server started.${X}"
    else
        echo -e "${G}  ✅ TTS server already running.${X}"
    fi

    echo -e "${C}  2/2 Starting UI server...${X}"
    bash "$HOME/scripts/serve_ui.sh"
    sleep 1
    open_once "http://localhost:8080/master_ai.html" "Master AI"
    log "=== MASTER AI LAUNCH COMPLETE ==="
}

launch_pupil() {
    log "=== PUPIL LAUNCH ==="
    local html="$HOME/scripts/pupil.html"
    if [ ! -f "$html" ]; then
        echo -e "${R}  ❌ pupil.html not found at $html${X}"
        return 1
    fi
    # Pupil needs Ollama (required provider), TTS (optional, for voice)
    if ! curl -s -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo -e "${Y}  ⚠  Ollama not responding — attempting start...${X}"
        systemctl start ollama 2>/dev/null || true
        sleep 2
    fi
    if ! pgrep -f "tts_server.py" > /dev/null; then
        echo -e "${C}  Starting TTS server (for Pupil voice)...${X}"
        python3 "$HOME/scripts/tts_server.py" > /tmp/tts_server.log 2>&1 &
        sleep 1
    fi
    echo -e "${G}  ✅ Opening Pupil in Firefox...${X}"
    open_once "file://$html" "Pupil"
}

launch_sunkissed() {
    # SKS Assistant — the REMOTE-role chat UI (peer-node bridge vision).
    # Same provider list as Pupil (Ollama / Groq / OpenRouter / OpenAI / etc.)
    # but Ollama host is configurable inside the UI → can point at another
    # Master AI node's IP for true remote chat.
    log "=== SKS ASSISTANT LAUNCH ==="
    if ! pgrep -f "npm run dev" > /dev/null; then
        cd "$HOME/Downloads/sunkissed-soul"
        npm run dev > "$LOG_FILE.sunkissed" 2>&1 &
        sleep 5
        echo -e "${G}  ✅ SKS Hub dev server started on :5173${X}"
    else
        echo -e "${G}  ✅ SKS Hub already running.${X}"
    fi
    sleep 2
    # Open directly on the /Assistant route — skip the root landing page.
    open_once "http://localhost:5173/Assistant" "SKS Assistant"
}

view_sessions() {
    local CHATS="$HOME/.master_ai_chats"
    local PC_SESSIONS="$HOME/scripts/sessions"
    clear
    banner_master_ai
    echo -e "\n  ${BC}◈ Saved Chat Sessions${X}  ${W}(~/.master_ai_chats/)${X}"
    echo -e "  ${C}─────────────────────────────────────────${X}"
    local files=( $(ls -t "$CHATS"/*.json.gz "$CHATS"/*.json 2>/dev/null) )
    if [ ${#files[@]} -eq 0 ]; then
        echo -e "  ${W}No saved sessions yet.${X}"
    else
        local i=1
        for f in "${files[@]}"; do
            local base=$(basename "$f")
            local size=$(du -h "$f" | cut -f1)
            local date=$(date -r "$f" "+%Y-%m-%d %H:%M" 2>/dev/null)
            echo -e "  ${Y}$i)${W} $base  ${C}[$size]${W}  $date${X}"
            ((i++))
        done
        echo ""
        echo -ne "  ${BC}[MAI]${X} ${Y}▸ ${X}Enter number to view, or x to go back: "
        read -r SEL
        if [[ "$SEL" =~ ^[0-9]+$ ]] && [ "$SEL" -ge 1 ] && [ "$SEL" -le ${#files[@]} ]; then
            local chosen="${files[$((SEL-1))]}"
            echo ""
            if [[ "$chosen" == *.gz ]]; then
                python3 -c "import gzip,json,sys; d=json.load(gzip.open('$chosen','rt')); [print(m.get('role','?').upper()+': '+m.get('content','')) for m in d.get('messages',[])]" 2>/dev/null | less
            else
                python3 -c "import json; d=json.load(open('$chosen')); [print(m.get('role','?').upper()+': '+m.get('content','')) for m in d.get('messages',[])]" 2>/dev/null | less
            fi
        fi
    fi
    echo ""
    echo -e "  ${BC}◈ PC Control Sessions${X}  ${W}(~/scripts/sessions/)${X}"
    echo -e "  ${C}─────────────────────────────────────────${X}"
    local pcfiles=( $(ls -t "$PC_SESSIONS"/*.log 2>/dev/null) )
    if [ ${#pcfiles[@]} -eq 0 ]; then
        echo -e "  ${W}No PC control sessions yet.${X}"
    else
        for f in "${pcfiles[@]}"; do
            local size=$(du -h "$f" | cut -f1)
            echo -e "  ${Y}▸${W} $(basename "$f")  ${C}[$size]${X}"
        done
        echo ""
        echo -ne "  ${BC}[MAI]${X} ${Y}▸ ${X}Enter filename to view (or x): "
        read -r PSEL
        [[ "$PSEL" != "x" && "$PSEL" != "X" && -f "$PC_SESSIONS/$PSEL" ]] && less "$PC_SESSIONS/$PSEL"
    fi
}

main_menu() {
    clear
    banner_master_ai
    echo ""

    # 2-column row helper — if right col empty, print left col full-width
    row() {
        if [ -z "$3" ]; then
            printf "  ${Y}%3s)${W} %s${X}\n" "$1" "$2"
        else
            printf "  ${Y}%3s)${W} %-32s${Y}%4s)${W} %s${X}\n" "$1" "$2" "$3" "$4"
        fi
    }
    section() { echo -e "\n  ${BC}── $1 ──${X}"; }

    section "LAUNCH  (local apps shown by port)"
    row  "1" "Full startup (all services)"    "4" "Sensei (tmux AI)"
    row  "5" "Pupil (local — tied to Master AI)"      "6" "SKS Assistant (remote node bridge)"

    section "CHECKS"
    row  "2" "Check Ollama"                   "3" "Check RustDesk"

    section "RECOVER"
    row  "7" "Restart Sensei (force rebuild)" ""   ""

    section "WORK"
    row  "8" "View chat sessions"             "9" "Log a new idea / POC"

    section "SYSTEM"
    row "10" "How we work"                   "11" "Update API keys"
    row "12" "PC Clean + tune-up"            "13" "Learn Python + Build AI"
    row "14" "Uninstall"                     ""   ""

    echo ""
    echo -e "  ${Y}x)${W} Exit${X}"
    echo ""
    echo -ne "${C}  Choose: ${X}"
    read -r CHOICE

    # Short pause after read-only check commands so output is readable
    # before the menu redraws. Enter to continue, or auto-skip after 8 sec.
    pause_read() {
        echo ""
        read -t 8 -rp "  [press Enter to return — or wait 8s] " _ || true
    }

    case "$CHOICE" in
        1)  startup ;;
        2)  check_ollama; pause_read ;;
        3)  check_rustdesk; pause_read ;;
        4)  launch_master_ai_terminal ;;
        5)  launch_pupil ;;
        6)  launch_sunkissed ;;
        7)  echo -e "  ${Y}🔄 Force-rebuilding Sensei (kills tmux session, fresh start)...${X}"
            bash ~/scripts/master_ai_kick.sh
            pause_read ;;
        8)  view_sessions ;;
        9)  prompt_idea ;;
        10) less ~/scripts/howwework.txt ;;
        11) bash ~/scripts/update_keys.sh ;;
        12) sudo bash ~/scripts/system_tune.sh ;;
        13) bash ~/scripts/learn.sh ;;
        14) bash ~/scripts/uninstall.sh ;;
        x|X) log "--- Script Exited ---"; echo -e "${G}Goodbye.${X}"; exit 0 ;;
        *) echo "Invalid option." ;;
    esac

    main_menu
}

main_menu
