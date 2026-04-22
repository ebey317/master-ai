#!/bin/bash
# S05 — Disable i915 PSR/FBC/DC to stop Skylake HD 530 silent-hang freezes
# Run with: sudo bash ~/scripts/apply_i915_safety.sh
# Idempotent — re-running won't duplicate parameters.
# Reboot is required to activate.

set -e

GRUB_FILE="/etc/default/grub"
BACKUP="/etc/default/grub.backup.$(date +%Y%m%d_%H%M%S)"
PARAMS="i915.enable_psr=0 i915.enable_fbc=0 i915.enable_dc=0"

if [ "$EUID" -ne 0 ]; then
    echo "This script needs root. Run: sudo bash $0"
    exit 1
fi

if [ ! -f "$GRUB_FILE" ]; then
    echo "ERROR: $GRUB_FILE not found. Aborting."
    exit 1
fi

echo "[1/4] Backing up $GRUB_FILE -> $BACKUP"
cp "$GRUB_FILE" "$BACKUP"

CURRENT=$(grep '^GRUB_CMDLINE_LINUX_DEFAULT=' "$GRUB_FILE" | head -1)
echo "[2/4] Current line: $CURRENT"

NEEDS_UPDATE=0
for p in $PARAMS; do
    if ! echo "$CURRENT" | grep -q "$p"; then
        NEEDS_UPDATE=1
        break
    fi
done

if [ $NEEDS_UPDATE -eq 0 ]; then
    echo "All i915 safety parameters already present. Nothing to do."
    echo "If freezes continue after a reboot, the cause is something else."
    exit 0
fi

NEW_VALUE=$(echo "$CURRENT" | sed -E 's/GRUB_CMDLINE_LINUX_DEFAULT="(.*)"/\1/')
for p in $PARAMS; do
    if ! echo "$NEW_VALUE" | grep -q "$p"; then
        NEW_VALUE="$NEW_VALUE $p"
    fi
done
NEW_VALUE=$(echo "$NEW_VALUE" | sed -E 's/^ +//; s/ +/ /g')

sed -i "s|^GRUB_CMDLINE_LINUX_DEFAULT=.*|GRUB_CMDLINE_LINUX_DEFAULT=\"$NEW_VALUE\"|" "$GRUB_FILE"

echo "[3/4] Updated line:"
grep '^GRUB_CMDLINE_LINUX_DEFAULT=' "$GRUB_FILE"

echo "[4/4] Running update-grub..."
update-grub

echo ""
echo "✅ Applied. Reboot to activate."
echo "   If something goes wrong, restore with:  sudo cp $BACKUP $GRUB_FILE && sudo update-grub"
echo ""
echo "After reboot, verify with:  cat /proc/cmdline | tr ' ' '\\n' | grep i915"
