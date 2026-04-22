#!/usr/bin/env bash
# S04 — install earlyoom + tune swappiness so hard freezes stop
#
# Why this exists: on 15 GB RAM with no OOM watchdog, memory pressure can
# thrash swap so hard the kernel locks up before its own OOM killer fires.
# earlyoom watches RAM+swap continuously and kills the biggest process
# pre-emptively. Result: one process dies instead of the whole machine.
#
# Paste this ONE LINE (no $ prefix, no quotes around it):
#     sudo bash ~/scripts/apply_earlyoom.sh
#
# Idempotent. Safe to re-run. No sudo lines inside (the script runs UNDER sudo).

set -e

echo "=== S04: earlyoom + swappiness tune ==="
echo

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run this with  sudo bash $0"
  exit 1
fi

echo "[1/5] apt update (quiet)..."
apt-get update -qq

echo "[2/5] install earlyoom..."
DEBIAN_FRONTEND=noninteractive apt-get install -y earlyoom

echo "[3/5] configure earlyoom thresholds..."
# -m 10 -s 10  =  kill biggest process when free mem AND swap both below 10%
# -r 60        =  report every 60s to journal
# -n           =  notify via d-bus when killing
mkdir -p /etc/default
cat > /etc/default/earlyoom <<'EOF'
# Master AI / Sensei freeze-prevention config (S04)
# Kill biggest process when BOTH free mem and swap drop under 10%.
EARLYOOM_ARGS="-m 10 -s 10 -r 60 -n --avoid '(^|/)(init|systemd|Xorg|sshd|tailscaled|cinnamon|mate-session|gnome-shell)$' --prefer '(^|/)(ollama|python|chrome|firefox|node)$'"
EOF

echo "[4/5] enable + restart earlyoom..."
systemctl enable earlyoom >/dev/null 2>&1
systemctl restart earlyoom
sleep 1
systemctl is-active earlyoom && echo "  earlyoom is ACTIVE"

echo "[5/5] tune swappiness 60 -> 10 (prefer RAM, swap only when truly needed)..."
mkdir -p /etc/sysctl.d
cat > /etc/sysctl.d/99-master-ai-swappiness.conf <<'EOF'
# Master AI: favor RAM over swap so low-memory box doesn't thrash
vm.swappiness=10
vm.vfs_cache_pressure=50
EOF
sysctl -p /etc/sysctl.d/99-master-ai-swappiness.conf

echo
echo "=== DONE ==="
echo "  earlyoom: $(systemctl is-active earlyoom)"
echo "  swappiness: $(cat /proc/sys/vm/swappiness)"
echo
echo "Next freeze test: this machine should no longer hard-lock under load."
echo "If memory still spikes, earlyoom will kill the biggest offender (usually Ollama or Chrome)"
echo "and you'll see it in 'journalctl -u earlyoom'."
