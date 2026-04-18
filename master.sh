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

alert_idea() {
    local IDEA="$1"
    TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
    log "🚨 NEW IDEA/POC: $IDEA"
    echo "╔══════════════════════════════════════════╗"
    echo "║  🚨 NEW IDEA / POC DISCOVERED            ║"
    echo "║  [$TIMESTAMP]"
    echo "║  $IDEA"
    echo "╚══════════════════════════════════════════╝"
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

    echo -e "${C}  2/3 Starting Master AI UI...${X}"
    bash "$HOME/scripts/serve_ui.sh"

    echo -e "${C}  3/3 Opening Firefox...${X}"
    sleep 2
    open_once "http://localhost:8080/master_ai.html" "Master AI"
    echo -e "${G}  ✅ All services launched!${X}"
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

launch_sunkissed() {
    log "=== SUNKISSED SOUL LAUNCH ==="
    if ! pgrep -f "npm run dev" > /dev/null; then
        cd "$HOME/Downloads/sunkissed-soul"
        npm run dev > "$LOG_FILE.sunkissed" 2>&1 &
        sleep 5
        echo "✅ Sunkissed Soul started on localhost:5173"
    else
        echo "✅ Sunkissed Soul already running."
    fi
    sleep 2
    open_once "http://localhost:5173" "Sunkissed"
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
    echo -e "${Y}  1)${W} Full startup (all services)${X}"
    echo -e "${Y}  2)${W} Check Ollama${X}"
    echo -e "${Y}  3)${W} Check RustDesk${X}"
    echo -e "${Y}  4)${W} Launch Master AI (terminal + UI)${X}"
    echo -e "${Y}  5)${W} Open Firefox tabs${X}"
    echo -e "${Y}  6)${W} Save session${X}"
    echo -e "${Y}  7)${W} Load session${X}"
    echo -e "${Y}  8)${W} Log a new idea / POC 🚨${X}"
    echo -e "${Y}  9)${W} Launch Sunkissed Soul (localhost:5173)${X}"
    echo -e "${Y} 10)${W} How we work${X}"
    echo -e "${Y} 11)${W} Launch Master AI UI (localhost:8080)${X}"
    echo -e "${Y} 12)${W} Update API keys${X}"
    echo -e "${Y} 13)${W} PC Clean + tune-up${X}"
    echo -e "${Y} 14)${W} PC Control (AI agent)${X}"
    echo -e "${Y} 15)${W} Uninstall${X}"
    echo -e "${Y} 16)${W} Learn Python + Build AI Apps${X}"
    echo -e "${Y} 17)${W} View chat sessions / transcripts${X}"
    echo -e "${Y}  x)${W} Exit${X}"
    echo ""
    echo -ne "${C}  Choose: ${X}"
    read -r CHOICE

    case "$CHOICE" in
        1) startup ;;
        2) check_ollama ;;
        3) check_rustdesk ;;
        4) launch_master_ai_terminal ;;
        5) open_firefox_tabs ;;
        6) echo -n "Session name: "; read -r SNAME; save_session "$SNAME" ;;
        7) echo -n "Session to load: "; read -r SNAME; load_session "$SNAME" ;;
        8) echo -n "Idea: "; read -r IDEA; alert_idea "$IDEA" ;;
        9) launch_sunkissed ;;
        10) less ~/scripts/howwework.txt ;;
        11) launch_master_ai ;;
        12) bash ~/scripts/update_keys.sh ;;
        13) sudo bash ~/scripts/system_tune.sh ;;
        14) bash ~/scripts/launch_master_ai.sh ;;
        15) bash ~/scripts/uninstall.sh ;;
        16) bash ~/scripts/learn.sh ;;
        17) view_sessions ;;
        x|X) log "--- Script Exited ---"; echo -e "${G}Goodbye.${X}"; exit 0 ;;
        *) echo "Invalid option." ;;
    esac

    main_menu
}

main_menu
