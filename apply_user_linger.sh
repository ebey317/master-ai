#!/usr/bin/env bash
# Enable systemd user lingering for elijah so Sensei + Pupil + TTS user
# services keep running after logout. Safe to run twice — flips a bit
# that's either on or off. Run with:
#   sudo bash ~/scripts/apply_user_linger.sh
set -euo pipefail

USER_NAME=elijah

# Check current state — no change needed if already on.
current=$(loginctl show-user "$USER_NAME" 2>/dev/null | grep -E '^Linger=' | cut -d= -f2 || echo "unknown")

if [ "$current" = "yes" ]; then
    echo "already on — Linger=yes for $USER_NAME"
else
    loginctl enable-linger "$USER_NAME"
    echo "turned on — Linger now enabled for $USER_NAME"
fi

echo
echo "final state:"
loginctl show-user "$USER_NAME" | grep -E '^Linger=' || echo "(no Linger line — something went wrong)"
echo
echo "what this means: your user services (stt_server on :8080, tts_server"
echo "on :5050, etc.) will now keep running after you log out. Sensei in tmux"
echo "will also survive as long as tmux is detached."
