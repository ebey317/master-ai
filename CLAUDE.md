# Claude Code Handoff — Master AI

Last updated: 2026-04-25

This repo is Elijah's local-first AI agent stack. Treat it as a local Claude Code / Codex-style computer agent, not a generic chatbot or greenfield app.

## Current Positioning

Master AI is a local-first coding and computer-control agent for the user's own machine.

- Sensei: tmux terminal agent in `master_ai.py`
- Pupil: browser UI in `pupil.html`
- Dojo: optional project/task picker, not an entry gate
- Local default: Ollama models
- Cloud escalation: Groq for fast replies, DeepSeek-R1/OpenRouter for reasoning, Gemini/web for live facts

Use this wording when describing it:

> Local-first computer agent with optional cloud escalation.

## Recent Committed Fixes

- `3b55fc0 Add router feedback metrics`
  - Added `~/.master_ai_router_metrics.jsonl`
  - Route decisions, model calls, cloud fallbacks, and command execution are now logged.
  - Added `router` / `router stats` command.

- `f71a1e8 Harden store release gate`
  - Auto mode stops downstream commands after the first failed/refused `RUN:`.
  - Shell commands run through `bash -o pipefail`, so pipeline failures are not hidden.
  - Interactive commands such as `less`, `vim`, `top`, and `htop` are blocked from `RUN:`.
  - Missing top-level commands are blocked in Auto mode.
  - Added `PRIVACY.md`, `SUPPORT.md`, and `STORE_READINESS.md`.

- `2efe47a Handle sandboxed socket selftest`
  - `sensei_selftest.sh` treats socket-blocked sandboxes as WARN, not false RED.

- `8b250ff Open Sensei without Dojo gate`
  - Menu 4 opens Sensei directly through `launch_master_ai.sh`.
  - Installer removes `~/.dojo_gate_sealed`.
  - Sale bundle no longer creates `.SEAL_ON_INSTALL`.
  - Dojo remains optional project/task pinning.

## Current In-Progress Changes

These may be uncommitted when you read this:

- Added `tight:` / `reason:` as user-friendly tighter reasoning prefixes.
  - Uses DeepSeek-R1 through OpenRouter when configured.
  - Falls back to local `think deep:` reasoning loop.
  - Output is display-only; directive-looking lines are neutralized before display.

- Added `commands`, `command`, and `?` as simple first-screen command help.
  - This is meant to be friendlier than the full paginated `help`.

- README now documents `fast:`, `deep:`, `tight:`, and `think:`.

## Important Existing Architecture

- `harvest.py` is already the reuse layer.
  - Records local and cloud calls.
  - Serves near-duplicates from cache with no model call.
  - Provides few-shot examples.

- Cloud identity is already injected.
  - Cloud calls should understand "you / your app / this project" as Master AI itself.

- Do not reintroduce a mandatory Dojo gate.
  - Project pinning is useful, but Sensei should open immediately.

- Do not treat cloud lanes as agents.
  - They are router destinations.

## Tests / Gates

Run before declaring ready:

```bash
python3 -m py_compile ~/scripts/master_ai.py ~/scripts/harvest.py
python3 ~/scripts/test_master_ai_parser.py
bash -n ~/scripts/master.sh ~/scripts/install.sh ~/scripts/pack_for_sale.sh ~/scripts/sensei_selftest.sh
bash ~/scripts/pack_for_sale.sh /tmp/master-ai-sale-test
```

Expected pack result in this Codex sandbox: YELLOW self-test can pass if warnings are environment edges.

## Product Gaps Still Worth Fixing

- Pupil UI still needs a cleaner first-run command palette and simpler provider wording.
- Main menu labels should stay plain-language, not internal architecture names.
- A clean-machine install test is still the final proof for store readiness.
- Store upload assets still need screenshots, listing copy, price/support/refund setup.

