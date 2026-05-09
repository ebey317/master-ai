#!/bin/bash
# ============================================================
# PRE-UPGRADE BACKUP — Master AI
# Run before swapping RAM or replacing your NVMe drive.
#
# Creates a single tarball with EVERYTHING you'd need to restore
# Master AI + your personal data on a fresh Ubuntu install.
# Also prints a step-by-step Clonezilla plan for a full-drive
# clone if you want to boot the new drive as-is.
#
# Usage:  bash ~/scripts/pre_upgrade_backup.sh [external-mount-path]
#         Default path: ~/Downloads (change to /media/... for USB drive)
# ============================================================

set -u
source ~/scripts/brand.sh 2>/dev/null || true
: "${BC:=$(tput bold 2>/dev/null; tput setaf 4 2>/dev/null)}"
: "${BG:=$(tput bold 2>/dev/null; tput setaf 2 2>/dev/null)}"
: "${BY:=$(tput bold 2>/dev/null; tput setaf 3 2>/dev/null)}"
: "${BR:=$(tput bold 2>/dev/null; tput setaf 1 2>/dev/null)}"
: "${BW:=$(tput bold 2>/dev/null; tput setaf 0 2>/dev/null)}"
: "${D:=$(tput setaf 8 2>/dev/null)}"
: "${X:=$(tput sgr0 2>/dev/null)}"

OUTDIR="${1:-$HOME/Downloads}"
STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$OUTDIR/master-ai-backup-$STAMP"
TARBALL="$OUTDIR/master-ai-backup-$STAMP.tar.gz"
LOG="$BACKUP_DIR/backup.log"

echo ""
echo -e "  ${BC}╔══════════════════════════════════════════════════════╗${X}"
echo -e "  ${BC}║${X}  ${BW}🥷  PRE-UPGRADE BACKUP${X}                             ${BC}║${X}"
echo -e "  ${BC}║${X}  ${D}Before RAM / NVMe swap${X}                             ${BC}║${X}"
echo -e "  ${BC}╚══════════════════════════════════════════════════════╝${X}"
echo ""
echo -e "  ${BW}Target:${X} $OUTDIR"
echo -e "  ${BW}Bundle:${X} master-ai-backup-$STAMP.tar.gz"
echo ""

# Sanity checks
if [ ! -d "$OUTDIR" ]; then
    echo -e "  ${BR}❌ target folder doesn't exist: $OUTDIR${X}"
    exit 1
fi
FREE_GB=$(df -BG "$OUTDIR" | awk 'NR==2 {gsub("G","",$4); print $4}')
NEEDED_GB=10
if [ "$FREE_GB" -lt "$NEEDED_GB" ]; then
    echo -e "  ${BR}⚠ only $FREE_GB GB free at $OUTDIR (need ~$NEEDED_GB). Consider an external drive.${X}"
    read -rp "  continue anyway? (y/N) " a
    [[ ! "$a" =~ ^[yY] ]] && exit 1
fi

mkdir -p "$BACKUP_DIR"
: > "$LOG"
log() { echo "[$(date '+%I:%M:%S %p')] $1" | tee -a "$LOG"; }

# ── 1. Personal Master AI state ──────────────────────────────
log "=== 1. Master AI personal state ==="
mkdir -p "$BACKUP_DIR/home"
for f in \
    ~/.master_ai_keys \
    ~/.master_ai_memory \
    ~/.master_ai_tasks \
    ~/.master_ai_settings \
    ~/.master_ai_approved \
    ~/.master_ai_permissions_done \
    ~/.master_ai_history \
    ~/.master_ai_tutorial_done \
    ~/.master_ai_thread \
    ~/.master_ai_active_profile \
    ~/.master_ai_active_project \
    ~/.master_ai_active_task \
    ~/.master_ai_active_model \
    ~/.dojo_gate_sealed \
    ~/.sensei_behavior.md \
    ~/.master_ai_resume
do
    [ -e "$f" ] && cp -a "$f" "$BACKUP_DIR/home/" 2>/dev/null && log "  ✓ $(basename "$f")"
done

# Directories
for d in \
    ~/.master_ai_chats \
    ~/.master_ai_profiles \
    ~/.master_ai_briefings \
    ~/.master_ai_approved_components
do
    [ -d "$d" ] && cp -a "$d" "$BACKUP_DIR/home/" 2>/dev/null && log "  ✓ $(basename "$d")/ ($(du -sh "$d" | awk '{print $1}'))"
done

# ── 2. Scripts + project ──────────────────────────────────────
log "=== 2. ~/scripts (entire Master AI codebase) ==="
rsync -a --exclude='.git' --exclude='*.log' --exclude='sessions/*.log' \
      ~/scripts/ "$BACKUP_DIR/scripts/" 2>/dev/null
log "  ✓ scripts ($(du -sh "$BACKUP_DIR/scripts" | awk '{print $1}'))"

# ── 3. Systemd user units ────────────────────────────────────
log "=== 3. Systemd user services ==="
if [ -d ~/.config/systemd/user ]; then
    cp -a ~/.config/systemd/user "$BACKUP_DIR/systemd-user" 2>/dev/null
    log "  ✓ ~/.config/systemd/user/"
    systemctl --user list-unit-files --state=enabled --no-pager > "$BACKUP_DIR/systemd-enabled.txt" 2>/dev/null
fi

# ── 4. Cloud desktop bits (claude CLI, etc.) ──────────────────
log "=== 4. Claude CLI + other AI tools ==="
for d in ~/.claude ~/.config/claude-code ~/.anthropic; do
    [ -d "$d" ] && cp -a "$d" "$BACKUP_DIR/" 2>/dev/null && log "  ✓ $(basename "$d")/"
done

# ── 5. SSH keys + .bashrc / .profile ──────────────────────────
log "=== 5. Dotfiles ==="
[ -d ~/.ssh ] && cp -a ~/.ssh "$BACKUP_DIR/" 2>/dev/null && chmod 700 "$BACKUP_DIR/.ssh" && log "  ✓ .ssh/"
for f in ~/.bashrc ~/.bash_aliases ~/.bash_profile ~/.profile ~/.zshrc ~/.gitconfig ~/.vimrc; do
    [ -f "$f" ] && cp -a "$f" "$BACKUP_DIR/" 2>/dev/null && log "  ✓ $(basename "$f")"
done

# ── 6. Ollama models manifest (names + versions, NOT blobs) ──
log "=== 6. Ollama manifest (list of pulled models) ==="
ollama list > "$BACKUP_DIR/ollama-models.txt" 2>/dev/null && log "  ✓ ollama list saved"
echo "# Restore with: xargs -L1 ollama pull < ollama-models.txt" > "$BACKUP_DIR/ollama-restore.sh"
ollama list 2>/dev/null | awk 'NR>1 && $1 !~ /:cloud$/ {print $1}' >> "$BACKUP_DIR/ollama-restore.sh"
chmod +x "$BACKUP_DIR/ollama-restore.sh"

# ── 7. Installed apt packages ────────────────────────────────
log "=== 7. Installed apt packages ==="
dpkg --get-selections > "$BACKUP_DIR/apt-installed.txt" 2>/dev/null
log "  ✓ $(wc -l < "$BACKUP_DIR/apt-installed.txt") packages listed"

# ── 8. System info snapshot ──────────────────────────────────
log "=== 8. System snapshot (for reference) ==="
{
    echo "=== OS ==="; cat /etc/os-release
    echo ""; echo "=== KERNEL ==="; uname -a
    echo ""; echo "=== CPU ==="; lscpu | head -12
    echo ""; echo "=== MEM ==="; free -h
    echo ""; echo "=== DISK ==="; df -h
    echo ""; echo "=== BLOCK ==="; lsblk
    echo ""; echo "=== PARTUUID ==="; blkid 2>/dev/null || sudo -n blkid 2>/dev/null
} > "$BACKUP_DIR/system-snapshot.txt"
log "  ✓ system snapshot"

# ── 9. Firefox profile (optional — sessions, cookies) ────────
log "=== 9. Firefox profile (sessions, tabs, history) ==="
if [ -d ~/.mozilla/firefox ]; then
    FF_SIZE=$(du -sh ~/.mozilla/firefox 2>/dev/null | awk '{print $1}')
    echo -e "  ${BW}Firefox profile is $FF_SIZE — include it? (y/N)${X}"
    read -rp "  " ff
    if [[ "$ff" =~ ^[yY] ]]; then
        cp -a ~/.mozilla/firefox "$BACKUP_DIR/" 2>/dev/null
        log "  ✓ firefox profile ($FF_SIZE)"
    else
        log "  ⊘ firefox profile skipped"
    fi
fi

# ── 10. Compress everything into a single restorable tarball ──
log "=== 10. Packaging into tarball ==="
cd "$OUTDIR"
tar czf "$(basename "$TARBALL")" "$(basename "$BACKUP_DIR")" 2>/dev/null
TAR_SIZE=$(du -sh "$TARBALL" | awk '{print $1}')
log "  ✓ $TARBALL ($TAR_SIZE)"

# Leave the expanded dir for inspection, tarball for portability
echo ""
echo -e "  ${BC}╔══════════════════════════════════════════════════════╗${X}"
echo -e "  ${BC}║${X}  ${BG}🥷  BACKUP COMPLETE${X}                                 ${BC}║${X}"
echo -e "  ${BC}╚══════════════════════════════════════════════════════╝${X}"
echo ""
echo -e "  ${BW}Tarball:${X}  $TARBALL"
echo -e "  ${BW}Size:${X}     $TAR_SIZE"
echo -e "  ${BW}Folder:${X}   $BACKUP_DIR (expanded — delete after verifying)"
echo ""
echo -e "  ${BW}BEFORE OPENING YOUR MACHINE:${X}"
echo -e "    ${BG}1)${X} Copy $TARBALL to an EXTERNAL drive (USB stick, another PC, cloud)"
echo -e "    ${BG}2)${X} Verify you can un-tar it somewhere else — don't trust a backup you haven't tested"
echo -e "    ${BG}3)${X} Keep the old NVMe physically until the new one is proven working"
echo ""

# ── 11. Clonezilla plan for full-drive clone ─────────────────
cat <<'EOF' > "$BACKUP_DIR/CLONEZILLA_INSTRUCTIONS.md"
# Full-drive clone to the new 4TB NVMe (fastest migration path)

If you want the new drive to boot exactly like the old one — no reinstall
needed — use Clonezilla. This is the preferred path.

## What you need
- A USB stick (4+ GB)
- Clonezilla Live AMD64 ISO: https://clonezilla.org/downloads.php
- An M.2-to-USB NVMe enclosure (~$25 on Amazon) — lets you clone to the new
  4TB BEFORE opening your HP ProDesk, so you just swap drives at the end

## Steps
1. Flash Clonezilla ISO to the USB stick with `dd`:
   `sudo dd if=clonezilla-live-*-amd64.iso of=/dev/sdX bs=4M status=progress && sync`
2. Plug the new 4TB NVMe into the M.2-USB enclosure → plug that into a free USB
   port on this machine.
3. Reboot → spam F9 (HP boot menu) → pick the Clonezilla USB.
4. In Clonezilla: `device-device` → `beginner` → `disk_to_local_disk`
5. Source = old internal NVMe (~238 GB). Target = new 4TB (via USB).
6. Let it copy (~30-60 min depending on how full the source is).
7. After clone, shutdown, open the HP, swap the internal NVMe for the 4TB, boot.
8. Ubuntu expands its root partition to fill the new 4TB:
     `sudo gparted /dev/nvme0n1`  → resize root partition → apply

## If the clone won't boot
Grub sometimes gets grumpy with UUID changes:
  1. Boot from an Ubuntu live USB
  2. `sudo mount /dev/nvme0n1p5 /mnt` (your root)
  3. `sudo mount /dev/nvme0n1p1 /mnt/boot/efi` (EFI)
  4. For i in /dev /proc /sys /run; do sudo mount --bind $i /mnt$i; done
  5. `sudo chroot /mnt`
  6. `update-grub && grub-install /dev/nvme0n1`
  7. Exit, reboot, you're good.
EOF

echo -e "  ${BW}Full-drive clone (Clonezilla) instructions written to:${X}"
echo -e "    ${C}$BACKUP_DIR/CLONEZILLA_INSTRUCTIONS.md${X}"
echo ""
echo -e "  ${BW}RAM upgrade:${X}"
echo -e "    ${D}· Safe to do any time — just power off, swap sticks, power on.${X}"
echo -e "    ${D}· First boot after RAM change, BIOS may train for 30-60 seconds.${X}"
echo ""
