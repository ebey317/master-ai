# Master AI Runtime Notes

Last updated: 2026-04-29

This repo is Elijah's local-first AI agent stack. It runs standalone on this machine and does not require Claude/Codex relay wiring for normal operation.

## Screen Auto-Adjust + Standalone Mode (2026-04-29)

Sensei terminal auto-resize is now continuous, not one-shot:

- Startup still snaps to client dimensions.
- Runtime now keeps following active client size changes (watcher + tmux hooks).
- `resize` = resync dimensions without killing panes.
- `only` = intentionally kill other panes, then resync.

Standalone runtime rule:

- No external Claude CLI handoff is required.
- Keep execution local-first; optional cloud model keys are independent and user-controlled.

## v1.9 Tag — Banner words for voice-to-text (2026-04-29)

Tag `v1.9` cut on commit `b7828a3 Banner reads in plain words for phone voice-to-text`. Latest tags before this: v1.8, v1.7.11. `pack_for_sale.sh` already had `NEXT_VERSION=v1.9` from `4e7ce85`, so the tag matches the buyer-bundle version.

Driver: Elijah uses voice-to-text on his phone to read Sensei. Symbols (`│`, `·`, bare `, . / ;`) read as silent pauses. The banner and legend are now spelled out as words so TTS speaks them.

Changes in commit `b7828a3` (`master_ai.py` + `sensei_tui.py`):

1. **Status banner separator** — `master_ai.py:draw_status_bar()` line 7249. `"  │  ".join(parts)` → `"  and  ".join(parts)`. Wide-form banner reads `MODE:AUTO  and  MODEL:AUTO+CLOUD  and  MEM:243`.

2. **Narrow-truncation bug** — `sensei_tui.py:_render_status` was rewriting `MODEL:AUTO+CLOUD` → `MODEL:CLOUD` on terminals < 82 cols, which reads like cloud is pinned when it's actually auto-routing. Now drops the `+CLOUD` modifier and keeps the actual selection (`MODEL:AUTO`). Narrow-form banner: `MODE:AUTO and MODEL:AUTO and MEM:243`.

3. **Bottom legend** — `sensei_tui.py:_render_legend()` line 702. Was `MODE:<X> · , · . · / · ;` (separators + bare key labels). Now `MODE:<X>  and  comma  and  dot  and  slash  and  semicolon`. The keyboard triggers (`,` `.` `/` `;`) are unchanged in `COMMAND_MENU_GROUPS` — only the on-screen labels were spelled out so TTS can speak them.

4. **Docstring example** — `sensei_tui.py:17` `app.set_status("MODE:SAFE  │  MODEL:AUTO  │  MEM:42")` → `app.set_status("MODE:AUTO  and  MODEL:AUTO  and  MEM:42")`. `SAFE` was retired earlier; modes are `plan` / `review` / `auto`. Internal animation variable `_A_SAFE` (master_ai.py:3937) is still used for `review` mode and was not renamed in this commit — that's an internal name, not user-visible. Polish-pass candidate, not a v1.9 blocker.

Tests run before tag: `python3 -m py_compile master_ai.py sensei_tui.py` ✓, `python3 ~/scripts/test_master_ai_parser.py` 19/19 ✓.

Things NOT touched by this commit but worth knowing for v1.9 surface review:
- Stoplight chrome accents (`SenseiApp._MODE_ACCENT` at sensei_tui.py:568) are untouched. Plan=`#cc0000`, Review=`#c7761a`, Auto=`#1a7a3a`. Do NOT re-tune.
- `_show_tui_credit_roll()` at master_ai.py:7191 still doesn't print MODE/MODEL — by intent, it's the brand login screen. Adding mode/model there was discussed and dropped in favor of the live status bar.
- `MODE_FILE` / `_load_saved_mode()` chain unchanged — chrome syncs to persisted mode at startup via `_SENSEI_APP.set_mode(MODE)` at master_ai.py:211.

## Recent Cleanup Safety Update (2026-04-28)

Elijah asked Sensei to clean up/shrink the PC, then clarified the durable rule: Sensei must be able to clean safely without deleting necessary files or Downloads.

Implemented in two layers:

1. **Model instruction in `Modelfile-master-ai`** — new `CLEANUP SAFETY` rule. Cleanup must start with audit commands (`df -h`, `du`, large-file `find`, process checks). Safe targets are Trash, `~/.cache`, browser cache folders, package caches, `__pycache__`, verified old tool versions, and logs with retention. Preserve `~/Downloads`, `~/Desktop`, `~/Documents`, project folders, git repos, app folders, Ollama models, Stable Diffusion models, photos, videos, archives, installers, and personal files unless Elijah explicitly names the exact path.

2. **Runtime guard in `master_ai.py`** — new `_cleanup_safety_issue(cmd)` blocks broad cleanup deletes that touch protected paths or use home-wide `find ~ ... -delete` without narrowing to cache/trash. It allows obvious cache/trash deletes such as `~/.cache`, Trash, and `__pycache__` cleanup. `confirm_run()` now refuses blocked cleanup commands before sudo/destructive approval paths.

Verification: `python3 -m py_compile master_ai.py` ✓, targeted guard smoke test blocks `rm -rf ~/Downloads/*`, `rm -rf /home/elijah/Documents/old`, `find ~ -type f -size +100M -delete`, and `rm -rf /home/elijah/scripts/*`; allows cache/trash cleanup. `test_master_ai_parser.py` remains 9/9. Rebuilt Sensei model with `ollama create master-ai -f /home/elijah/scripts/Modelfile-master-ai`; current `master-ai:latest` ID is `54dce4dd38cd`.

## Recent Committed Work (2026-04-27)

Commit `2842240 Save system query fixes` saved these work units:

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
