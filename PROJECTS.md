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
