#!/bin/bash
# Make Ollama listen on all interfaces (needed for Tailscale access)
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
Environment="OLLAMA_ORIGINS=*"
EOF
systemctl daemon-reload
systemctl restart ollama
sleep 2
curl -s http://100.101.249.96:11434/api/tags > /dev/null && echo "✅ Ollama now accessible on Tailscale (100.101.249.96:11434)" || echo "❌ Still not reachable"
