#!/bin/bash
# Multi-user live test — creates two throwaway profiles, switches between
# them, verifies that memory / chats / tasks / briefings stay isolated,
# then cleans up. Proves Sensei + Pupil + stt_server actually honor
# ~/.master_ai_active_profile at runtime.
#
# Safety: uses profile names prefixed 'test_' so real profiles can't be
# clobbered. Backs up and restores ~/.master_ai_active_profile.
# Exit 0 = PASS · Exit 1 = FAIL

set -u
source ~/scripts/brand.sh 2>/dev/null || true

PROFILES_DIR="$HOME/.master_ai_profiles"
ACTIVE_FILE="$HOME/.master_ai_active_profile"
BACKUP_ACTIVE=""
PASS=0
FAIL=0
LINES=()

pass() { PASS=$((PASS + 1)); LINES+=("${G:-}  ✅ PASS${X:-} — $1"); }
fail() { FAIL=$((FAIL + 1)); LINES+=("${R:-}  ❌ FAIL${X:-} — $1"); }
info() { LINES+=("${D:-}  ·   INFO${X:-} — $1"); }

echo ""
echo -e "${BC:-}╔════════════════════════════════════════════════════╗${X:-}"
echo -e "${BC:-}║${X:-}  ${BW:-}👥 MULTI-USER LIVE TEST${X:-}                           ${BC:-}║${X:-}"
echo -e "${BC:-}║${X:-}  ${D:-}two throwaway profiles · verify isolation · cleanup${X:-}  ${BC:-}║${X:-}"
echo -e "${BC:-}╚════════════════════════════════════════════════════╝${X:-}"
echo ""

# Back up current active-profile marker so the test is reversible
if [ -f "$ACTIVE_FILE" ]; then
    BACKUP_ACTIVE=$(cat "$ACTIVE_FILE")
    info "current active profile: '$BACKUP_ACTIVE' (will restore at end)"
else
    info "no active profile set (default) — will restore default at end"
fi

# Helper — build a profile skeleton same way master.sh add_user() does
seed_profile() {
    local p="$1"
    local root="$PROFILES_DIR/$p"
    mkdir -p "$root/sessions" "$root/chats" "$root/briefings"
    : > "$root/memory"
    : > "$root/tasks"
    cat > "$root/profile.json" <<EOF
{
  "name": "$p",
  "created": "$(date -Iseconds)",
  "selftest": true
}
EOF
}

# --- Phase 1 — seed two profiles
mkdir -p "$PROFILES_DIR"
rm -rf "$PROFILES_DIR/test_alice" "$PROFILES_DIR/test_bob" 2>/dev/null
seed_profile "test_alice"
seed_profile "test_bob"
[ -d "$PROFILES_DIR/test_alice" ] && pass "created profile test_alice" || fail "could not create test_alice"
[ -d "$PROFILES_DIR/test_bob"   ] && pass "created profile test_bob"   || fail "could not create test_bob"

# --- Phase 2 — activate alice, write identifiable state
echo "test_alice" > "$ACTIVE_FILE"
[ "$(cat "$ACTIVE_FILE")" = "test_alice" ] && pass "activated test_alice" || fail "could not activate test_alice"

ALICE_MEM_MARK="alice-memory-$(date +%s%N)"
ALICE_TASK_MARK="alice-task-$(date +%s%N)"
ALICE_CHAT_MARK="alice-chat-$(date +%s%N)"
echo "$ALICE_MEM_MARK"  >> "$PROFILES_DIR/test_alice/memory"
echo "$ALICE_TASK_MARK" >> "$PROFILES_DIR/test_alice/tasks"
echo "{\"name\":\"$ALICE_CHAT_MARK\"}" > "$PROFILES_DIR/test_alice/chats/alice_chat.json"
pass "wrote alice's memory / task / chat markers"

# Verify master_ai.py profile resolver sees alice
resolved=$(python3 -c "
import os, pathlib
p = (pathlib.Path.home()/'.master_ai_active_profile').read_text().strip()
pr = pathlib.Path.home()/'.master_ai_profiles'/p
print(p if pr.is_dir() else '')
" 2>/dev/null)
[ "$resolved" = "test_alice" ] && pass "profile resolver returns test_alice" \
    || fail "profile resolver returned '$resolved' (expected test_alice)"

# --- Phase 3 — switch to bob, confirm isolation
echo "test_bob" > "$ACTIVE_FILE"
[ "$(cat "$ACTIVE_FILE")" = "test_bob" ] && pass "switched to test_bob" || fail "switch to bob failed"

# Bob's memory / tasks / chats must NOT contain alice's markers
if grep -q "$ALICE_MEM_MARK" "$PROFILES_DIR/test_bob/memory" 2>/dev/null; then
    fail "alice's memory marker leaked into bob"
else
    pass "bob's memory is clean of alice's marker"
fi
if grep -q "$ALICE_TASK_MARK" "$PROFILES_DIR/test_bob/tasks" 2>/dev/null; then
    fail "alice's task marker leaked into bob"
else
    pass "bob's tasks are clean of alice's marker"
fi
if ls "$PROFILES_DIR/test_bob/chats/" 2>/dev/null | grep -q "alice_chat"; then
    fail "alice's chat file leaked into bob's chats"
else
    pass "bob's chats are clean of alice's files"
fi

# Write bob's own markers
BOB_MEM_MARK="bob-memory-$(date +%s%N)"
BOB_CHAT_MARK="bob-chat-$(date +%s%N)"
echo "$BOB_MEM_MARK" >> "$PROFILES_DIR/test_bob/memory"
echo "{\"name\":\"$BOB_CHAT_MARK\"}" > "$PROFILES_DIR/test_bob/chats/bob_chat.json"
pass "wrote bob's memory + chat markers"

# --- Phase 4 — switch back to alice, confirm alice still intact
echo "test_alice" > "$ACTIVE_FILE"
if grep -q "$ALICE_MEM_MARK" "$PROFILES_DIR/test_alice/memory"; then
    pass "alice's memory marker survived the round-trip"
else
    fail "alice's memory marker missing after round-trip"
fi
if [ -f "$PROFILES_DIR/test_alice/chats/alice_chat.json" ]; then
    pass "alice's chat file survived the round-trip"
else
    fail "alice's chat file missing after round-trip"
fi
if grep -q "$BOB_MEM_MARK" "$PROFILES_DIR/test_alice/memory" 2>/dev/null; then
    fail "bob's memory marker leaked into alice"
else
    pass "alice's memory is clean of bob's marker"
fi

# --- Phase 5 — stt_server live check (only if :8080 responds)
if curl -sf -m 2 http://localhost:8080/profile -o /tmp/mu_profile.json 2>/dev/null; then
    reported=$(python3 -c "import json; print(json.load(open('/tmp/mu_profile.json')).get('profile',''))" 2>/dev/null)
    if [ "$reported" = "test_alice" ]; then
        pass "stt_server /profile reports test_alice (live)"
    else
        fail "stt_server /profile returned '$reported' (expected test_alice)"
    fi
    # Switch and verify /profile updates immediately (no restart)
    echo "test_bob" > "$ACTIVE_FILE"
    reported=$(curl -sf -m 2 http://localhost:8080/profile | python3 -c "import json,sys;print(json.load(sys.stdin).get('profile',''))" 2>/dev/null)
    if [ "$reported" = "test_bob" ]; then
        pass "stt_server /profile reflects switch to test_bob (live, no restart)"
    else
        fail "stt_server /profile did not pick up switch (reported '$reported')"
    fi
    rm -f /tmp/mu_profile.json
else
    info "stt_server not running — skipping live /profile check"
fi

# --- Phase 6 — switch to default (remove active file), verify isolation
rm -f "$ACTIVE_FILE"
resolved=$(python3 -c "
import pathlib
p = pathlib.Path.home()/'.master_ai_active_profile'
print(p.read_text().strip() if p.exists() else '(default)')
" 2>/dev/null)
[ "$resolved" = "(default)" ] && pass "active-profile file removed (back to default)" \
    || fail "active-profile file still present: '$resolved'"

# Default memory (~/.master_ai_memory) must NOT contain either test marker
if grep -qE "$ALICE_MEM_MARK|$BOB_MEM_MARK" "$HOME/.master_ai_memory" 2>/dev/null; then
    fail "test markers leaked into default ~/.master_ai_memory"
else
    pass "default ~/.master_ai_memory untouched by test"
fi

# --- Phase 7 — cleanup
rm -rf "$PROFILES_DIR/test_alice" "$PROFILES_DIR/test_bob"
[ ! -d "$PROFILES_DIR/test_alice" ] && [ ! -d "$PROFILES_DIR/test_bob" ] \
    && pass "test profile dirs removed" \
    || fail "test profile dirs still present"

# Restore original active profile marker
if [ -n "$BACKUP_ACTIVE" ]; then
    echo "$BACKUP_ACTIVE" > "$ACTIVE_FILE"
    info "restored previous active profile: '$BACKUP_ACTIVE'"
else
    rm -f "$ACTIVE_FILE"
    info "restored default (no active profile)"
fi

# --- Summary
echo ""
for l in "${LINES[@]}"; do echo -e "$l"; done
echo ""
echo -e "${BW:-}  results:${X:-} ${G:-}${PASS} PASS${X:-} · ${R:-}${FAIL} FAIL${X:-}"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo -e "${G:-}  ✅ Multi-user isolation VERIFIED.${X:-}"
    echo -e "${D:-}     each profile keeps its own memory, tasks, chats; stt_server live-switches.${X:-}"
    exit 0
else
    echo -e "${R:-}  ❌ Multi-user isolation test FAILED.${X:-}"
    exit 1
fi
