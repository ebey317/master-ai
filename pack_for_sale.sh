#!/bin/bash
# ============================================================
# PACK FOR SALE — the ship ritual, as a script
#
# Run when Elijah says the phrase "pack it up for sale."
# Creates a CLEAN buyer-bound copy of ~/scripts in a target dir,
# scrubs Sunkissed/SKS references, strips personal data, generates
# docs (README + slideshow), writes a manifest, tags a version.
#
# Elijah's personal ~/scripts is NEVER mutated. The buyer bundle
# is a separate directory so he can keep working as usual.
#
# Usage:  bash ~/scripts/pack_for_sale.sh            (default target: ~/master-ai-for-sale)
#         bash ~/scripts/pack_for_sale.sh <outdir>
# ============================================================

set -euo pipefail
source ~/scripts/brand.sh 2>/dev/null || true
: "${BC:=$(tput bold 2>/dev/null; tput setaf 4 2>/dev/null)}"
: "${BG:=$(tput bold 2>/dev/null; tput setaf 2 2>/dev/null)}"
: "${BY:=$(tput bold 2>/dev/null; tput setaf 3 2>/dev/null)}"
: "${BR:=$(tput bold 2>/dev/null; tput setaf 1 2>/dev/null)}"
: "${BW:=$(tput bold 2>/dev/null; tput setaf 0 2>/dev/null)}"
: "${D:=$(tput setaf 8 2>/dev/null)}"
: "${X:=$(tput sgr0 2>/dev/null)}"

OUTDIR="${1:-$HOME/master-ai-for-sale}"
SRC="$HOME/scripts"
NEXT_VERSION="v1.9"   # bump manually when current v is v1.8

echo ""
echo -e "  ${BC}╔══════════════════════════════════════════════════════╗${X}"
echo -e "  ${BC}║${X}  ${BW}🥷  PACK FOR SALE${X}                                   ${BC}║${X}"
echo -e "  ${BC}╚══════════════════════════════════════════════════════╝${X}"
echo ""
echo -e "  ${BW}Target:${X}  $OUTDIR"
echo -e "  ${BW}Source:${X}  $SRC"
echo -e "  ${BW}Version tag:${X} $NEXT_VERSION (edit the script to bump)"
echo ""

# ── 1. Ship-readiness checklist ──────────────────────────────
echo -e "  ${BC}━━━ 1/6  ship-readiness checklist ━━━${X}"
READY=1
warn() { echo -e "  ${BY}⚠ $1${X}"; READY=0; }
ok()   { echo -e "  ${BG}✓ $1${X}"; }

[ -f "$SRC/master.sh" ]           && ok "master.sh present"          || warn "master.sh MISSING"
[ -f "$SRC/master_ai.py" ]        && ok "master_ai.py present"       || warn "master_ai.py MISSING"
[ -f "$SRC/pupil.html" ]          && ok "pupil.html present"         || warn "pupil.html MISSING"
[ -f "$SRC/dojo_gate.sh" ]        && ok "dojo_gate.sh present"       || warn "dojo_gate.sh MISSING"
[ -f "$SRC/learn.sh" ]            && ok "learn.sh present"           || warn "learn.sh MISSING"
[ -f "$SRC/install.sh" ]          && ok "install.sh present"         || warn "install.sh MISSING"
[ -f "$SRC/README_FOR_BUYER.md" ] && ok "README_FOR_BUYER.md present" || warn "README_FOR_BUYER.md MISSING"
[ -f "$SRC/PRIVACY.md" ]          && ok "PRIVACY.md present"          || warn "PRIVACY.md MISSING (store privacy disclosure)"
[ -f "$SRC/SUPPORT.md" ]          && ok "SUPPORT.md present"          || warn "SUPPORT.md MISSING (buyer support path)"
[ -f "$SRC/STORE_READINESS.md" ]  && ok "STORE_READINESS.md present"  || warn "STORE_READINESS.md MISSING (release checklist)"
[ -f "$SRC/slideshow.html" ]      && ok "slideshow.html present"     || warn "slideshow.html MISSING"
[ -d "$SRC/systemd" ]             && ok "systemd/ unit files present" || warn "systemd/ MISSING (auto-start won't wire on Linux)"
[ -f "$SRC/sensei_selftest.sh" ]  && ok "sensei_selftest.sh present"  || warn "sensei_selftest.sh MISSING (acceptance gate)"
[ -f "$SRC/master_ai_voice.json" ] && ok "master_ai_voice.json present" || warn "master_ai_voice.json MISSING (shared voice)"
[ -f "$SRC/selfscan.sh" ]         && ok "selfscan.sh present"         || warn "selfscan.sh MISSING (post-install scan)"
[ -f "$SRC/LINKS.md" ]            && ok "LINKS.md present"            || warn "LINKS.md MISSING (download links inventory)"
[ -f "$SRC/mesh.sh" ]             && ok "mesh.sh present"             || warn "mesh.sh MISSING (federated routing)"

if [ "$READY" != "1" ]; then
    echo ""
    echo -e "  ${BR}❌ Ship-readiness failed — generate the missing pieces before packing.${X}"
    exit 1
fi

if [ -d "$SRC/.git" ]; then
    if ! git -C "$SRC" diff --quiet || ! git -C "$SRC" diff --cached --quiet || [ -n "$(git -C "$SRC" ls-files --others --exclude-standard)" ]; then
        echo ""
        echo -e "  ${BR}❌ Git worktree is dirty. Commit, stash, or remove loose files before packing.${X}"
        git -C "$SRC" status --short | sed 's/^/  /'
        exit 1
    fi
    ok "git worktree clean"
fi

if find "$SRC" -maxdepth 1 -type f \( -name '*spam*.sh' -o -name '*unsubscribe*.sh' \) | grep -q .; then
    echo ""
    echo -e "  ${BR}❌ Found generated mail/spam automation script in source root. Refusing to pack.${X}"
    find "$SRC" -maxdepth 1 -type f \( -name '*spam*.sh' -o -name '*unsubscribe*.sh' \) | sed 's/^/  /'
    exit 1
fi

# ── 1b. Sensei acceptance gate — MUST pass before anything ships ─
echo ""
echo -e "  ${BC}━━━ 1b  sensei self-test (acceptance gate) ━━━${X}"
echo -e "  ${D}  9-phase stress: bash + python interop + git + http + cleanup${X}"
if bash "$SRC/sensei_selftest.sh" > /tmp/sensei_selftest.out 2>&1; then
    tail -5 /tmp/sensei_selftest.out | sed 's/^/  /'
    echo -e "  ${BG}✓ acceptance gate passed${X}"
else
    echo -e "  ${BR}❌ Sensei self-test FAILED. Full log:${X}  /tmp/sensei_selftest.out"
    tail -20 /tmp/sensei_selftest.out | sed 's/^/  /'
    echo ""
    echo -e "  ${BR}refusing to pack — scaffolding is not healthy.${X}"
    exit 1
fi

# ── 2. Prep the outdir ───────────────────────────────────────
echo ""
echo -e "  ${BC}━━━ 2/6  preparing $OUTDIR ━━━${X}"
if [ -d "$OUTDIR" ]; then
    echo -e "  ${BY}⚠ $OUTDIR exists — it will be wiped and rebuilt.${X}"
    read -rp "  proceed? (type YES to confirm) " ans
    [ "$ans" != "YES" ] && { echo "  cancelled."; exit 0; }
    rm -rf "$OUTDIR"
fi
mkdir -p "$OUTDIR"
echo -e "  ${BG}✓ outdir ready${X}"

# ── 3. Copy scripts, excluding personal + internal-only files ────────
echo ""
echo -e "  ${BC}━━━ 3/6  copying scripts (exclusions applied) ━━━${X}"
# Files/dirs that don't ship — personal data, internal-only scripts,
# the Sunkissed codebase, git-work, logs
EXCLUDES=(
    "--exclude=sessions"
    "--exclude=.git"
    "--exclude=__pycache__"
    "--exclude=*.pyc"
    "--exclude=*.log"
    "--exclude=master.crash.log"
    "--exclude=.claude"
    "--exclude=CLAUDE.md"
    "--exclude=archive"
    "--exclude=resources"
    "--exclude=memory"
    "--exclude=AUDIT_*"
    "--exclude=APOCALYPSE_MECHANISM_OPTIONS.md"
    "--exclude=howwework.txt"
    "--exclude=master_ai_developer_description.md"
    "--exclude=sync_hard_limits.py"
    "--exclude=inject_memory.sh"
    "--exclude=approval_queue.py"
    "--exclude=PENDING_SUDO.md"
    "--exclude=SENSEI_REASONING_LOOP.prompt.md"
    "--exclude=competitor_benchmark.sh"
    "--exclude=benchmark_sensei.sh"
    "--exclude=pack_for_sale.sh"
    "--exclude=pre_upgrade_backup.sh"
    "--exclude=save_context.sh"
    "--exclude=check_key_expiry.sh"
    "--exclude=cleanup.sh"
)
rsync -a "${EXCLUDES[@]}" "$SRC/" "$OUTDIR/"
echo -e "  ${BG}✓ copied (logs, .git, sessions, internal scripts excluded)${X}"

# ── 4. Scrub Sunkissed / SKS references in user-facing strings ──────
echo ""
echo -e "  ${BC}━━━ 4/6  scrubbing Sunkissed/SKS references ━━━${X}"

# pupil.html: replace the Sunkissed project card with "Flagship App" placeholder
# (buyer gets empty boards anyway — this is just in case a leftover ref exists)
sed -i "s|selectProject('Sunkissed Soul')|selectProject('Flagship')|g" "$OUTDIR/pupil.html" 2>/dev/null
sed -i "s|>Sunkissed Soul</div>|>Flagship App</div>|g" "$OUTDIR/pupil.html" 2>/dev/null
sed -i "s|Sunkissed Soul lives at base44.com .*\$||g" "$OUTDIR/pupil.html" 2>/dev/null

# master_ai.py: remove Sunkissed entry from the PROJECTS slide show
python3 - "$OUTDIR/master_ai.py" <<'PY'
import sys, re
p = sys.argv[1]
src = open(p).read()
# Remove the Sunkissed project dict from the projects slideshow
pat = re.compile(
    r'\s*\{\s*"name":\s*"Sunkissed Soul".*?\},\s*',
    re.DOTALL
)
new = pat.sub('\n        ', src)
if new != src:
    open(p, 'w').write(new)
    print("  ✓ Sunkissed project block stripped from master_ai.py")
else:
    print("  · no Sunkissed block to strip in master_ai.py")
PY

# Broad customer scrub. Source files can carry Elijah's working notes; the
# buyer bundle cannot. Keep this post-copy so the working repo remains intact.
if command -v rg >/dev/null 2>&1; then
    while IFS= read -r f; do
        [ -f "$f" ] || continue
        case "$f" in
            *.onnx|*.png|*.jpg|*.jpeg|*.gif|*.webp|*.zip|*.gz|*.tar|*.bundle) continue ;;
        esac
        perl -0pi -e '
            s/Elijah\x27s/the user\x27s/g;
            s/Elijah/the user/g;
            s/Madam-Mary/this machine/g;
            s#/home/elijah#~#g;
            s/ebey317\@gmail\.com/support email/g;
            s/github\.com\/ebey317/github.com/g;
            s/ebey317/your-github-handle/g;
            s/CLAUDE\.md \/ //g;
            s/CLAUDE\.md/project notes/g;
            s/Sunkissed Soul/Flagship App/g;
            s/Sunkissed/Flagship/g;
            s/\bSKS\b/Flagship/g;
        ' "$f" 2>/dev/null || true
    done < <(rg -l 'Elijah|Madam-Mary|/home/elijah|ebey317|Sunkissed|SKS' "$OUTDIR" || true)
fi

# systemd unit paths need %h rather than a literal user home.
find "$OUTDIR/systemd" -type f \( -name '*.service' -o -name '*.timer' \) 2>/dev/null | while read -r unit; do
    sed -i 's#~/scripts#%h/scripts#g' "$unit" 2>/dev/null || true
done

echo -e "  ${BG}✓ scrubbed${X}"

# ── 5. Strip personal data + ship empty project boards ───────────────
echo ""
echo -e "  ${BC}━━━ 5/6  stripping personal data ━━━${X}"

# PROJECTS.md → ship only the STRUCTURE with a sample "Starter" project
cat > "$OUTDIR/PROJECTS.md" <<'EOF'
# Your Projects

> Edit this file (or use menu option 9) to add new projects.
> Each project can be pinned before opening Sensei, but Sensei also opens directly.

---

## Project Boards

### Starter Project
- **Type:** master-bound
- **Role:** example — delete or rename when you make your own
- **Entry:** optional Dojo pinning
- **Model:** auto
- **Goal:** explore Master AI — learn what Sensei can do, get comfortable with the menu
- **Tasks:**
  - [ ] take the slideshow tour (`open ~/scripts/slideshow.html`)
  - [ ] finish Linux Class 1 in Pupil (menu 5 → Projects ▾ → Linux/Bash)
  - [ ] pin this project from Projects, then open Sensei
  - [ ] log your first real idea via menu 9

---

## Ideas / POCs
<!-- auto-appended by master.sh option 9 -->
EOF
echo -e "  ${BG}✓ PROJECTS.md replaced with starter board${X}"

# Empty the memory / history / keys / chats — buyer starts fresh
rm -rf "$OUTDIR/.master_ai_chats" 2>/dev/null
rm -f  "$OUTDIR/.master_ai_keys"  2>/dev/null
rm -f  "$OUTDIR/.master_ai_memory" 2>/dev/null
rm -f  "$OUTDIR/.master_ai_tasks" 2>/dev/null
rm -f  "$OUTDIR/.master_ai_history" 2>/dev/null
rm -f  "$OUTDIR/.master_ai_cache.json" 2>/dev/null
rm -f  "$OUTDIR/.master_ai_creator" 2>/dev/null     # creator marker NEVER ships
rm -f  "$OUTDIR/.dojo_gate_sealed" 2>/dev/null      # Sensei opens directly
rm -f  "$OUTDIR/.dojo_entered" 2>/dev/null
rm -rf "$OUTDIR/appforge" 2>/dev/null  # personal scaffold — don't ship
find "$OUTDIR" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUTDIR" -type f \( -name '*.log' -o -name '*.pyc' \) -delete 2>/dev/null || true
echo -e "  ${BG}✓ personal dotfiles + caches removed${X}"

cat > "$OUTDIR/INSTALL_FIRST.txt" <<'EOF'
MASTER AI — INSTALL FIRST

This is a local-first app, not a hosted cloud account.

Start here:

  bash install.sh

After install:

  master   # opens the main portal/menu
  sensei   # opens the terminal agent directly

Cloud keys are optional and belong to you. If you want cloud fallback,
the installer and Pupil setup screen will ask you to paste your own API
keys for providers such as Groq, OpenRouter, Gemini, or Firecrawl.

There is no seller login server in this package. The app runs on your
machine, uses your local Ollama models by default, and only uses cloud
providers when you configure your own keys.
EOF

# ── 6. Write manifest ────────────────────────────────────────────────
echo ""
echo -e "  ${BC}━━━ 6/6  writing manifest ━━━${X}"

# Write a manifest the buyer can verify
cat > "$OUTDIR/MANIFEST.txt" <<EOF
Master AI — Buyer Bundle
Version: $NEXT_VERSION
Packed:  $(date -Iseconds)
Host:    (stripped — your machine is your own)

Contents:
  master.sh              — main menu (the front door)
  master_ai.py           — Sensei (terminal AI agent)
  pupil.html             — Pupil (browser UI)
  dojo_gate.sh           — optional project/task picker for pinning context
  learn.sh               — lessons (Linux/bash → Python)
  install.sh             — installer (run this first)
  README_FOR_BUYER.md    — the full manual
  slideshow.html         — 12-slide click-and-read tour
  PROJECTS.md            — your project boards (seeded with Starter)
  tts_server.py          — optional voice (Piper)
  stt_server.py          — Pupil backend (/keys, /sessions)

What to do first:
  1. Run:   bash install.sh
  2. Open:  master.sh  (then option 5 for Pupil, or 4 for Sensei)
  3. Read:  README_FOR_BUYER.md — or open slideshow.html for the voiced tour
EOF
echo -e "  ${BG}✓ manifest written${X}"

# ── Summary ──────────────────────────────────────────────────────────
echo ""
echo -e "  ${BC}╔══════════════════════════════════════════════════════╗${X}"
echo -e "  ${BC}║${X}  ${BG}🥷  BUNDLE READY${X}                                    ${BC}║${X}"
echo -e "  ${BC}╚══════════════════════════════════════════════════════╝${X}"
echo ""
echo -e "  ${BW}Bundle:${X}   $OUTDIR"
echo -e "  ${BW}Next:${X}"
echo -e "    ${BG}1)${X} sanity-check the bundle: ${BW}bash $OUTDIR/master.sh${X} and poke around"
echo -e "    ${BG}2)${X} tar it:                   ${BW}tar czf master-ai-$NEXT_VERSION.tar.gz -C $OUTDIR .${X}"
echo -e "    ${BG}3)${X} upload to Gumroad / share link"
echo ""
echo -e "  ${D}Your personal $SRC was NOT modified — keep working as usual.${X}"
echo ""
