#!/bin/bash
# Daily housekeeping for Master AI:
#  • gzip full chat transcripts older than 7 days (keeps .summary uncompressed)
#  • rotate master.log + master.crash.log when they exceed 1 MB
#  • prune gzipped chats older than 180 days entirely

set -u
CHATS="$HOME/.master_ai_chats"
LOG_DIR="$HOME/scripts"

log_section() { echo "── $1 ──"; }

log_section "Chats: gzipping transcripts >7 days"
if [ -d "$CHATS" ]; then
    find "$CHATS" -maxdepth 1 -type f -name "*.chat" -mtime +7 -print | while read -r f; do
        gzip -9 "$f" && echo "  gz: $(basename "$f")"
    done
    find "$CHATS" -maxdepth 1 -type f -name "*.chat.gz" -mtime +180 -delete -print | \
        sed 's|^|  rm (>180d): |;s|.*/||'
    echo "  size now: $(du -sh "$CHATS" 2>/dev/null | cut -f1)"
fi

log_section "Logs: rotating files >1MB"
for f in "$LOG_DIR/master.log" "$LOG_DIR/master.crash.log" \
         "$LOG_DIR/stt_server.log" "$LOG_DIR/tts_server.log"; do
    [ -f "$f" ] || continue
    size=$(stat -c%s "$f" 2>/dev/null || echo 0)
    if [ "$size" -gt 1048576 ]; then
        mv "$f" "$f.1"
        gzip -9 -f "$f.1"
        : > "$f"
        echo "  rotated: $(basename "$f") (${size} bytes → ${f}.1.gz)"
    fi
done

# Prune rotated logs older than 60 days
find "$LOG_DIR" -maxdepth 1 -type f -name "*.log.1.gz" -mtime +60 -delete -print 2>/dev/null | \
    sed 's|^|  rm (>60d): |;s|.*/||'

echo "── done $(date) ──"
