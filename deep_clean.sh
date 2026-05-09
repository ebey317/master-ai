#!/bin/bash
# ============================================
# Master AI — BIWEEKLY DEEP CLEAN
# Scheduled: Thursdays 04:30–06:00 America/Indiana/Indianapolis,
# every other week. Computer-idle gated (not human-idle — runs
# while Elijah is away at work).
#
# Triggered by: master-ai-deep-clean.timer (systemd user)
# Called: master-ai-deep-clean.service
#
# What it does:
#   1. Time-window gate   — bail if outside Thu 04:30–06:00 local
#   2. Biweekly gate      — bail if the last run was <13 days ago
#   3. Idle gate          — bail if load avg > 0.8 (computer busy)
#   4. Bug check          — syntax-check every .py/.sh in ~/scripts
#   5. File clean         — invoke cleanup.sh (pip/browser cache, Downloads)
#   6. Session archive    — gzip session files older than 30 days
#   7. Ollama audit       — list pulled models, flag any not in trifecta
#   8. Report             — write markdown to ~/Desktop/master_ai_cleanups/
#   9. Stamp              — update ~/.master_ai_last_deep_clean for (2)
# ============================================
set -u

STAMP_FILE="$HOME/.master_ai_last_deep_clean"
REPORT_DIR="$HOME/Desktop/master_ai_cleanups"
LOG="$HOME/scripts/master.log"
DATE_SLUG=$(date +%Y-%m-%d_%H%M)
REPORT="$REPORT_DIR/deep_clean_${DATE_SLUG}.md"

mkdir -p "$REPORT_DIR"
log() { echo "[$(date '+%Y-%m-%d %I:%M:%S %p')] $1" | tee -a "$LOG"; }
report() { echo "$1" | tee -a "$REPORT"; }

# ── 1. Time-window gate ───────────────────────────────────────
dow=$(date +%u)          # 1=Mon..7=Sun
hhmm=$(date +%H%M)
if [ "$dow" != "4" ]; then
    log "DEEP_CLEAN: skipping — not Thursday (dow=$dow)"
    exit 0
fi
if [ "$hhmm" -lt "0430" ] || [ "$hhmm" -gt "0600" ]; then
    log "DEEP_CLEAN: skipping — outside 04:30-06:00 window (hhmm=$hhmm)"
    exit 0
fi

# ── 2. Biweekly gate ──────────────────────────────────────────
if [ -f "$STAMP_FILE" ]; then
    last_epoch=$(stat -c %Y "$STAMP_FILE" 2>/dev/null || echo 0)
    now_epoch=$(date +%s)
    days_since=$(( (now_epoch - last_epoch) / 86400 ))
    if [ "$days_since" -lt 13 ]; then
        log "DEEP_CLEAN: skipping — last run was $days_since days ago (need >=13 for biweekly)"
        exit 0
    fi
fi

# ── 3. Computer-idle gate ─────────────────────────────────────
# Load avg over the last minute. On a 4-core i7-6700T, <0.8 means
# mostly idle. Ollama during inference pushes load way above this.
load1=$(awk '{print $1}' /proc/loadavg)
load_int=$(awk -v l="$load1" 'BEGIN {printf "%d", l*100}')
if [ "$load_int" -gt 80 ]; then
    log "DEEP_CLEAN: skipping — load avg $load1 > 0.80 (computer busy)"
    exit 0
fi

# Also skip if Ollama is actively serving a request
if pgrep -f "ollama runner" >/dev/null 2>&1; then
    log "DEEP_CLEAN: skipping — Ollama inference running"
    exit 0
fi

# ── Begin deep clean ──────────────────────────────────────────
log "DEEP_CLEAN: START (load=$load1, disk=$(df -h "$HOME" | awk 'NR==2 {print $4}') free)"
report "# Master AI — Deep Clean Report"
report ""
report "**Run:** $(date '+%A, %B %d %Y · %I:%M %p %Z')"
report "**Host:** $(hostname)"
report "**Load avg (1min):** $load1"
report "**Disk free ($HOME):** $(df -h "$HOME" | awk 'NR==2 {print $4}')"
report ""

# ── 4. Bug check — syntax-scan every .py and .sh in ~/scripts
report "## 1. Bug check (syntax scan)"
report ""
py_errors=0
sh_errors=0
py_files=0
sh_files=0
while IFS= read -r -d '' f; do
    py_files=$((py_files + 1))
    if ! python3 -c "import ast; ast.parse(open('$f').read())" 2>/dev/null; then
        report "- ❌ **$f** — Python syntax error"
        py_errors=$((py_errors + 1))
    fi
done < <(find "$HOME/scripts" -maxdepth 2 -name "*.py" -print0 2>/dev/null)

while IFS= read -r -d '' f; do
    sh_files=$((sh_files + 1))
    if ! bash -n "$f" 2>/dev/null; then
        report "- ❌ **$f** — Bash syntax error"
        sh_errors=$((sh_errors + 1))
    fi
done < <(find "$HOME/scripts" -maxdepth 2 -name "*.sh" -print0 2>/dev/null)

if [ "$py_errors" = "0" ] && [ "$sh_errors" = "0" ]; then
    report "✅ No syntax errors. Scanned $py_files Python files + $sh_files Bash files."
else
    report ""
    report "❌ Found $py_errors Python error(s) + $sh_errors Bash error(s) of $((py_files + sh_files)) total files."
fi
report ""

# ── 5. File clean — delegate to cleanup.sh
report "## 2. File clean (cleanup.sh)"
report ""
if [ -x "$HOME/scripts/cleanup.sh" ]; then
    if bash "$HOME/scripts/cleanup.sh" >>"$REPORT" 2>&1; then
        report ""
        report "✅ cleanup.sh completed."
    else
        report ""
        report "⚠ cleanup.sh exited non-zero. Check $LOG for details."
    fi
else
    report "⚠ ~/scripts/cleanup.sh not executable — skipped."
fi
report ""

# ── 6. Session archive — gzip session files older than 30 days
report "## 3. Session archive"
report ""
archived=0
if [ -d "$HOME/scripts/sessions" ]; then
    while IFS= read -r -d '' f; do
        gzip -f "$f" 2>/dev/null && archived=$((archived + 1))
    done < <(find "$HOME/scripts/sessions" -maxdepth 1 -type f \( -name "*.md" -o -name "*.txt" -o -name "*.json" \) -mtime +30 -print0 2>/dev/null)
fi
report "Archived $archived session files older than 30 days (gzip in place)."
report ""

# ── 7. Ollama audit — list models, flag non-trifecta
report "## 4. Ollama model audit"
report ""
if command -v ollama >/dev/null 2>&1; then
    models=$(ollama list 2>/dev/null | awk 'NR>1 {print $1, $3, $4}')
    if [ -n "$models" ]; then
        report '```'
        echo "$models" | tee -a "$REPORT"
        report '```'
        report ""
        # Flag models NOT in the locked trifecta (3b / 7b / llava)
        TRIFECTA_PATTERN='^(qwen2\.5:3b|qwen2\.5:7b|llava(:latest)?)( |$)'
        non_trifecta=$(echo "$models" | awk '{print $1}' | grep -Ev "$TRIFECTA_PATTERN" || true)
        if [ -n "$non_trifecta" ]; then
            report "⚠ Non-trifecta models pulled (memory + disk cost):"
            echo "$non_trifecta" | sed 's/^/- /' | tee -a "$REPORT"
            report ""
            report "(Run \`ollama rm <model>\` to free space if unused. Elijah decides — no auto-delete.)"
        else
            report "✅ Only trifecta models pulled (3b + 7b + llava)."
        fi
    else
        report "⚠ \`ollama list\` returned nothing."
    fi
else
    report "⚠ ollama not installed."
fi
report ""

# ── 8. Summary + stamp
report "## 5. Summary"
report ""
report "- Next biweekly run: ~$(date -d '+14 days' '+%A, %B %d')"
report "- Disk free ($HOME) after clean: $(df -h "$HOME" | awk 'NR==2 {print $4}')"
report "- Full log: $LOG"
report ""
report "_Generated by ~/scripts/deep_clean.sh_"

touch "$STAMP_FILE"
log "DEEP_CLEAN: DONE (report: $REPORT)"
exit 0
