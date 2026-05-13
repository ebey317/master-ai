#!/usr/bin/env bash
# Master AI state backup — disaster recovery for a stolen / damaged device.
#
# Pushes non-code state to a PRIVATE GitHub repo (ebey317/master-ai-state-backup).
# Run on a cron schedule. SECRETS (~/.master_ai_keys, ~/.master_ai_extension_token)
# are explicitly excluded via the .gitignore inside the backup repo + a hard
# rsync exclude list below. If you add new secret files, extend BOTH places.
#
# Source paths backed up:
#   ~/MD/                              — shared markdown handoff dir (Claude+Codex)
#   ~/.claude/projects/-home-elijah/memory/  — Claude's memory index + memory files
#   ~/.master_ai_chats/                — chat history (all surfaces share this)
#   ~/.master_ai_harvest.jsonl         — few-shot training data (irreplaceable)
#   ~/.master_ai_audit_typed.jsonl     — behavioral action audit
#   ~/.master_ai_memory                — saved facts
#   ~/Desktop/master_ai_project_notes.md (if present)
#
# Run manually:  bash ~/scripts/backup_state.sh
# Cron entry:    0 */6 * * * bash ~/scripts/backup_state.sh >> ~/.master_ai_backup.log 2>&1

set -u  # don't 'set -e' — we want to keep going if one source path is missing

BACKUP_DIR="$HOME/master-ai-state-backup"
LOG_PREFIX="[backup_state $(date -Iseconds)]"

if [ ! -d "$BACKUP_DIR/.git" ]; then
  echo "$LOG_PREFIX FATAL: $BACKUP_DIR is not a git repo. Run 'git init' + 'git remote add origin <url>' first."
  exit 2
fi

cd "$BACKUP_DIR" || exit 2

# .gitignore in the backup repo. Hard-exclude any path that could contain secrets,
# even if rsync accidentally copies them. Belt + suspenders.
cat > .gitignore <<'GITIGNORE'
# Secrets — never backup to ANY repo
master_ai_keys
master_ai_extension_token
*.key
*.pem
*_token
*_secret
# Local-only state
.master_ai_backup.lock
GITIGNORE

# Sources to mirror. rsync --delete drops files that no longer exist on source.
# Exclude lists prevent secret leakage even if a source dir picks up a sensitive file.
RSYNC_EXCLUDES=(
  --exclude='*.key'
  --exclude='*.pem'
  --exclude='*_token*'
  --exclude='*_secret*'
  --exclude='.git'
  --exclude='__pycache__'
)

# ── MD/ (shared Claude+Codex markdown) ──────────────────────────────
if [ -d "$HOME/MD" ]; then
  mkdir -p MD
  rsync -a --delete "${RSYNC_EXCLUDES[@]}" "$HOME/MD/" MD/
fi

# ── Memory dir (Claude's project memory) ────────────────────────────
MEM_SRC="$HOME/.claude/projects/-home-elijah/memory"
if [ -d "$MEM_SRC" ]; then
  mkdir -p claude_memory
  rsync -a --delete "${RSYNC_EXCLUDES[@]}" "$MEM_SRC/" claude_memory/
fi

# ── Chat history ────────────────────────────────────────────────────
if [ -d "$HOME/.master_ai_chats" ]; then
  mkdir -p master_ai_chats
  rsync -a --delete "${RSYNC_EXCLUDES[@]}" "$HOME/.master_ai_chats/" master_ai_chats/
fi

# ── Single-file state ───────────────────────────────────────────────
for f in \
  "$HOME/.master_ai_harvest.jsonl" \
  "$HOME/.master_ai_audit_typed.jsonl" \
  "$HOME/.master_ai_memory" \
  "$HOME/.master_ai_settings" \
  "$HOME/.master_ai_approved" \
  "$HOME/.master_ai_allowed_commands.json" \
  "$HOME/.master_ai_mode" \
  "$HOME/.master_ai_active_task" \
  "$HOME/.master_ai_router_metrics.jsonl"
do
  if [ -f "$f" ]; then
    cp "$f" "./$(basename "$f")"
  fi
done

# ── Desktop notes ───────────────────────────────────────────────────
if [ -f "$HOME/Desktop/master_ai_project_notes.md" ]; then
  mkdir -p desktop_notes
  cp "$HOME/Desktop/master_ai_project_notes.md" desktop_notes/
fi

# Safety: explicitly remove any secret file that may have slipped through.
rm -f master_ai_keys master_ai_extension_token .master_ai_keys .master_ai_extension_token 2>/dev/null

# README so anyone (including future you) opening this repo knows what it is.
cat > README.md <<'README'
# master-ai-state-backup

**PRIVATE.** Non-code state backup for Master AI / Sensei.

Disaster recovery: if the laptop is stolen, damaged, or wiped, restore from
here. Code is in the sibling repo `ebey317/master-ai-private` (clone that
first, then walk the directories below to put state back where it belongs).

## Layout

| Path here              | Goes back to                              | Contents                       |
|------------------------|-------------------------------------------|--------------------------------|
| `MD/`                  | `~/MD/`                                   | Shared Claude+Codex markdown   |
| `claude_memory/`       | `~/.claude/projects/-home-elijah/memory/` | Memory index + memory files    |
| `master_ai_chats/`     | `~/.master_ai_chats/`                     | Chat history (all surfaces)    |
| `master_ai_harvest.jsonl`     | `~/.master_ai_harvest.jsonl`       | Few-shot training data         |
| `master_ai_audit_typed.jsonl` | `~/.master_ai_audit_typed.jsonl`   | Action audit log               |
| `master_ai_memory`     | `~/.master_ai_memory`                     | Saved facts                    |
| `master_ai_settings`   | `~/.master_ai_settings`                   | No-mouse / phone mode flags    |
| `master_ai_approved`   | `~/.master_ai_approved`                   | Approved command list          |
| `master_ai_allowed_commands.json` | `~/.master_ai_allowed_commands.json` | Sensei's allowed-command map |
| `master_ai_mode`       | `~/.master_ai_mode`                       | Persisted MODE (plan/review/auto) |
| `master_ai_active_task` | `~/.master_ai_active_task`               | Current session context        |
| `master_ai_router_metrics.jsonl` | `~/.master_ai_router_metrics.jsonl` | Router decision audit     |
| `desktop_notes/`       | `~/Desktop/`                              | Hand-written notes             |

## What is NOT in here (intentional)

- `~/.master_ai_keys` — API keys. Re-enter on restore.
- `~/.master_ai_extension_token` — Chrome extension token. Regenerate on restore.
- SSH keys, gh credentials — not in scope.
- Code — see `ebey317/master-ai-private`.
- Ollama models — re-pull on restore (~5-10 min for master-ai:latest + llava).

## Backup mechanism

Sync script lives at `~/scripts/backup_state.sh` (versioned in the code repo).
Run via cron every 6 hours; manual run via `bash ~/scripts/backup_state.sh`.

## Restore drill (untested — exercise quarterly)

```bash
# 1. New machine — get the code first
git clone https://github.com/ebey317/master-ai-private ~/scripts

# 2. Get the state
git clone https://github.com/ebey317/master-ai-state-backup ~/master-ai-state-backup

# 3. Restore non-code files into their original paths
bash ~/scripts/backup_state.sh --restore   # (NOT YET IMPLEMENTED — manual rsync for now)

# 4. Re-enter secrets
nano ~/.master_ai_keys                     # paste API keys
~/scripts/install.sh                       # regenerates extension token + Ollama models
```
README

# Commit + push. Skip if no changes (don't pollute history with empty commits).
git add -A
if git diff --cached --quiet; then
  echo "$LOG_PREFIX no state changes since last backup — skipping commit"
  exit 0
fi

# Commit message includes a short summary of what changed so future-you can
# grep through history for "when did chat history grow" etc.
SUMMARY=$(git diff --cached --shortstat | head -1)
git commit -m "state snapshot $(date -Iseconds) — ${SUMMARY:-files updated}"

# Push. First-time push needs -u; subsequent pushes don't, but -u is harmless.
if git push -u origin main 2>&1 | tee /dev/stderr | grep -q "rejected"; then
  echo "$LOG_PREFIX push rejected. Run 'git pull --rebase origin main' and re-run this script."
  exit 3
fi

echo "$LOG_PREFIX OK — pushed to origin/main"
