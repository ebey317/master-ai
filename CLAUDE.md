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

- `757f891 Sync Claude handoff and command UX`
  - Added `CLAUDE.md` as the cross-agent handoff file.
  - Added `commands`, `command`, and `?` as simple first-screen command help.
  - Added `tight:` / `reason:` as user-friendly tighter reasoning prefixes.
  - Uses DeepSeek-R1 through OpenRouter when configured.
  - Falls back to local `think deep:` reasoning loop.
  - Output is display-only; directive-looking lines are neutralized before display.
  - README documents `fast:`, `deep:`, `tight:`, and `think:`.

- `a2a8587 Fix Any Key provider placement`
  - Pupil Any Key no longer guesses Gumroad from generic 30-50 char tokens.
  - Unknown ambiguous keys require explicit provider dropdown selection.
  - Success message now reports the actual server key slot saved to `~/.master_ai_keys`.

- `7745c4c Install terminal launch commands`
  - Installer creates `~/.local/bin/master` and `~/.local/bin/sensei`.
  - `master` opens the main one-command portal/menu.
  - `sensei` opens the Sensei terminal agent directly.

- `261bc22 Auto-configure terminal command PATH`
  - Installer adds `~/.local/bin` to `.bashrc`, `.profile`, and `.zshrc` when missing.
  - Installer exports the updated PATH during the current install session too.

## Current In-Progress Changes

No known in-progress changes at this handoff. Worktree should be clean.

## Current Sync Snapshot

As of commit `ffb5475`, the older "WHERE WE WERE" snapshot that stops at
`066c9fa` is stale. The current Codex lane has already moved past that point.

- Buyer-safe zip exists at `~/Desktop/master-ai-v1.8-buyer-bundle.zip`.
  - Built through `pack_for_sale.sh`.
  - Scrubbed of personal keys, sessions, `.git`, logs, cache artifacts, and spam/unsubscribe scripts.

- Personal working archive exists at `~/Desktop/master-ai-personal-working-archive-ffb5475.zip`.
  - This is for Elijah's own stable-point archive, not for buyers.
  - It contains the tracked repo state plus `master-ai-ffb5475-history.bundle`.

- Latest terminal UX state:
  - `master` opens the main portal/menu.
  - `sensei` opens the terminal agent directly.
  - Installer creates both commands and auto-configures PATH.

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

- Keep terminal entry behavior simple:
  - `master` = one-command portal/menu.
  - `sensei` = direct local Claude Code-style terminal agent.
  - Buyer installer should set this up automatically.

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
