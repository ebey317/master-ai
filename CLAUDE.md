# Claude Code Handoff — Master AI

Last updated: 2026-04-27

This repo is Elijah's local-first AI agent stack. Treat it as a local Claude Code / Codex-style computer agent, not a generic chatbot or greenfield app.

## Recent Uncommitted Changes (2026-04-27)

Two work units landed on disk; not yet committed.

### Phase 1: deterministic system-query short-circuit + retry-on-prose

Root cause being fixed: the local 7B model writes prose for "where is X / find X / what's on port N / is X running / is X installed" instead of emitting `RUN:`/`READ:` directives, even though the Modelfile teaches them. Architecture-level fix in three layers (in execution order):

1. **Deterministic short-circuit in `master_ai.py`** — new helpers `_system_query_short_circuit`, `_is_system_state_question`, `_reply_has_directive`, `_build_filename_glob`. New route `system_query` in `orchestrate()` (placed after explicit prefixes so `local:`/`fast:`/`deep:` still win). Matches: file-find (`where is / find / locate / do I have / show me`), port (`what's on port N / using port N / port N`), service (`is X running/up/active`, `check service X`, `X service status`), installed package (`is X installed`, `do I have X installed`), list-files (`ls X`, `list files in X`, `what's in X`), open-file (`open file <path>`). Emits a synthesized `RUN:`/`READ:` line that flows through `process_reply()` — same dispatch path the LLM's directives would take, so mode-aware confirmation, action-failed chain abort, and router metrics all still apply. False-positive guards: glue-word filter, ≤6-word target, abstract first-word stop list, case-preserved path matching for `ls`/`open file`. Logs to router metrics as `system_query_short_circuit`.

2. **Retry-on-prose in `handle()`** — when `_is_system_state_question(low_user)` is true and the model's `reply` has no directive (`_reply_has_directive` checks RUN/RUNTERM/READ/CREATE/EDIT with backtick-parity, matching `process_reply`'s parser), a `[Directive repair]` message is appended to history and `result = None`, which triggers the existing repair loop at line ~7070+. Single retry only — the existing infrastructure already prevents loops. Logs as `retry_on_prose`.

3. **Modelfile-master-ai rebuild** — added `SYSTEM-STATE QUESTIONS` section as an explicit exception to `REASON FIRST`, with 7 hard few-shot examples (field-manual find, LibreOffice templates, port 8080, ollama running, libreoffice installed, list templates, check service rustdesk). Model rebuilt via `ollama create master-ai -f /home/elijah/scripts/Modelfile-master-ai` — new layer `sha256:2d26fc57...`.

Tests passing: `py_compile master_ai.py harvest.py` ✓, `test_master_ai_parser.py` 9/9 ✓, `bash -n` on shell scripts ✓, helper unit tests 23/23 + 11/11 + 19/19 ✓, `orchestrate()` smoke 5/5 ✓, end-to-end find locates `/home/elijah/off_grid_kit/biovega_field_manual.md`. `pack_for_sale.sh` blocks on dirty git tree (expected).

### Menu duplicates cleanup in `sensei_tui.py`

User-facing duplication only — dispatch tuples in `master_ai.py` keep all aliases for muscle-memory compatibility (typing `menu`, `reload`, `kick`, `home`, `health`, `open preview`, `task list` still works, just no autocomplete suggestion). Removed from `COMMAND_MENU_HINTS`: `menu`, `home`, `reload`, `task list`, `open preview`, `health`, `kick`. Canonicals kept: `hub`, `restart`, `refresh`, `tasks`, `preview`, `doctor`. Removed from `,` group: same set. Cross-group fix: `.` group is now pure scroll (`up`/`down`/`top`/`bottom`/`last`) — `cache`, `approved`, `log`, `health`, `doctor` removed from `.` (still present in `,`).

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

Active side project: upstream Loki contribution in `~/master_ai_loki_fork/`.

- Goal is not to fork Loki as a Master AI product. Improve Loki and contribute upstream to `gitlab.com/maik3531/LibreOffice_KI-Assistent`.
- Do not move this work into `~/scripts/master_ai.py`; Master AI stays untouched for this lane.
- Existing Loki chat dialog is the surface to polish. It is a hand-built non-modal UNO dialog in `main.py`, launched by the `Chat` command / AI Chat menu item.
- Menu mapping in `Addons.xcu`: `M1` Extend selection, `M2` Edit/create text, `M3` Insert AI image, `M4` AI Chat, `M5` Settings.
- Current local patch in `~/master_ai_loki_fork/main.py` adds chat tabs inside the existing chat dialog and a `Make Doc` button.
- `Make Doc` uses Loki's configured backend through `call_chat_api()` and creates a Writer `.odt` document from the active chat. It extracts URLs and inserts QR images when the optional Python `qrcode` package is available.
- Verification so far: `python3 -m py_compile ~/master_ai_loki_fork/main.py` passes.
- Not yet verified: actual LibreOffice UNO dialog behavior and ODT save flow inside Writer.

Important correction: Alt+C appears in Loki accelerator config/runtime installer, but do not assume it works or describe it as the primary user path. Anchor the feature on the existing AI Chat command/menu unless shortcut repair is explicitly requested.

Parked idea: a separate Master-AI-specific Writer extension is not the immediate move.

## Current Sync Snapshot

As of commit `ffb5475`, the older "WHERE WE WERE" snapshot that stops at
`066c9fa` is stale. The current Codex lane has already moved past that point.

- Buyer-safe zip exists at `~/Desktop/master-ai-v1.8-buyer-bundle.zip`.
  - Built through `pack_for_sale.sh`.
  - Scrubbed of personal keys, sessions, `.git`, logs, cache artifacts, and spam/unsubscribe scripts.

- Personal working archive exists at `~/Desktop/master-ai-personal-working-archive-ffb5475.zip`.
  - This is for Elijah's own stable-point archive, not for buyers.
  - It contains the tracked repo state plus `master-ai-ffb5475-history.bundle`.

- Customer install zip exists at `~/Desktop/Master-AI-v1.8-Customer-Install.zip`.
  - This is the buyer-facing package.
  - It includes `INSTALL_FIRST.txt`.
  - It is local-first/BYOK, not a hosted cloud-login SaaS.
  - It is scrubbed of creator-specific handoff files, personal archives, `.git`, sessions, logs, keys, and internal Claude sync state.

- Latest terminal UX state:
  - `master` opens the main portal/menu.
  - `sensei` opens the terminal agent directly.
  - Installer creates both commands and auto-configures PATH.
  - Sensei now has `image: <prompt>` for local image jobs; Pupil's Image tab
    shows the same sd-server job stream and inline PNG result.

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
