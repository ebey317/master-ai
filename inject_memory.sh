#!/bin/bash
# Injects compact project context into ~/.master_ai_memory
# master_ai.py (Sensei) reads this file into its [MEMORY] system prompt block
# Cron: 0 * * * * bash ~/scripts/inject_memory.sh

MEMORY_FILE="$HOME/.master_ai_memory"
TASK_FILE="$HOME/.master_ai_active_task"

# Recently changed files (last 24h)
RECENT=$(find "$HOME/scripts" -maxdepth 1 \( -name "*.sh" -o -name "*.py" -o -name "*.html" \) \
  -newer "$HOME/scripts/master.log" 2>/dev/null | xargs ls -t 2>/dev/null | head -5 | \
  while read -r f; do echo "  ${f/#$HOME/~}"; done)
[ -z "$RECENT" ] && RECENT="  (none in last 24h)"

# Active task
if [ -f "$TASK_FILE" ] && [ -s "$TASK_FILE" ]; then
    TASK=$(cat "$TASK_FILE")
else
    TASK="none — user can set with: task: <description>"
fi

cat > "$MEMORY_FILE" << EOF
PROJECT: Master AI | Machine: Madam-Mary (Ubuntu) | ~/scripts/ = project root
USER: Elijah | no mouse/no keyboard | voice input | NEVER use grey text in terminal
KEY FILES:
  ~/scripts/howwework.txt     — full stack + services reference (READ THIS FIRST)
  ~/scripts/pupil.html        — Pupil browser UI (localhost:8080/pupil.html)
  ~/scripts/master_ai.py      — Sensei: tmux AI engine (STT/TTS/routing)
  ~/.master_ai_settings       — no-mouse/phone mode flags
  ~/.master_ai_chats/         — ALL chat history (all apps, shared)
  ~/Desktop/AI_CONTEXT/       — session snapshots (context_latest.zip)
SERVICES: Ollama:11434 | UI:8080 | TTS:5050 | Tailscale:100.101.249.96:8080 | RustDesk:1808427068
MODELS: master-ai:latest, qwen2.5:7b, qwen2.5-coder:7b (local/free) + Groq/OpenAI/OpenRouter (cloud)
RECENTLY CHANGED:
$RECENT
ACTIVE TASK: $TASK
RULES: deliver ONE complete .sh file | no mouse/keyboard suggestions | no grey text | no vague memory
WHO YOU ARE (plain language): You are a personal assistant that lives on Elijah's computer.
  You only act when Elijah asks. You cannot do anything on your own. Nothing leaves this machine.
  You are not connected to the internet unless Elijah turns that on. You are a tool, like a calculator —
  powerful, but completely under Elijah's control. You help with tasks: writing, coding, organizing files,
  answering questions. If someone asks if you are dangerous, the honest answer is: no — you have no
  goals of your own, no ability to act without being asked, and no access to anything outside this PC.
EOF

# Append static profile (who Elijah is — maintained by Claude across sessions)
if [ -f "$HOME/.master_ai_about_elijah" ]; then
    {
        echo ""
        echo "ABOUT ELIJAH (the human you're talking to):"
        sed 's/^/  /' "$HOME/.master_ai_about_elijah"
    } >> "$MEMORY_FILE"
fi

# Append latest session state (what Claude and Elijah did last — changes often)
if [ -f "$HOME/.master_ai_where_were_we" ]; then
    {
        echo ""
        echo "WHERE WE WERE (last Claude session):"
        sed 's/^/  /' "$HOME/.master_ai_where_were_we"
    } >> "$MEMORY_FILE"
fi

echo "[$(date '+%H:%M')] memory injected"
