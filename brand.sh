#!/bin/bash
# ============================================================
# BRAND ASSETS — Master AI
# Source this in other scripts: source ~/scripts/brand.sh
# Preview: bash ~/scripts/brand.sh
# ============================================================

# ── COLORS ───────────────────────────────────────────────────
G='\033[92m'   # bright green
C='\033[96m'   # cyan
W='\033[97m'   # white
Y='\033[33m'   # yellow
R='\033[31m'   # red
D='\033[90m'   # dark grey
B='\033[94m'   # blue
M='\033[95m'   # magenta
X='\033[0m'    # reset
BOLD='\033[1m'

BC='\033[1;34m'  # bold blue  — banner (readable on light terminals)
BG='\033[1;32m'  # bold green — banner accent
BW='\033[97m'    # bright white — banner labels

# ── STATUS LINE ──────────────────────────────────────────────
status_line() {
    local HOST USER STATUS COLOR
    HOST=$(hostname)
    USER=$(whoami)
    STATUS="${1:-ONLINE}"
    COLOR="${2:-$G}"
    echo -e "${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
    echo -e "${C}  HOST:${W} ${HOST}${X}   ${C}USER:${W} ${USER}${X}   ${C}STATUS:${COLOR} ● ${STATUS}${X}"
    echo -e "${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
}

# ── MASTER AI BANNER (big block ASCII — for master.sh main menu) ─
banner_master_ai() {
    echo -e "
${BC}███╗   ███╗ █████╗ ███████╗████████╗███████╗██████╗ ${X}   ${BG} █████╗ ██╗${X}
${BC}████╗ ████║██╔══██╗██╔════╝╚══██╔══╝██╔════╝██╔══██╗${X}   ${BG}██╔══██╗██║${X}
${BC}██╔████╔██║███████║███████╗   ██║   █████╗  ██████╔╝${X}   ${BG}███████║██║${X}
${BC}██║╚██╔╝██║██╔══██║╚════██║   ██║   ██╔══╝  ██╔══██╗${X}   ${BG}██╔══██║██║${X}
${BC}██║ ╚═╝ ██║██║  ██║███████║   ██║   ███████╗██║  ██║${X}   ${BG}██║  ██║██║${X}
${BC}╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═╝${X}   ${BG}╚═╝  ╚═╝╚═╝${X}"
    echo -e "${BC}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
    echo -e "${BC}  🥷 POWERED BY:${BG} MASTER AI${X}   ${BC}HOST:${BW} $(hostname)${X}   ${BC}BY:${BW} $(whoami)${X}   ${BC}STATUS:${BG} ● ONLINE${X}"
    echo -e "${BC}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
}

# Compact banner for places that don't need the big block art (master_ai.py boot)
banner_compact() {
    local BAR="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${BC}  ${BAR}${X}"
    echo -e "${BC}    🥷  ${BW}MASTER AI${X}  ${BC}·${X}  ${BG}Vision · Voice · Web · Code${X}"
    echo -e "${BC}    HOST:${BW} $(hostname)${X}   ${BC}USER:${BW} $(whoami)${X}   ${BC}STATUS:${BG} ● ONLINE${X}"
    echo -e "${BC}  ${BAR}${X}"
}

# ── STANDALONE PREVIEW ───────────────────────────────────────
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo ""
    echo -e "${Y}  ── MASTER AI BANNER ────────────────────────────────────────${X}"
    banner_master_ai
    echo ""
    echo -e "${Y}  ── STATUS LINE ─────────────────────────────────────────────${X}"
    status_line "ONLINE"
    echo ""
    echo -e "${C}  To use in any script:${X}"
    echo -e "${C}    source ~/scripts/brand.sh${X}"
    echo -e "${C}    banner_master_ai${X}"
    echo ""
fi
