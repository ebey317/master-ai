#!/usr/bin/env bash
# Sensei extension redeploy — one-shot to flip committed changes live.
#
# Runs the deterministic steps needed to take master_ai.py /
# Modelfile-master-ai changes from "in git" to "running on the box":
#
#   1. Rebuild the local master-ai Ollama model from Modelfile so the
#      Modelfile-baked SYSTEM (PLAN-AS-BLOCK, VERIFICATION, STUCK-
#      RECOVERY, HUMAN-RHYTHM, NO-JSON, AMBIGUITY, POST-ACTION
#      CONFIRMATION) is what the local lane reads on the next /chat.
#
#   2. Restart master-ai-ui.service so stt_server.py reimports the
#      latest master_ai.py — that's how CLOUD_SYSTEM (cloud-lane
#      teaching) + orchestrate() routing changes pick up.
#
#   3. Print the manual steps that ONLY the user can take (Chrome
#      extension reload at chrome://extensions, refresh the target
#      tab) — neither is scriptable from this side, so we surface
#      them clearly instead of guessing.
#
# Safe to run any time. Idempotent. No sudo required (user-level
# systemd unit + ollama). Per feedback_passwords_other_terminal.md
# this script does not run sudo; if you need something gated, run it
# in your own terminal.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELFILE="${SCRIPT_DIR}/Modelfile-master-ai"
SERVICE="master-ai-ui.service"

# ANSI helpers — phone-readable colors per feedback_light_terminal.md
# (bold blue / green / red on light background).
BC=$'\033[1;34m'
BG=$'\033[1;32m'
BR=$'\033[1;31m'
BY=$'\033[1;33m'
X=$'\033[0m'

echo
echo "${BC}═══ Sensei Redeploy ═══${X}"
echo

# Step 1 — rebuild local master-ai model. ollama create is idempotent;
# unchanged Modelfile = no-op (manifest already up to date).
echo "${BC}[1/3]${X} Rebuilding local master-ai model from Modelfile…"
if [[ ! -f "${MODELFILE}" ]]; then
  echo "${BR}  ✗ Modelfile not found at ${MODELFILE}${X}"
  exit 1
fi
if ! command -v ollama >/dev/null 2>&1; then
  echo "${BR}  ✗ ollama not on PATH. Install it first, or this script can't run.${X}"
  exit 1
fi
ollama create master-ai -f "${MODELFILE}" 2>&1 | tail -3
echo "${BG}  ✓ master-ai model rebuilt${X}"
echo

# Step 2 — restart user service so master_ai.py + stt_server.py edits
# load. systemctl --user is the user-scope socket; no sudo.
echo "${BC}[2/3]${X} Restarting ${SERVICE}…"
if ! systemctl --user list-unit-files "${SERVICE}" 2>/dev/null | grep -q "${SERVICE}"; then
  echo "${BR}  ✗ ${SERVICE} not installed at the user scope.${X}"
  echo "${BR}    Run install.sh once to wire it up.${X}"
  exit 1
fi
systemctl --user restart "${SERVICE}"
# Brief settle so health probes get a real answer.
sleep 2
if systemctl --user is-active --quiet "${SERVICE}"; then
  echo "${BG}  ✓ ${SERVICE} is active${X}"
else
  echo "${BR}  ✗ ${SERVICE} did not come up clean. Check:${X}"
  echo "${BR}    journalctl --user -u ${SERVICE} -n 50${X}"
  exit 1
fi

# Verify the backend HTTP surface answers — catches the case where the
# service comes up but stt_server.py crashes mid-init.
if curl -sS --max-time 4 http://127.0.0.1:8080/health 2>/dev/null \
  | grep -q '"ok":\s*true'; then
  echo "${BG}  ✓ http://127.0.0.1:8080/health responds${X}"
else
  echo "${BY}  ⚠ /health didn't return ok=true within 4s — check journalctl${X}"
fi
echo

# Step 3 — manual user steps that can't be scripted. State them
# explicitly, don't pretend.
echo "${BC}[3/3]${X} Manual steps remaining (chrome://extensions is a GUI,"
echo "      and the target tab needs YOU to focus it):"
echo
echo "${BY}  a)${X} Open ${BC}chrome://extensions${X} → find ${BC}Sensei${X} → click the"
echo "     circular-arrow reload icon. This picks up content_script.js,"
echo "     side_panel.js, side_panel.css, and any manifest changes."
echo
echo "${BY}  b)${X} Refresh the target browser tab once (Cmd/Ctrl+R or F5)."
echo "     The reloaded extension only injects into pages opened AFTER"
echo "     reload — refreshing flips the existing tab onto the new build."
echo
echo "${BY}  c)${X} Send your prompt. If Sensei doesn't already have"
echo "     ${BC}Always allow site${X} on the page's origin, the first action"
echo "     card's primary (filled-accent) button will say"
echo "     \"Always allow <origin>\" — one click and the rest of the"
echo "     session flows."
echo
echo "${BG}═══ Done. Sensei is live on the latest committed teaching. ═══${X}"
