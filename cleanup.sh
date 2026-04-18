#!/bin/bash
# ============================================
# SYSTEM CLEANUP — HP ProDesk
# Removes unused Ollama models, stale cache,
# and old Downloads clutter to stop freezes.
# Run: bash ~/scripts/cleanup.sh
# ============================================

LOG="$HOME/scripts/master.log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"; }

echo "╔══════════════════════════════════════════╗"
echo "║          SYSTEM CLEANUP                  ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. REMOVE UNUSED OLLAMA MODELS ──────────────
echo "[ 1/4 ] Removing unused Ollama models..."
log "--- Ollama model cleanup ---"

UNUSED_MODELS=("llava:latest" "phi3:mini" "llama3:latest")

for MODEL in "${UNUSED_MODELS[@]}"; do
    if ollama list 2>/dev/null | grep -q "^$MODEL"; then
        echo "  Removing $MODEL ..."
        ollama rm "$MODEL" && log "Removed model: $MODEL" || log "Failed to remove: $MODEL"
    else
        echo "  $MODEL not found, skipping."
    fi
done
echo "✅ Ollama cleanup done."
echo ""

# ── 2. CLEAR PIP CACHE ──────────────────────────
echo "[ 2/4 ] Clearing pip cache (2.7 GB)..."
log "--- pip cache cleanup ---"
pip cache purge 2>/dev/null && log "pip cache cleared" || rm -rf ~/.cache/pip && log "pip cache removed manually"
echo "✅ pip cache cleared."
echo ""

# ── 3. CLEAR BROWSER CACHES ─────────────────────
echo "[ 3/4 ] Clearing browser caches..."
log "--- browser cache cleanup ---"
rm -rf ~/.cache/mozilla/firefox/*/cache2
rm -rf ~/.cache/chromium/Default/Cache
log "Browser caches cleared"
echo "✅ Browser caches cleared."
echo ""

# ── 4. CLEAN OLD DOWNLOADS CLUTTER ──────────────
echo "[ 4/4 ] Removing old installer scripts and zip files from Downloads..."
log "--- Downloads cleanup ---"

# Old zip files (not sunkissed-soul-sync which may still be needed)
OLD_ZIPS=(
    "$HOME/Downloads/files.zip"
    "$HOME/Downloads/files(1).zip"
    "$HOME/Downloads/files(5).zip"
    "$HOME/Downloads/files(6).zip"
    "$HOME/Downloads/files(7).zip"
    "$HOME/Downloads/files(8).zip"
    "$HOME/Downloads/find-just-zen-flow.zip"
    "$HOME/Downloads/master-ai-final-backup.zip"
)

# Old installer/patch scripts (already applied)
OLD_SCRIPTS=(
    "$HOME/Downloads/fix_cors_and_restart.sh"
    "$HOME/Downloads/fix_master_aiant.sh"
    "$HOME/Downloads/hard_recovery.sh"
    "$HOME/Downloads/inject_key.sh"
    "$HOME/Downloads/install.sh"
    "$HOME/Downloads/install(1).sh"
    "$HOME/Downloads/install(2).sh"
    "$HOME/Downloads/install_desktop.sh"
    "$HOME/Downloads/install_howwework.sh"
    "$HOME/Downloads/install-master-ai.sh"
    "$HOME/Downloads/install_sks.sh"
    "$HOME/Downloads/master-ai-installer.sh"
    "$HOME/Downloads/master-ai-quick-start.sh"
    "$HOME/Downloads/nuke_gemini.sh"
    "$HOME/Downloads/patch_enhanced.sh"
    "$HOME/Downloads/patch_master-ai.sh"
    "$HOME/Downloads/prove_connection.sh"
    "$HOME/Downloads/restore_local_ai.sh"
    "$HOME/Downloads/restore_master.sh"
    "$HOME/Downloads/revert_changes.sh"
    "$HOME/Downloads/setup_keys.sh"
    "$HOME/Downloads/setup_keys(1).sh"
    "$HOME/Downloads/master-ai-complete.sh"
    "$HOME/Downloads/master-ai-terminal.sh"
    "$HOME/Downloads/rustdesk-1.2.7-x86_64.deb"
)

for F in "${OLD_ZIPS[@]}" "${OLD_SCRIPTS[@]}"; do
    if [ -f "$F" ]; then
        rm "$F" && echo "  Removed: $(basename $F)"
    fi
done

log "Downloads cleanup done"
echo "✅ Downloads cleaned."
echo ""

# ── SUMMARY ─────────────────────────────────────
echo "╔══════════════════════════════════════════╗"
echo "║           CLEANUP COMPLETE               ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Disk usage now:"
df -h / | tail -1
echo ""
echo "Remaining Ollama models:"
ollama list 2>/dev/null
echo ""
log "=== CLEANUP COMPLETE ==="
echo ""
echo "💡 TIP: Reboot after cleanup to free RAM fully."
