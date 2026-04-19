# Elijah's Projects

> Authoritative list of everything Elijah is building on Madam-Mary.
> Ideas captured via `master.sh` menu option 9 auto-append to the bottom.

## Master AI (brand / umbrella)
- **Menu** — `~/scripts/master.sh` — top-level launcher, front door of the whole system
- **Sensei** — `~/scripts/master_ai.py` — tmux terminal AI agent (menu option 4)
- **Master AI Web Chat** — `~/scripts/master_ai.html` on `:8080` (served by `stt_server.py`)
- **TTS Server** — `~/scripts/tts_server.py` on `:5050` (Piper voices, backend)

## Live Apps (external)
- **Sunkissed Soul** — base44.com — flagship app; local stack is being built to eventually replace the paid hosting

## Local App Builds
- **SKS Hub Client (local)** — `~/Downloads/sunkissed-soul` on `:5173` (Vite) — test harness for wiring the local Ollama hub into the real base44 Sunkissed Soul
- **SKS Hub Server** — `~/sks_hub.py` — Flask LAN knowledge library (built, not running)
- **Team Assist** — `~/test-interface.py` — Ollama model routing + chat stats (built, not running)
- **ai-master.sh** — `~/master-ai/ai-master.sh` — lightweight bash Ollama wrapper

## Infrastructure
- **Ollama** — `:11434` — local LLM runtime (master-ai:latest, qwen2.5:14b, qwen2.5-coder:7b, llava, qwen3.5:cloud, kimi-k2.5:cloud)
  - system-wide `OLLAMA_KEEP_ALIVE=30m` via `/etc/systemd/system/ollama.service.d/keep-alive.conf`
  - pre-warm on login: `master-ai-prewarm.service` (user) — loads master-ai before first query
- **RustDesk** — remote access (ID 1808427068)

## Sensei config (behavior & routing)
- **Orchestrator** — `orchestrate()` in `~/scripts/master_ai.py` routes to the right model/path (local / cloud-deep / cloud-fast / vision / ask-user / recall-memory / save-refresh)
- **Behavior contract** — `~/.sensei_behavior.md` — loaded into system prompt; defines the one-at-a-time workflow, ask-before-guess rule, visible [thinking] markers
- **Idle thoughts** — 💭 tips appear after 15s idle, rotate every 5s
- **Session auto-resume** — on context pressure (60k chars), Sensei auto-snapshots + soft re-execs + reloads full history on restart

## Ideas / POCs
<!-- auto-appended by master.sh option 9 -->

### Master AI — Multi-User Node (captured 2026-04-18 brainstorm)
- **Pitch:** each Master AI instance supports up to 4 local users, each with their own accounts / memory / sessions, sharing the one Ollama runtime
- **Why 4:** keeps CPU/RAM per-user reasonable on Madam-Mary-class hardware; small group feel
- **Scope items:** local account setup (add user / switch user), per-user memory file, per-user session dir, Ollama check on startup
- **Touches:** master.sh menu (new "Users" section), master_ai.py (per-user paths via $USER or a sensei_user flag)
- **Status:** concept — next up after Sensei UI stabilizes

### Master AI Mesh — Node-to-Node Federation (captured 2026-04-18 brainstorm)
- **Pitch:** once a node has its 4 users, it can connect to other Master AI nodes (another 4 users each). A question asked on node A can route to a model/user on node B. Decentralized peer-network of personal AI instances
- **Why this matters:** breaks the single-user / single-machine ceiling without going to corporate cloud
- **Open questions:** discovery (LAN mDNS? Tailscale IPs? shared pubkey?), permissions (who can ask whose node?), routing rules (prefer local, fail over to peer)
- **Status:** vision — depends on multi-user node first

### Idea Manager — POC Merge/Delete/Track (captured 2026-04-18 brainstorm)
- **Pitch:** the `PROJECTS.md` Ideas / POCs section becomes a real little manager. Elijah can tell Sensei "merge ideas 1 and 3", "delete idea 2", "mark idea 5 as in-progress" — Sensei edits the file and keeps everything on track
- **Why:** vague ideas pile up; humans merge and prune. AI should understand the current state of the pile so suggestions stay coherent
- **Commands to wire:** `idea list`, `idea merge A B`, `idea delete N`, `idea status N <phase>`, `idea rename N "..."`
- **Status:** concept — small, high-leverage, probably first to actually implement

### AppForge — "app that makes apps" (captured 2026-04-18 brainstorm)
- **Pitch:** non-technical person describes what they want → wizard generates working code + sale-ready package
- **Elijah's core pains to solve:** (a) describing the idea clearly enough to get accurate code, (b) "what now?" after code exists (distribution, selling)
- **Output bundle user gets:** zip of runnable code + Gumroad listing scaffold + Android/iOS store submission checklist + sole-prop paperwork page
- **Stack vision:** start simple on phone (caches locally), syncs to desktop when back. Offline-first, uses local Ollama so it costs $0 to run
- **Evolution:** v1 = template-driven code gen, v2 = LLM-generated code, v3 = phone web UI + cloud sync
- **Scaffold on disk:** `~/scripts/appforge/` — forge.py wizard, Flask starter template (BUILD NOT STARTED — waiting for go-ahead)
- **Status:** POC / brainstorm phase
- **Philosophy note:** "this is just cosmetic — the real win is already having free offline AI that lets one person build a civilization in a terminal"
