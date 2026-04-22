#!/usr/bin/env bash
# Add "only one brain awake at a time" to Ollama's config, then restart
# Ollama so it picks up the new rule. Safe to run twice — won't duplicate
# the line. Run with:  sudo bash ~/scripts/apply_ollama_cap.sh
set -euo pipefail

CONF=/etc/systemd/system/ollama.service.d/keep-alive.conf
DROP_IN_DIR=/etc/systemd/system/ollama.service.d

# Make sure the drop-in directory exists (it should — created in v1.7 session —
# but defensive check so the script works on a fresh install too).
mkdir -p "$DROP_IN_DIR"

# Make sure the conf file has a [Service] header so new Environment lines
# are read by systemd. If the file is empty or missing, start it clean.
if [ ! -s "$CONF" ]; then
    {
        echo "[Service]"
        echo 'Environment="OLLAMA_KEEP_ALIVE=30m"'
    } > "$CONF"
elif ! grep -q '^\[Service\]' "$CONF"; then
    tmpf="$(mktemp)"
    {
        echo "[Service]"
        cat "$CONF"
    } > "$tmpf"
    mv "$tmpf" "$CONF"
fi

# Add the RAM cap if it isn't there yet.
if grep -q OLLAMA_MAX_LOADED_MODELS "$CONF"; then
    echo "already set — skipping append"
else
    echo 'Environment="OLLAMA_MAX_LOADED_MODELS=1"' >> "$CONF"
    echo "added OLLAMA_MAX_LOADED_MODELS=1"
fi

systemctl daemon-reload
systemctl restart ollama

echo
echo "done — Ollama config now contains:"
grep -E '^(Environment|\[)' "$CONF"
echo
echo "to double-check Ollama picked it up:"
echo "  systemctl show ollama -p Environment"
