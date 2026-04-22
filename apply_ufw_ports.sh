#!/usr/bin/env bash
# Open LAN ports for Master AI services (Pupil :8080, TTS :5050, Ollama
# :11434) in ufw. Only acts if ufw is already active — does NOT turn the
# firewall on for you. Safe to run twice — ufw dedupes rules with the
# same spec. Run with:
#   sudo bash ~/scripts/apply_ufw_ports.sh
set -euo pipefail

# Check if ufw exists at all.
if ! command -v ufw >/dev/null 2>&1; then
    echo "ufw is not installed on this machine — nothing to do."
    echo "if you want a firewall, install it with:  sudo apt install ufw"
    exit 0
fi

# Check if ufw is active. Use an exact match on "Status: active" so we
# don't false-match "Status: inactive" (the substring "active" lives
# inside "inactive" and a sloppy grep would match both).
status=$(ufw status 2>/dev/null | head -1 || true)
if ! echo "$status" | grep -qE '^Status: active$'; then
    echo "ufw is installed but not active — nothing to open."
    echo "current status: $status"
    echo
    echo "if you want to turn ufw on (careful — this WILL block traffic by"
    echo "default; make sure you allow ssh first if you're remote):"
    echo "  sudo ufw allow ssh"
    echo "  sudo ufw enable"
    exit 0
fi

echo "ufw is active — adding rules for Master AI's LAN ports."
echo

# Each `ufw allow` with --comment is idempotent — running it twice doesn't
# create duplicate rules, ufw recognizes the match.
ufw allow 8080/tcp  comment 'Master AI Pupil (browser UI)'
ufw allow 5050/tcp  comment 'Master AI TTS (Piper voice)'
ufw allow 11434/tcp comment 'Master AI Ollama (LAN only — do not use on public networks)'

echo
echo "done — current rules:"
ufw status numbered | grep -E '(8080|5050|11434)' || ufw status numbered
echo
echo "what this means: other devices on your local network (phone via"
echo "Tailscale, other PCs) can now reach Pupil in a browser at"
echo "http://<this-machine-ip>:8080, hear TTS at :5050, and talk to Ollama"
echo "at :11434. Port 11434 (Ollama) stays LAN-only — never expose it to"
echo "the public internet; it has no auth."
