# Master AI — Local-First Agent Stack

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> A modular AI agent runtime that routes tasks between local Ollama models and cloud APIs — with persistent state, typed action envelopes, safety gates, and subagent orchestration. Runs standalone on your hardware. No cloud account required for local mode.

**Local-first computer agent with optional cloud escalation.**

---

## Components

| Component | Entry point | Description |
|---|---|---|
| **Sensei** | `python3 master_ai.py` | tmux-based terminal agent with router, safety gates, and subagents |
| **Pupil** | `pupil.html` | Browser UI — visual interaction, image gen, metrics dashboard |
| **TTS Server** | `tts_server.py` | Local text-to-speech (edge-tts / piper) on port 5001 |
| **STT Server** | `stt_server.py` | Whisper speech-to-text HTTP server (Pupil `/voice`) |

---

## Architecture

```
User input (voice or text)
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  Router  (router.py)                                        │
│  ├─ system_query  → deterministic short-circuit             │
│  │   (file-find, port check, service status, weather)       │
│  ├─ local         → Ollama  (qwen2.5-coder, hermes3)       │
│  ├─ cloud_fast    → Groq    (free, fast — llama-3.3-70b)   │
│  ├─ cloud_reason  → DeepSeek-R1 / OpenRouter               │
│  └─ cloud_web     → Gemini  (live facts, web search)       │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  Typed Actions  (typed_actions.py)                          │
│  RUN: / RUNTERM: / READ: / CREATE: / EDIT:                 │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  Safety Gates  (master_ai.py)                               │
│  ├─ _read_path_ok       blocks secrets and symlink escapes  │
│  ├─ _cleanup_safety_issue  protects ~/Downloads, ~/Desktop  │
│  ├─ _hallucination_warn    blocks fake commands             │
│  └─ confirm_run         approval TTL + cwd tracking         │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
  Execution + Audit log  (~/.master_ai_audit_typed.jsonl)
```

---

## Features

- **Smart routing** — keywords, context length, and route history decide local vs cloud per turn
- **Symbol-aware context slicing** — pulls only the relevant `def`/`class`/`=` block instead of dumping the whole file
- **Typed action envelopes** — `RUN`, `RUNTERM`, `READ`, `CREATE`, `EDIT` with JSON audit trail
- **Hook system** — pre/post tool events; blocking hooks feed `[HOOK BLOCKED]` back into model history
- **Subagent registry** — 6 built-in specialists: `code_reviewer`, `context_inspector`, `file_finder`, `spend_reporter`, `test_runner`, `directive_simulator`
- **Deterministic short-circuits** — weather, file-find, port checks, service status, installed-package checks bypass the LLM for instant results
- **Per-route history budgets** — local context trim configured per route class to reduce drag without touching prompts
- **Reasoning surface** — `reason fast|standard|deep|max` routes to DeepSeek-R1 via OpenRouter; output is display-only, never executable

---

## Setup

### 1. Prerequisites

- Python 3.10+
- [Ollama](https://ollama.ai) installed and running: `ollama serve`
- A local model pulled: `ollama pull hermes3:3b` (fast) or `ollama pull qwen2.5-coder:latest` (capable)

### 2. Install

```bash
git clone https://github.com/ebey317/master-ai.git
cd master-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. System packages

```bash
sudo apt install mpv xdotool ffmpeg python3-gi gir1.2-gtk-3.0
pip install edge-tts          # TTS engine
```

Optional — Piper for offline TTS:

```bash
pip install piper-tts
# Download a voice: https://github.com/rhasspy/piper/releases
```

### 4. API keys (optional — local mode works without any)

Place cloud keys in `~/.master_ai_keys` (JSON or KEY=VALUE format):

```
GROQ_API_KEY=gsk_...
OPENROUTER_API_KEY=sk-or-...
GEMINI_API_KEY=AIza...
```

Keys are loaded at startup and projected into the env. The file is gitignored by design.

### 5. Run

```bash
# Terminal agent (Sensei)
python3 master_ai.py

# Or use the system command installed by the installer
sensei

# Pupil browser UI
open pupil.html    # or serve it: python3 -m http.server 8080
```

---

## Commands

Type these at the Sensei prompt:

```
# Routing prefixes
fast:   <prompt>    Route to Groq (fast cloud)
deep:   <prompt>    Route to DeepSeek-R1 (reasoning)
local:  <prompt>    Force local Ollama
tight:  <prompt>    Concise reasoning mode
think:  <prompt>    Extended chain-of-thought

# Navigation
hub                 Command menu
doctor              Health check — Ollama, models, keys, services
stats               Router metrics (routes used, latency, fallbacks)
agents              List subagents and run one
tasks               Task list

# Mode
mode plan           Read-only planning mode
mode review         Audit mode — no auto-exec
mode auto           Autonomous mode — executes with safety gates

# Model
model auto          Router decides per turn
model local         Pin to Ollama
model groq          Pin to Groq
```

---

## Safety standards score

Current: **95/100** (17 PASS, 2 WARN, 0 FAIL)

Remaining WARNs are intentionally honest:

| Item | Status | Reason |
|---|---|---|
| Typed tool boundary | WARN | Dispatch still regex-parses free model text; typed envelope is shadow-only |
| Sandbox boundary | WARN | Shell commands run on the user machine without process isolation |

Do not claim 100/100 until typed dispatch is end-to-end and real sandboxing exists.

Run the acceptance gate before any pack/sale:

```bash
python3 -m py_compile master_ai.py
python3 test_master_ai_parser.py
python3 test_master_ai_safety.py
bash sensei_selftest.sh
```

---

## Configuration reference

All variables are optional. Set in shell or in a sourced `.env`:

| Variable | Default | Description |
|---|---|---|
| `MASTER_AI_MODE` | `auto` | `plan`, `review`, or `auto` |
| `MASTER_AI_MODEL` | `auto` | Force model slug or `auto` for routing |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |
| `GROQ_API_KEY` | — | Enables Groq cloud tier (free) |
| `OPENROUTER_API_KEY` | — | Enables DeepSeek-R1 reasoning |
| `GEMINI_API_KEY` | — | Enables Gemini web/live-facts route |

---

## Subagents

Dispatch a specialist from the prompt or programmatically:

```
agents code_reviewer   Review the last edited file
agents file_finder     Find files matching a description
agents spend_reporter  Summarize token spend this session
```

From Python:

```python
from subagent_registry import run
result = run("code_reviewer", task="review router.py for logic bugs")
```

All subagent outputs are inert structured JSON — never executable directives.

---

## Related

- **[CLAF](https://github.com/ebey317/claf)** — Closed-Loop Agent Framework; redirects Claude Code's LLM calls to local Ollama
- **[AI Controller](https://github.com/ebey317/-AI-controller.)** — Xbox controller → voice → desktop control pipeline

---

## License

MIT — see [LICENSE](LICENSE)
