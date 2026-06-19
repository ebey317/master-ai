# Master AI — Local-First Agent Stack

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> A modular AI agent runtime that routes tasks between local Ollama models and cloud APIs, with persistent state, tool safety gates, and subagent orchestration.

**Local-first computer agent with optional cloud escalation.**

## Features

- **Smart Routing** — Automatically routes tasks to local models (90%) or cloud APIs based on complexity
- **Symbol-Aware Context Slicing** — Extracts relevant code symbols instead of dumping entire files
- **Typed Action Envelopes** — Structured `RUN`, `READ`, `CREATE`, `EDIT` commands with JSON audit trail
- **Hook System** — Pre/post tool events with configurable blocking
- **Subagent Registry** — 6 built-in specialists: `code_reviewer`, `context_inspector`, `file_finder`, `spend_reporter`, `test_runner`, `directive_simulator`
- **Safety Gates** — Read fences block secret paths, approval TTL prevents stale permissions
- **Deterministic Short-Circuits** — Weather, file-find, port checks, service status bypass the LLM for instant results

## Components

| Component | Description |
|-----------|-------------|
| **Sensei** | tmux-based terminal agent (`master_ai.py`) |
| **Pupil** | Browser UI for visual interaction (`pupil.html`) |
| **Dojo** | Optional project/task picker |

## Architecture

```
User Input
    │
    ▼
┌─────────────────────────────────────────────────┐
│  Router (router.route)                          │
│  ├─ system_query → deterministic short-circuit  │
│  ├─ local → Ollama (qwen2.5-coder, hermes3)    │
│  ├─ cloud_fast → Groq (free, fast)             │
│  ├─ cloud_reason → DeepSeek-R1 / OpenRouter    │
│  └─ cloud_web → Gemini (live facts)            │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│  Typed Actions (typed_actions.py)               │
│  RUN: / RUNTERM: / READ: / CREATE: / EDIT:     │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│  Safety Gates                                   │
│  ├─ _read_path_ok (blocks secrets, symlinks)   │
│  ├─ _cleanup_safety_issue (protects ~/Downloads)│
│  ├─ _hallucination_warn (blocks fake commands) │
│  └─ confirm_run (approval TTL + cwd tracking)  │
└─────────────────────────────────────────────────┘
    │
    ▼
  Execution + Audit Log (~/.master_ai_audit_typed.jsonl)
```

## Quick Start

```bash
# Clone
git clone https://github.com/ebey317/master-ai.git
cd master-ai

# Install dependencies
pip install -r requirements.txt

# Run Sensei (terminal agent)
python3 master_ai.py

# Or use the launcher
bash launch_master_ai.sh
```

## Configuration

Environment variables (all optional):

| Variable | Default | Description |
|----------|---------|-------------|
| `MASTER_AI_MODE` | `auto` | `plan`, `review`, or `auto` |
| `MASTER_AI_MODEL` | `auto` | Force specific model or `auto` for routing |
| `GROQ_API_KEY` | — | Enable Groq cloud tier |
| `OPENROUTER_API_KEY` | — | Enable DeepSeek-R1 reasoning |
| `GEMINI_API_KEY` | — | Enable live web facts |

## Commands

```
fast:   Route to fast cloud model (Groq)
deep:   Route to reasoning model (DeepSeek-R1)
local:  Force local Ollama
tight:  Concise reasoning mode
think:  Extended reasoning with chain-of-thought

stats   Show router metrics
doctor  Health check
hub     Command menu
```

## Standards Score

Current: **95/100** (17 PASS, 2 WARN, 0 FAIL)

Remaining WARNs are honest:
- `typed tool boundary` — dispatch still regex-parses free text (typed envelope is shadow-only)
- `sandbox boundary` — shell runs on user machine without process isolation

## Related Projects

- **[CLAF](https://github.com/ebey317/claf)** — Closed-Loop Agent Framework (Anthropic-skin proxy for local Ollama)
- **[AI Controller](https://github.com/ebey317/-AI-controller.)** — Voice-first desktop control with Xbox controller

## License

MIT — see [LICENSE](LICENSE)
