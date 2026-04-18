#!/bin/bash
# ============================================================
# MASTER AI — UNINSTALLER
# Run: bash ~/scripts/uninstall.sh
# ============================================================

source ~/scripts/brand.sh 2>/dev/null || true

G='\033[92m'; C='\033[96m'; W='\033[97m'
Y='\033[33m'; R='\033[31m'; D='\033[90m'; X='\033[0m'

confirm() {
    echo -ne "${R}  ⚠️  Are you sure? Type YES to confirm: ${X}"
    read -r ANS
    [[ "$ANS" == "YES" ]]
}

# ── LEVEL 1: PC CONTROL ONLY ─────────────────────────────────
remove_pc_control() {
    echo ""
    echo -e "${Y}  Removing PC Control...${X}"
    rm -f "$HOME/scripts/pc_control.sh"
    rm -f "$HOME/.master_ai_memory"
    rm -f "$HOME/.master_ai_approved"
    echo -e "${G}  ✅ pc_control.sh removed${X}"
    echo -e "${G}  ✅ Memory file removed${X}"
    echo -e "${G}  ✅ Approved commands removed${X}"
    echo ""
    echo -e "${W}  PC Control uninstalled. Everything else untouched.${X}"
}

# ── LEVEL 2: MASTER AI APP ─────────────────────────────────
remove_master-ai() {
    echo ""
    echo -e "${Y}  Removing Master AI app...${X}"

    # Scripts
    local scripts=(
        master.sh master_ai.py master_ai.html serve_ui.sh
        tts_server.py pc_control.sh brand.sh system_tune.sh
        update_keys.sh howwework.txt fix_ollama_host.sh
        cleanup.sh uninstall.sh install.sh
        Modelfile-master-ai master.log
    )
    for f in "${scripts[@]}"; do
        rm -f "$HOME/scripts/$f" && echo -e "${G}  ✅ Removed: scripts/${f}${X}"
    done

    # Sessions
    rm -rf "$HOME/scripts/sessions/"
    echo -e "${G}  ✅ Removed: scripts/sessions/${X}"

    # Personal data files
    rm -f "$HOME/.master_ai_keys"
    rm -f "$HOME/.master_ai_memory"
    rm -f "$HOME/.master_ai_approved"
    echo -e "${G}  ✅ Removed: API keys, memory, approved list${X}"

    # Remove scripts dir if empty
    rmdir "$HOME/scripts" 2>/dev/null && echo -e "${G}  ✅ Removed: ~/scripts/ (was empty)${X}"

    echo ""
    echo -e "${W}  Master AI removed. Ollama and models untouched.${X}"
}

# ── LEVEL 3: EVERYTHING ──────────────────────────────────────
remove_everything() {
    remove_master-ai

    echo ""
    echo -e "${Y}  Removing Ollama models...${X}"
    if command -v ollama &>/dev/null; then
        ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | while read -r model; do
            [ -z "$model" ] && continue
            ollama rm "$model" 2>/dev/null && echo -e "${G}  ✅ Removed model: ${model}${X}"
        done
    fi

    echo ""
    echo -e "${Y}  Uninstalling Ollama...${X}"
    if command -v ollama &>/dev/null; then
        sudo systemctl stop ollama 2>/dev/null
        sudo systemctl disable ollama 2>/dev/null
        sudo rm -f /usr/local/bin/ollama
        sudo rm -rf /usr/share/ollama
        sudo rm -f /etc/systemd/system/ollama.service
        sudo rm -rf /etc/systemd/system/ollama.service.d
        sudo systemctl daemon-reload 2>/dev/null
        echo -e "${G}  ✅ Ollama uninstalled${X}"
    else
        echo -e "${D}  Ollama not found — skipping${X}"
    fi

    echo ""
    echo -e "${Y}  Removing Python packages...${X}"
    pip3 uninstall -y openai duckduckgo-search requests 2>/dev/null
    echo -e "${G}  ✅ Python packages removed${X}"

    echo ""
    echo -e "${W}  Full uninstall complete. Machine is clean.${X}"
}

# ── MAIN MENU ─────────────────────────────────────────────────
clear
echo ""
echo -e "${R}╔══════════════════════════════════════════════════════╗${X}"
echo -e "${R}║${X}         ${W}MASTER AI — UNINSTALL${X}"
echo -e "${R}╠══════════════════════════════════════════════════════╣${X}"
echo -e "${R}║${X}  ${Y}1)${W} Remove PC Control only${X}"
echo -e "${R}║${X}     ${D}pc_control.sh + memory + approved list${X}"
echo -e "${R}║${X}"
echo -e "${R}║${X}  ${Y}2)${W} Remove Master AI app${X}"
echo -e "${R}║${X}     ${D}all scripts + UI + keys (keeps Ollama)${X}"
echo -e "${R}║${X}"
echo -e "${R}║${X}  ${Y}3)${W} Remove EVERYTHING${X}"
echo -e "${R}║${X}     ${D}full wipe — Ollama + models + all files${X}"
echo -e "${R}║${X}"
echo -e "${R}║${X}  ${Y}x)${W} Cancel${X}"
echo -e "${R}╚══════════════════════════════════════════════════════╝${X}"
echo ""
echo -ne "${C}  Choose (1/2/3/x): ${X}"
read -r CHOICE

case "$CHOICE" in
    1)
        echo ""
        echo -e "${Y}  This will remove: pc_control.sh, memory, approved commands.${X}"
        confirm && remove_pc_control || echo -e "${D}  Cancelled.${X}"
        ;;
    2)
        echo ""
        echo -e "${Y}  This will remove all Master AI scripts and your API keys.${X}"
        echo -e "${Y}  Ollama and your downloaded models will NOT be touched.${X}"
        confirm && remove_master-ai || echo -e "${D}  Cancelled.${X}"
        ;;
    3)
        echo ""
        echo -e "${R}  This will remove EVERYTHING — Ollama, all models, all scripts.${X}"
        echo -e "${R}  This cannot be undone.${X}"
        confirm && remove_everything || echo -e "${D}  Cancelled.${X}"
        ;;
    x|X)
        echo -e "${D}  Cancelled.${X}"
        ;;
    *)
        echo -e "${D}  Invalid option. Cancelled.${X}"
        ;;
esac

echo ""
