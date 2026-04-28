#!/bin/bash
set -euo pipefail

DROPIN="/etc/systemd/system/ollama.service.d/keep-alive.conf"

echo "No-sudo llava keep-warm check"
echo "────────────────────────────"

if [ ! -r "$DROPIN" ]; then
  echo "Cannot read $DROPIN"
  echo "This script will not use sudo. Fix the Ollama system drop-in manually if needed."
  exit 1
fi

if grep -qx 'Environment="OLLAMA_MAX_LOADED_MODELS=2"' "$DROPIN"; then
  echo "OK: Ollama is configured to allow master-ai + llava loaded together."
else
  echo "NEEDS MANUAL FIX: $DROPIN should contain exactly:"
  echo 'Environment="OLLAMA_MAX_LOADED_MODELS=2"'
  echo
  echo "Current matching lines:"
  grep -n 'OLLAMA_MAX_LOADED_MODELS' "$DROPIN" || true
  echo
  echo "No sudo was run."
  exit 2
fi

echo "Reloading user prewarm unit only..."
systemctl --user daemon-reload
systemctl --user restart master-ai-prewarm.service
systemctl --user status master-ai-prewarm.service --no-pager
