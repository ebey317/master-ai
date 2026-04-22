#!/bin/bash
# Saves a tight AI context snapshot to ~/Desktop/AI_CONTEXT/
# Cron: */20 * * * * bash ~/scripts/save_context.sh

DEST="$HOME/Desktop/AI_CONTEXT"
SNAP="$DEST/context_$(date '+%Y-%m-%d_%H-%M').txt"
ZIP="$DEST/context_latest.zip"
TASK_FILE="$HOME/.master_ai_active_task"

mkdir -p "$DEST"

{
echo "=== MASTER AI CONTEXT — $(date '+%Y-%m-%d %H:%M') ==="
echo ""
echo "[WHO]"
echo "Elijah | no mouse/no keyboard | voice input | light terminal (never use grey text)"
echo "Machine: Madam-Mary | Project root: ~/scripts/"
echo ""
echo "[KEY FILES — read these to know the codebase]"
echo "~/scripts/howwework.txt       — full stack + services reference"
echo "~/scripts/pupil.html          — Pupil browser UI (localhost:8080/pupil.html)"
echo "~/scripts/pc_control.sh       — terminal AI agent (arrow-key menus built in)"
echo "~/scripts/master_ai.py        — AI engine (STT/TTS/routing)"
echo "~/.master_ai_settings         — no-mouse / phone mode flags"
echo "~/.master_ai_memory           — saved AI facts (ALL apps share this)"
echo "~/.master_ai_keys             — API keys (Groq, OpenAI, OpenRouter)"
echo "~/.master_ai_chats/           — ALL chat history (web UI + PC Control + all apps)"
echo "~/Desktop/AI_CONTEXT/         — session snapshots (this file lives here)"
echo ""
echo "[RECENTLY CHANGED — last 24h]"
find "$HOME/scripts" -maxdepth 1 -name "*.sh" -o -name "*.py" -o -name "*.html" 2>/dev/null \
  | xargs ls -t 2>/dev/null \
  | head -8 \
  | while read -r f; do
      mod=$(stat -c '%y' "$f" 2>/dev/null | cut -d'.' -f1)
      echo "  $mod  ${f/#$HOME/~}"
    done
echo ""
echo "[ACTIVE TASK]"
if [ -f "$TASK_FILE" ] && [ -s "$TASK_FILE" ]; then
    cat "$TASK_FILE"
else
    echo "  none recorded — type 'task: <description>' in PC Control to set"
fi
echo ""
echo "[MEMORY FACTS]"
if [ -f "$HOME/.master_ai_memory" ] && [ -s "$HOME/.master_ai_memory" ]; then
    head -10 "$HOME/.master_ai_memory"
else
    echo "  (empty)"
fi
} > "$SNAP"

rm -f "$ZIP"
zip -j "$ZIP" "$SNAP" > /dev/null 2>&1
# Keep only last 5 snapshots
ls -t "$DEST"/context_*.txt 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null
echo "Context saved: $SNAP"
