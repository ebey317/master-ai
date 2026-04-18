#!/bin/bash
# Master AI — Script Backup
# Takes a git snapshot of ~/scripts so you can revert to any point in time.

SCRIPTS_DIR="$HOME/scripts"
source "$SCRIPTS_DIR/brand.sh" 2>/dev/null

G='\033[92m'; Y='\033[33m'; C='\033[96m'; D='\033[90m'; W='\033[97m'; X='\033[0m'

cd "$SCRIPTS_DIR" || exit 1

# Init git if this is the first time
if [ ! -d "$SCRIPTS_DIR/.git" ]; then
    git init -q
    git config user.email "masterai@local"
    git config user.name "Master AI"
    echo -e "  ${D}Git initialized in ~/scripts${X}"
fi

# Stage all tracked file types; never commit sensitive data files
git add \
    *.sh *.html *.py *.txt *.md \
    Modelfile-master-ai \
    .gitignore \
    2>/dev/null

# Only commit if there's something new
if git diff --cached --quiet 2>/dev/null; then
    echo -e "  ${D}No changes since last snapshot.${X}"
    exit 0
fi

LABEL="${1:-manual snapshot}"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
git commit -q -m "[$TIMESTAMP] $LABEL"

HASH=$(git rev-parse --short HEAD 2>/dev/null)
echo -e "  ${G}✅ Snapshot saved${X}  ${D}${TIMESTAMP}${X}  ${C}${HASH}${X}  ${D}\"${LABEL}\"${X}"
