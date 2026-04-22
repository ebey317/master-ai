# Master AI — Layer Map

**What this doc is:** every file in `~/scripts/` labeled with which of the four product layers it belongs to. Uses the reviewer's proposed layering (Runtime / Agent / UI / Access) applied to the code that actually exists today.

**Honest note up top:** today `master_ai.py` is a monolith — it fuses Layer 1 (the runtime: orchestrator, memory, tool execution) with Layer 2 (the Sensei agent: tmux UI, readline, status bar, keyboard handling). The reviewer's clean separation is a *description you could sell from* more than a refactor map. Everything works as-is; no code has to move. If you ever want to split `master_ai.py` into `master_ai_core.py` + `sensei.py`, this map shows you where the seams naturally run.

---

## Layer 1 — Runtime (Master AI Core)

The engine. What a buyer means when they say "my AI." Handles: picking the right brain, storing memory, running tools, writing the audit log, serving data to every UI. Would survive if Sensei and Pupil both disappeared — this is the ONE piece nothing else can live without.

| File | Role |
|---|---|
| `master_ai.py` (L100–900, L2660–3100) | Core engine: `orchestrate()` routing, `ask_local()/ask_cloud()` bridges, memory store, tool execution (`confirm_run`, `confirm_create`, `confirm_edit`), permission layer (`_audit`, `_sudo_handoff`, `_cwd_fence_ok`, `_safe_input`), session save/resume |
| `sensei_reasoning_loop.py` | 4-stage reasoning pipeline (Planner → Solver → Critic → Finalizer) — called by the `think:` prefix in the agent layer but is pure runtime logic |
| `stt_server.py` | HTTP API server on `:8080` — serves `/keys`, `/sessions`, `/profile`, `/project_summary`, `/node_info`, `/peers`. Used by Pupil AND Mesh AND Sensei |
| `tts_server.py` | Voice synthesis service on `:5050` — Piper TTS, POST-only API |
| `master_ai_voice.json` | Voice / copy source of truth — idle tips, brand quotes, thinking phrases. Consumed by every UI |
| `~/.master_ai_audit.log` | Audit trail (written by `_audit()` in master_ai.py) |
| `~/.master_ai_memory`, `~/.master_ai_cache.json` | Persistent memory + response cache |
| `~/.master_ai_approved` | Auto-approved commands list |

**Docs that describe Layer 1:**
- `MODEL_ROUTING.md` — what every request routes to and why
- `SENSEI_REASONING_LOOP.md` — the 4-stage think pipeline spec
- `SUDO_MAP.md` — the finite set of privileged operations

---

## Layer 2 — Agent (Sensei)

The tmux terminal experience. Your "operator console." Handles: readline input, command parsing, slash-commands, status bar, mode switching (safe / plan / auto), drift reminders, scroll control, idle thoughts, the 4-button confirmation UI.

| File | Role |
|---|---|
| `master_ai.py` (L900–2650, L3100–5000) | Agent UI: main input loop, command parser (`hub`, `help`, `projects`, `tts`, `mode`, `task add`, etc.), status bar render, drift reminder, idle thought cloud, 5-button confirm UI |
| `launch_master_ai.sh` | Spawns master_ai.py inside tmux with supervisor loop (auto-restart on exit 42) |
| `master_ai_kick.sh` | Hard rebuild — tmux kill-session + fresh launch |
| `master_ai_refresh.sh` | Soft kill + respawn — preserves session state |
| `master_ai_autostart.sh` | Login-time autostart |
| `dojo_gate.sh` | Entry ritual — picks project + task + model before Sensei opens |
| `dojo_gate_test.sh` | Gate regression tests |
| `brand.sh` | ASCII ninja banners, color themes (BC/BG/BW for light-terminal rule) |
| `inject_memory.sh`, `save_context.sh` | Memory injection + session persistence helpers |
| `sensei_tui.py` | Alt TUI experiment (not primary UI) |
| `.sensei_behavior.md` | Behavior contract loaded into system prompts every request |
| `~/.master_ai_creator` | Creator-bypass flag for dojo gate |
| `~/.master_ai_active_project`, `~/.master_ai_active_task`, `~/.master_ai_active_model` | Written by dojo_gate, read by Sensei |

---

## Layer 3 — UI (Pupil)

The browser experience. Your "apprentice window." Handles: chat with project context, lesson chains (Bash 1–6, Python 1–6), RAM bar, paperwork briefings, localStorage-namespaced per-profile history, auto-speak, martial-arts belt themes, idle thought rotation, projects ▾ dropdown, any-key API-key finder.

| File | Role |
|---|---|
| `pupil.html` | The whole UI — single ~1200-line HTML with embedded JS + CSS |
| `stt_server.py` | **DUAL-ROLE**: also serves Pupil's API (`/chat`, `/sessions`, `/keys`, `/project_summary`, `/thoughts`, `/sys`). Listed here as consumer even though it lives in Layer 1 |
| `slideshow.html` | Click-and-read buyer onboarding (product tour) |
| `learn.sh` | Dojo Bash Tutor + Python lessons CLI — runs in terminal, but is the curriculum Layer 3 orchestrates |
| `README_FOR_BUYER.md` | First-run reading material |

---

## Layer 4 — Access (Remote)

How the product reaches you when you're not at the machine. Handles: phone access via Tailscale, peer-to-peer mesh between machines, remote key rotation.

| File | Role |
|---|---|
| `mesh.sh` | Mesh CLI — `ls / add / remove / ping / menu`. Calls peer's `/node_info` over HTTP |
| `~/.master_ai_mesh.json` | Mesh address book — this node's name + peers list |
| `stt_server.py` endpoints | `/node_info` (this node announces itself), `/peers` (list peers) — listed here as cross-layer consumer |
| `update_keys.sh` | Rotate cloud API keys from a separate terminal |
| Tailscale (external) | Provides the secure tunnel the whole product assumes exists when buyer wants multi-device access |

---

## Orchestration / Entry points

Not a layer — the dispatcher that picks which layer to launch.

| File | Role |
|---|---|
| `master.sh` | Top-level menu (20 options). Every launch goes through here |
| `install.sh` | First-run setup — models, services, API key prompts, cross-platform branches |
| `uninstall.sh` | Reverse of install |
| `pack_for_sale.sh` | Ship ritual — scrubs personal data, seals dojo gate, writes MANIFEST.txt |

---

## Operations (maintenance / health)

Not layer-specific — things you run now and then to keep the product healthy.

| File | Role |
|---|---|
| `master_ai_archive.sh` | Rotates logs, gzips old chats (daily 03:30 systemd timer) |
| `cleanup.sh` | On-demand housekeeping |
| `backup.sh`, `pre_upgrade_backup.sh` | Full-system backup before RAM/NVMe swap |
| `fix_ollama_host.sh` | Patches Ollama host binding if broken |
| `system_tune.sh` | PC Clean + tune-up (menu option 12) |
| `selfscan.sh` | What-your-box-can-run self-scan (menu option 19) |
| `check_key_expiry.sh` | Warns when a cloud API key is about to expire |

---

## Sudo palace (password-gated — added 2026-04-19)

The finite, documented list of operations that need root.

| File | Role |
|---|---|
| `apply_ollama_cap.sh` | S01 — caps Ollama at one model in RAM (applied) |
| `apply_user_linger.sh` | S02 — enables systemd user lingering (already on) |
| `apply_ufw_ports.sh` | S03 — opens LAN ports if ufw is active (ufw off here; no-op) |
| `SUDO_MAP.md` | Living doc of every entry |

---

## Tests / benchmarks

| File | Role |
|---|---|
| `sensei_selftest.sh` | End-to-end Sensei self-test (deliberately NOT run per Elijah's "save it for last" rule) |
| `multiuser_test.sh` | Multi-user plumbing regression (18 PASS / 0 FAIL) |
| `dojo_gate_test.sh` | Gate regression (14 PASS / 0 FAIL) |
| `benchmark_sensei.sh` | Sensei throughput benchmark |
| `competitor_benchmark.sh` | Compare against cloud-only baselines |
| `endurance_day.sh` | Long-run stability test |

---

## Archived (on disk, NOT wired)

Kept for reference or potential un-archival — none have active entry points.

| File | Why archived |
|---|---|
| `chunker.sh`, `chunker-test.sh` | Chunker concept archived 2026-04-19 — "a leaf falling off a tree" (memory: `project_chunked_workflow.md`). Scripts retained; no menu, no alias, no lesson, no symlink. **Do not un-archive without Elijah's permission.** |
| `~/scripts/archive/master_ai.html.deprecated` | Old browser chat — replaced by Pupil |
| `Modelfile-master-ai` | Old 14B model definition — removed 2026-04-19 |
| `serve_ui.sh.disabled` | Inactive UI server |

---

## The seams (if you ever split the monolith)

If you want to turn the reviewer's "clean 4-layer architecture" into code and not just docs, these are where `master_ai.py` naturally splits:

- **`master_ai_core.py`** (Layer 1) — extract: `orchestrate()`, `ask_local()`, `ask_cloud_*()`, memory load/save, `confirm_run/create/edit`, `_audit`, `_sudo_handoff`, `_cwd_fence_ok`, `_safe_input`, session save/resume, `_load_active_from_gate()`, all the directive parsing.
- **`sensei.py`** (Layer 2) — extract: `main()` input loop, command parser, status bar, drift reminder, idle thought cloud, scroll/tmux controls, mode switching, slide-show / hub / help / projects renderers.

The runtime file would be importable by Pupil, Mesh, or any future UI. The agent file would be the "human at the terminal" experience. Right now the line between them is a comment header inside `master_ai.py` — not a file boundary.

**Not recommending you do this today.** It works as-is. This doc just shows where the seams live if a buyer or contributor ever asks "where's the core vs the UI?"
