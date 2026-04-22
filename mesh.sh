#!/bin/bash
# Master AI Mesh — minimum viable node-to-node scaffolding.
# Manages ~/.master_ai_mesh.json: list / add / remove / ping peer nodes.
# No federated routing yet — this is just the address book + reachability check.
# Each peer is another machine running stt_server.py on :8080.

source ~/scripts/brand.sh 2>/dev/null || true

MESH_FILE="$HOME/.master_ai_mesh.json"

# Seed the config if missing. node_name defaults to hostname; peers is empty.
# mesh_token authenticates federated /ask calls — a random 32-hex value that
# every peer must share. If you rotate the token, rotate it on ALL peers.
ensure_config() {
    if [ ! -f "$MESH_FILE" ]; then
        local token
        token=$(od -An -N16 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n' | head -c 32)
        [ -z "$token" ] && token="$(date +%s%N)$(hostname)"
        cat > "$MESH_FILE" <<EOF
{
  "node_name": "$(hostname)",
  "mesh_token": "$token",
  "peers": []
}
EOF
        chmod 600 "$MESH_FILE"
    else
        # Backfill mesh_token if an older config is missing it.
        if ! grep -q '"mesh_token"' "$MESH_FILE"; then
            local token
            token=$(od -An -N16 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n' | head -c 32)
            python3 - "$MESH_FILE" "$token" <<'PY'
import json, sys
path, tok = sys.argv[1], sys.argv[2]
cfg = json.load(open(path))
cfg.setdefault('mesh_token', tok)
json.dump(cfg, open(path, 'w'), indent=2)
PY
        fi
    fi
}

# Pretty print the current mesh config.
mesh_list() {
    ensure_config
    local node
    node=$(python3 -c "import json; print(json.load(open('$MESH_FILE')).get('node_name',''))" 2>/dev/null)
    echo ""
    echo -e "  ${BC}🕸  Master AI Mesh${X}"
    echo -e "  ${D}─────────────────────────────${X}"
    echo -e "  ${W}this node:${X} ${BW}$node${X}"
    echo ""

    local count
    count=$(python3 -c "import json; print(len(json.load(open('$MESH_FILE')).get('peers',[])))" 2>/dev/null)
    if [ "${count:-0}" = "0" ]; then
        echo -e "  ${D}no peers yet. use '${W}add${D}' to register one.${X}"
        return 0
    fi

    echo -e "  ${W}peers:${X}"
    python3 - "$MESH_FILE" <<'PY'
import json, sys
path = sys.argv[1]
cfg  = json.load(open(path))
for i, p in enumerate(cfg.get('peers', []), 1):
    name = p.get('name', '?')
    host = p.get('host', '?')
    note = p.get('note', '')
    line = f"    {i}) {name:<20}  {host}"
    if note:
        line += f"  ({note})"
    print(line)
PY
}

# Add a peer. Asks for a name and a host (IP or hostname). Optional note.
mesh_add() {
    ensure_config
    echo ""
    echo -ne "  ${BC}peer name${X} (e.g. laptop-upstairs): "
    read -r name
    [ -z "$name" ] && { echo "  cancelled."; return 1; }

    echo -ne "  ${BC}host${X} (Tailscale IP or LAN hostname): "
    read -r host
    [ -z "$host" ] && { echo "  cancelled."; return 1; }

    echo -ne "  ${BC}note${X} (optional, one line): "
    read -r note

    python3 - "$MESH_FILE" "$name" "$host" "$note" <<'PY'
import json, sys
path, name, host, note = sys.argv[1:5]
cfg = json.load(open(path))
cfg.setdefault('peers', [])
# Dedupe by host
cfg['peers'] = [p for p in cfg['peers'] if p.get('host') != host]
cfg['peers'].append({'name': name, 'host': host, 'note': note})
json.dump(cfg, open(path, 'w'), indent=2)
print(f"  ✅ added {name} @ {host}")
PY
}

# Remove a peer by index (from the list shown in mesh_list).
mesh_remove() {
    ensure_config
    mesh_list
    echo ""
    echo -ne "  ${BC}remove which #${X} (or x to cancel): "
    read -r n
    [[ -z "$n" || "$n" =~ ^[xX]$ ]] && { echo "  cancelled."; return 0; }
    [[ ! "$n" =~ ^[0-9]+$ ]] && { echo -e "  ${R}enter a number${X}"; return 1; }

    python3 - "$MESH_FILE" "$n" <<'PY'
import json, sys
path, n = sys.argv[1], int(sys.argv[2])
cfg = json.load(open(path))
peers = cfg.get('peers', [])
if not (1 <= n <= len(peers)):
    print("  out of range"); sys.exit(1)
gone = peers.pop(n - 1)
cfg['peers'] = peers
json.dump(cfg, open(path, 'w'), indent=2)
print(f"  🗑  removed {gone.get('name','?')} @ {gone.get('host','?')}")
PY
}

# Ping every peer by curl'ing /node_info. Prints reachable/unreachable.
mesh_ping() {
    ensure_config
    local hosts
    hosts=$(python3 -c "import json; [print(p.get('host','')) for p in json.load(open('$MESH_FILE')).get('peers',[])]" 2>/dev/null)
    if [ -z "$hosts" ]; then
        echo -e "  ${D}no peers to ping.${X}"
        return 0
    fi
    echo ""
    echo -e "  ${BC}pinging peers...${X}"
    while IFS= read -r h; do
        [ -z "$h" ] && continue
        local url="http://${h}:8080/node_info"
        if curl -sf -m 3 "$url" >/dev/null 2>&1; then
            echo -e "  ${G}✅ $h — reachable${X}"
        else
            echo -e "  ${R}❌ $h — unreachable${X} ${D}($url)${X}"
        fi
    done <<< "$hosts"
}

# Little menu loop so the user can stay in mesh mode to add a few peers.
mesh_menu() {
    while true; do
        mesh_list
        echo ""
        echo -e "  ${BC}a)${X} add peer   ${BC}r)${X} remove peer   ${BC}p)${X} ping all   ${BC}x)${X} back"
        echo ""
        read -rp "  pick: " c
        case "$c" in
            a|A) mesh_add ;;
            r|R) mesh_remove ;;
            p|P) mesh_ping ;;
            x|X|'') return 0 ;;
            *) echo -e "  ${R}? unknown${X}" ;;
        esac
        echo ""
        read -rp "  [press Enter] " _ || true
    done
}

# Federated ask — POST /ask on a peer with this node's shared mesh_token.
# Usage: mesh_ask <peer_host_or_name> <prompt...>
# Falls back to loopback (127.0.0.1) if the peer name matches "self" / "local" /
# "localhost" — useful for smoke-testing the /ask pipe without a real peer.
mesh_ask() {
    ensure_config
    local peer="$1"; shift || true
    local prompt="$*"
    if [ -z "$peer" ] || [ -z "$prompt" ]; then
        echo "  usage: mesh.sh ask <peer> <prompt...>"
        return 1
    fi

    # Resolve peer → host (match by name first, then host, then loopback fallback)
    local host=""
    case "$peer" in
        self|local|localhost|127.0.0.1) host="127.0.0.1" ;;
        *)
            host=$(python3 - "$MESH_FILE" "$peer" <<'PY'
import json, sys
path, want = sys.argv[1], sys.argv[2]
cfg = json.load(open(path))
for p in cfg.get('peers', []):
    if p.get('name') == want or p.get('host') == want:
        print(p.get('host', ''))
        sys.exit(0)
print('', end='')
PY
            )
            ;;
    esac
    if [ -z "$host" ]; then
        echo -e "  ${R}unknown peer:${X} $peer  (try 'ls' to see known peers; or use 'self' for loopback)"
        return 1
    fi

    local token
    token=$(python3 -c "import json; print(json.load(open('$MESH_FILE')).get('mesh_token',''))")
    if [ -z "$token" ]; then
        echo -e "  ${R}mesh_token missing — re-run 'mesh.sh ls' to backfill${X}"
        return 1
    fi

    echo -e "  ${BC}→ ${peer} (${host}):${X} $prompt"
    local body
    body=$(python3 -c "import json,sys; print(json.dumps({'prompt': sys.argv[1], 'model': 'qwen2.5:3b'}))" "$prompt")
    local resp
    resp=$(curl -sf -m 180 -X POST "http://${host}:8080/ask" \
        -H "Content-Type: application/json" \
        -H "X-Mesh-Token: $token" \
        -d "$body" 2>&1)
    if [ -z "$resp" ]; then
        echo -e "  ${R}❌ no response — peer unreachable or Ollama down${X}"
        return 1
    fi
    # Extract the response field; fall back to raw on parse failure
    local text
    text=$(echo "$resp" | python3 -c "import json,sys
try:
    d=json.load(sys.stdin)
    if 'error' in d: print('[error]', d['error'])
    else: print(d.get('response',''))
    if 'elapsed_s' in d: print('  (', d['elapsed_s'], 's on', d.get('node','?'), ')', sep='')
except Exception as e:
    print(sys.stdin.read())" 2>/dev/null)
    echo "$text"
}

# Dispatcher: `mesh.sh ls | add | remove | ping | ask | menu` (default: menu)
case "${1:-menu}" in
    ls|list)   mesh_list ;;
    add)       mesh_add ;;
    rm|remove) mesh_remove ;;
    ping)      mesh_ping ;;
    ask)       shift; mesh_ask "$@" ;;
    menu|*)    mesh_menu ;;
esac
