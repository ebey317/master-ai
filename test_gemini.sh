#!/usr/bin/env bash
# Diagnose the Gemini key without the credential ever appearing in your
# paste buffer. Run with:  bash ~/scripts/test_gemini.sh
set -uo pipefail

KEYFILE="$HOME/.master_ai_keys"
if [ ! -f "$KEYFILE" ]; then
    echo "no keys file at $KEYFILE"
    exit 1
fi

KEY="$(python3 -c "import json,sys; d=json.load(open('$KEYFILE')); print(d.get('gemini','') or '')")"

echo "── KEY CHECK ──"
if [ -z "$KEY" ]; then
    echo "  gemini key is EMPTY in $KEYFILE"
    exit 1
fi
echo "  key present: yes"
echo "  key length:  ${#KEY} chars"
echo "  starts with: ${KEY:0:4} (Google keys start with AIza)"
echo

RESP=$(mktemp)
URL="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${KEY}"

echo "── AVAILABLE MODELS (what your key can talk to) ──"
MODELS_RESP=$(mktemp)
HTTP0=$(curl -sS -o "$MODELS_RESP" -w "%{http_code}" \
    "https://generativelanguage.googleapis.com/v1beta/models?key=${KEY}")
echo "  HTTP status: $HTTP0"
if [ "$HTTP0" = "200" ]; then
    # Print just the model names, one per line, up to 20
    python3 -c "
import json, sys
d = json.load(open('$MODELS_RESP'))
for m in d.get('models', [])[:20]:
    name = m.get('name', '')
    methods = ','.join(m.get('supportedGenerationMethods', []))
    print(f'  {name}  [{methods}]')
"
else
    echo "  response (first 400 chars):"
    head -c 400 "$MODELS_RESP"
    echo
fi
rm -f "$MODELS_RESP"
echo

echo "── PLAIN PING — walk the model chain until one has free-tier quota ──"
MODELS="gemini-2.5-flash gemini-flash-latest gemini-2.0-flash gemini-2.5-flash-lite gemma-3-12b-it"
for MODEL in $MODELS; do
    URL="https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${KEY}"
    HTTP=$(curl -sS -o "$RESP" -w "%{http_code}" -X POST "$URL" \
        -H "Content-Type: application/json" \
        -d '{"contents":[{"parts":[{"text":"hi"}]}]}')
    echo "  $MODEL → HTTP $HTTP"
    if [ "$HTTP" = "200" ]; then
        echo "    ✓ this model has quota — you're good"
        WORKING_MODEL="$MODEL"
        break
    fi
done
echo

if [ -n "${WORKING_MODEL:-}" ]; then
    echo "── GROUNDED PING on $WORKING_MODEL (with googleSearch tool) ──"
    URL="https://generativelanguage.googleapis.com/v1beta/models/${WORKING_MODEL}:generateContent?key=${KEY}"
    HTTP2=$(curl -sS -o "$RESP" -w "%{http_code}" -X POST "$URL" \
        -H "Content-Type: application/json" \
        -d '{"contents":[{"parts":[{"text":"who won wrestlemania 2026"}]}],"tools":[{"googleSearch":{}}]}')
    echo "  HTTP status: $HTTP2"
    if [ "$HTTP2" = "200" ]; then
        echo "  ✓ grounded search WORKS on $WORKING_MODEL — master_ai.py will use it"
    else
        echo "  ✗ grounded search failed — model has quota but not for the googleSearch tool"
        echo "  response (first 400 chars):"
        head -c 400 "$RESP"
        echo
    fi
else
    echo "── ALL MODELS RETURNED 429 — no free-tier quota on this project ──"
    echo "  To fix: https://console.cloud.google.com/ → your project →"
    echo "    1. Enable 'Generative Language API'"
    echo "    2. Link a billing account (free tier stays free, billing just unlocks quota)"
    echo "    3. Regenerate the key if needed"
    echo "  Or: create a fresh project at ai.google.dev and use the key it provides."
    echo "  Meanwhile: web_search() falls back to DuckDuckGo, which works fine."
fi
rm -f "$RESP"

echo
echo "── WHAT THE NUMBERS MEAN ──"
echo "  200 on both        → key + grounding work, search ready to use"
echo "  200 plain / 4xx grounded  → plain works but grounding tool isn't on this tier"
echo "  4xx on plain       → key itself is the problem (invalid, wrong project, API disabled)"
echo "  403 unregistered   → key wasn't transmitted; check for paste corruption"
echo "  429                → rate limited; wait or reduce calls"
