#!/bin/bash
# Serve master_ai.html on localhost:8080
# Avoids CORS issues with file:// protocol
PORT=8080
SCRIPTS="$HOME/scripts"

# Kill any existing server on this port
fuser -k ${PORT}/tcp 2>/dev/null

echo "🚀 Starting UI server on http://localhost:${PORT}"
echo "   Open: http://localhost:${PORT}/master_ai.html"

cd "$SCRIPTS"
python3 ~/scripts/stt_server.py $PORT > /tmp/ui_server.log 2>&1 &
SERVER_PID=$!

sleep 1

if kill -0 $SERVER_PID 2>/dev/null; then
    echo "✅ Server running (PID $SERVER_PID)"
    URL="http://localhost:${PORT}/master_ai.html"
    if command -v wmctrl >/dev/null 2>&1 && wmctrl -l 2>/dev/null | grep -qi "Master AI"; then
        echo "  ↺ UI already open — focusing existing window"
        wmctrl -a "Master AI" 2>/dev/null || true
    else
        for browser in xdg-open firefox google-chrome-stable chromium-browser; do
            command -v "$browser" &>/dev/null && { "$browser" "$URL" 2>/dev/null & break; }
        done
    fi
else
    echo "❌ Server failed to start"
fi
