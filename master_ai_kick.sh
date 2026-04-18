#!/bin/bash
# Force-restore Master AI from any state. Safe to run anytime.
# Use when the tmux session itself is broken or missing.

SESSION="master-ai"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Killing existing tmux session..."
    tmux kill-session -t "$SESSION"
fi

echo "Starting fresh Master AI session..."
bash ~/scripts/launch_master_ai.sh
