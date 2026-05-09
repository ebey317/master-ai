#!/usr/bin/env bash
# Keep master-ai + llava resident together in Ollama, then restart so the
# new rule takes effect. Safe to run twice — it rewrites the drop-in to the
# desired values. Run with:  sudo bash ~/scripts/apply_ollama_cap.sh
set -euo pipefail

CONF=/etc/systemd/system/ollama.service.d/keep-alive.conf
DROP_IN_DIR=/etc/systemd/system/ollama.service.d

mkdir -p "$DROP_IN_DIR"

cat > "$CONF" <<'EOF'
[Service]
Environment="OLLAMA_KEEP_ALIVE=30m"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
EOF

systemctl daemon-reload
systemctl restart ollama

echo
echo "done — Ollama config now contains:"
grep -E '^(Environment|\[)' "$CONF"
echo
echo "to double-check Ollama picked it up:"
echo "  systemctl show ollama -p Environment"
