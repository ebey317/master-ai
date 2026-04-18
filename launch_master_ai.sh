#!/bin/bash
# Launches Master AI in a persistent tmux session with supervisor loop.
# If already running, reattaches.
# If tmux session exists but engine is dead (clean exit), relaunches engine.
# Terminal can close — session stays alive.

SESSION="master-ai"

# The supervisor loop: runs master_ai.py forever, restarts on crash (non-zero exit),
# breaks cleanly on exit 0 so user's 'x' command actually quits.
SUPERVISOR='cd ~ && while true; do python3 ~/scripts/master_ai.py; EXIT=$?; if [ $EXIT -eq 0 ]; then echo "Master AI exited cleanly."; break; fi; if [ $EXIT -eq 42 ]; then echo "kick requested — restarting..."; sleep 1; continue; fi; echo "[$(date)] Master AI crashed (exit=$EXIT) — restarting in 3s..." | tee -a ~/scripts/master.crash.log; sleep 3; done'

engine_alive() { pgrep -f "python3.*master_ai.py" >/dev/null 2>&1; }

# ── Defensive: always force pane to match the terminal we're launching from ──
# Without this, a session created yesterday with different dims would persist.
# Customer should never have to manually kill tmux to get a full-screen Sensei.
tmux set-window-option -g aggressive-resize on 2>/dev/null || true
COLS=$(tput cols 2>/dev/null || echo 120)
LINES=$(tput lines 2>/dev/null || echo 40)

if tmux has-session -t "$SESSION" 2>/dev/null; then
    # Resize to match current terminal before attaching
    tmux resize-window -t "$SESSION" -x "$COLS" -y "$LINES" 2>/dev/null || true
    if engine_alive; then
        echo "Master AI already running — reattaching..."
    else
        echo "Tmux session alive but engine stopped — relaunching engine..."
        tmux send-keys -t "$SESSION" "$SUPERVISOR" Enter
        sleep 1
    fi
else
    echo "Starting Master AI persistent session..."
    # Create with current terminal dims; aggressive-resize handles later changes
    tmux new-session -d -s "$SESSION" -x "$COLS" -y "$LINES"
    tmux send-keys -t "$SESSION" "$SUPERVISOR" Enter
fi

# Switch if already inside tmux, otherwise attach
if [ -n "$TMUX" ]; then
    tmux switch-client -t "$SESSION"
else
    tmux attach-session -t "$SESSION"
fi
