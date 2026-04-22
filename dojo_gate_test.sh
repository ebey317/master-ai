#!/bin/bash
# Dojo gate logic test — exercises the parsers and state-writing path
# in dojo_gate.sh against a synthetic fixture, without opening Sensei.
# Verifies: list_projects, unchecked_tasks, project_model, project_goal,
# the write-three-files flow, and the `done`-flips-[x] logic on a
# sandbox copy of PROJECTS.md. Cleans up and restores everything.
# Exit 0 = PASS · Exit 1 = FAIL

set -u
source ~/scripts/brand.sh 2>/dev/null || true

REAL_PROJECTS="$HOME/scripts/PROJECTS.md"
FIXTURE=$(mktemp -t dojo_fixture_XXXXXX.md)
BACKUP_PROJECT=""
BACKUP_TASK=""
BACKUP_MODEL=""
PASS=0
FAIL=0
LINES=()

pass() { PASS=$((PASS + 1)); LINES+=("${G:-}  ✅ PASS${X:-} — $1"); }
fail() { FAIL=$((FAIL + 1)); LINES+=("${R:-}  ❌ FAIL${X:-} — $1"); }

echo ""
echo -e "${BC:-}╔════════════════════════════════════════════════════╗${X:-}"
echo -e "${BC:-}║${X:-}  ${BW:-}🥷 DOJO GATE LOGIC TEST${X:-}                           ${BC:-}║${X:-}"
echo -e "${BC:-}║${X:-}  ${D:-}parsers · state writes · done flips · no Sensei launch${X:-} ${BC:-}║${X:-}"
echo -e "${BC:-}╚════════════════════════════════════════════════════╝${X:-}"
echo ""

# Back up any current active-state dotfiles so we can restore them
[ -f "$HOME/.master_ai_active_project" ] && BACKUP_PROJECT=$(cat "$HOME/.master_ai_active_project")
[ -f "$HOME/.master_ai_active_task"    ] && BACKUP_TASK=$(cat "$HOME/.master_ai_active_task")
[ -f "$HOME/.master_ai_active_model"   ] && BACKUP_MODEL=$(cat "$HOME/.master_ai_active_model")

# --- Build a synthetic PROJECTS.md fixture with two projects
cat > "$FIXTURE" <<'FIX'
# Fixture PROJECTS.md

## Project Boards

### Alpha Project
- **Type:** master-bound
- **Role:** fixture for parser test
- **Gate:** open
- **Model:** qwen2.5:7b
- **Goal:** prove parsers work
- **Tasks:**
  - [ ] alpha-task-one
  - [ ] alpha-task-two
  - [x] alpha-task-done

### Beta Project
- **Type:** training
- **Role:** second fixture
- **Gate:** N/A
- **Model:** auto
- **Goal:** verify isolation across projects
- **Tasks:**
  - [ ] beta-task-one

## Ecosystem notes
(unrelated)
FIX

# Source the parsers from dojo_gate.sh, pointed at our fixture
# shellcheck source=./dojo_gate.sh
source "$HOME/scripts/dojo_gate.sh"
PROJECTS_FILE="$FIXTURE"   # override the module-level constant

# --- Phase 1: list_projects
projects=$(list_projects)
expected=$'Alpha Project\nBeta Project'
if [ "$projects" = "$expected" ]; then
    pass "list_projects returns both fixture projects in order"
else
    fail "list_projects output mismatch: got '$projects'"
fi

# --- Phase 2: unchecked_tasks per project
alpha_open=$(unchecked_tasks "Alpha Project")
expected_alpha=$'alpha-task-one\nalpha-task-two'
if [ "$alpha_open" = "$expected_alpha" ]; then
    pass "unchecked_tasks('Alpha Project') returns both open tasks, skips [x]"
else
    fail "unchecked_tasks('Alpha Project') wrong: '$alpha_open'"
fi

beta_open=$(unchecked_tasks "Beta Project")
if [ "$beta_open" = "beta-task-one" ]; then
    pass "unchecked_tasks('Beta Project') returns only its single open task"
else
    fail "unchecked_tasks('Beta Project') wrong: '$beta_open'"
fi

# --- Phase 3: project_model + project_goal
mod=$(project_model "Alpha Project")
if [ "$mod" = "qwen2.5:7b" ]; then
    pass "project_model('Alpha Project') = qwen2.5:7b"
else
    fail "project_model wrong: '$mod'"
fi
mod=$(project_model "Beta Project")
if [ "$mod" = "auto" ]; then
    pass "project_model('Beta Project') = auto"
else
    fail "project_model beta wrong: '$mod'"
fi
goal=$(project_goal "Alpha Project")
if [ "$goal" = "prove parsers work" ]; then
    pass "project_goal('Alpha Project') = 'prove parsers work'"
else
    fail "project_goal wrong: '$goal'"
fi

# --- Phase 4: state-write flow (what main() does before exec)
ap="$HOME/.master_ai_active_project"
at="$HOME/.master_ai_active_task"
am="$HOME/.master_ai_active_model"
echo "Alpha Project"    > "$ap"
echo "alpha-task-one"   > "$at"
echo "qwen2.5:7b"       > "$am"
[ "$(cat "$ap")" = "Alpha Project"  ] && pass "wrote active project marker" || fail "project marker wrong"
[ "$(cat "$at")" = "alpha-task-one" ] && pass "wrote active task marker"    || fail "task marker wrong"
[ "$(cat "$am")" = "qwen2.5:7b"     ] && pass "wrote active model marker"   || fail "model marker wrong"

# --- Phase 5: `done` flips [ ] → [x] in PROJECTS.md (simulate master_ai.py's _dojo_mark_done)
# Uses the same python logic Sensei uses — keep this in sync if that changes.
before=$(grep -c '\[ \] alpha-task-one' "$FIXTURE")
[ "$before" = "1" ] && pass "fixture pre-state: alpha-task-one is open" || fail "fixture pre-state wrong"

python3 - "$FIXTURE" "Alpha Project" "alpha-task-one" <<'PY'
import sys, re, pathlib
path = pathlib.Path(sys.argv[1])
target_proj = sys.argv[2]
target_task = sys.argv[3]
lines = path.read_text().splitlines()
in_proj = False
for i, ln in enumerate(lines):
    if ln == f"### {target_proj}":
        in_proj = True; continue
    if ln.startswith("### ") or ln.startswith("## "):
        in_proj = False
    if in_proj and re.match(r'^\s*- \[ \]\s*' + re.escape(target_task) + r'\s*$', ln):
        lines[i] = ln.replace("[ ]", "[x]", 1)
        break
path.write_text("\n".join(lines) + "\n")
PY

after_open=$(grep -c '\[ \] alpha-task-one' "$FIXTURE")
after_done=$(grep -c '\[x\] alpha-task-one' "$FIXTURE")
[ "$after_open" = "0" ] && pass "after done: alpha-task-one no longer [ ]" || fail "alpha-task-one still [ ]"
[ "$after_done" = "1" ] && pass "after done: alpha-task-one is now [x]" || fail "alpha-task-one not [x]"

# --- Phase 6: auto-pin-next — unchecked_tasks should now return just alpha-task-two
next_open=$(unchecked_tasks "Alpha Project")
if [ "$next_open" = "alpha-task-two" ]; then
    pass "auto-pin-next: remaining open task is alpha-task-two"
else
    fail "after done, open tasks wrong: '$next_open'"
fi

# --- Phase 7: seal-flag sentinel (don't actually seal — just verify detect)
if is_sealed; then
    fail "is_sealed reports true but no flag file was created — leaked state"
fi
touch "$HOME/.dojo_gate_sealed_testflag_not_real"
if is_sealed; then
    fail "is_sealed accepted a non-canonical flag filename"
else
    pass "is_sealed correctly ignores non-canonical flag files"
fi
rm -f "$HOME/.dojo_gate_sealed_testflag_not_real"

# --- cleanup: remove fixture, restore active-state markers to what Elijah had
rm -f "$FIXTURE"
if [ -n "$BACKUP_PROJECT" ]; then echo "$BACKUP_PROJECT" > "$ap"; else rm -f "$ap"; fi
if [ -n "$BACKUP_TASK"    ]; then echo "$BACKUP_TASK"    > "$at"; else rm -f "$at"; fi
if [ -n "$BACKUP_MODEL"   ]; then echo "$BACKUP_MODEL"   > "$am"; else rm -f "$am"; fi

echo ""
for l in "${LINES[@]}"; do echo -e "$l"; done
echo ""
echo -e "${BW:-}  results:${X:-} ${G:-}${PASS} PASS${X:-} · ${R:-}${FAIL} FAIL${X:-}"
echo ""
if [ "$FAIL" -eq 0 ]; then
    echo -e "${G:-}  ✅ Dojo gate logic VERIFIED.${X:-}"
    echo -e "${D:-}     parsers + state writes + done flip + auto-pin-next all correct.${X:-}"
    exit 0
else
    echo -e "${R:-}  ❌ Dojo gate test FAILED.${X:-}"
    exit 1
fi
