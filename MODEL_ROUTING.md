# Master AI — Model Routing

**What this doc is:** the exact rules Sensei uses to decide which AI brain answers each message. Source of truth: `orchestrate()` in `master_ai.py:729`. If you change the router there, update this doc.

## The big idea

When you type a message, Sensei doesn't just send it to one AI. It reads your message, checks a few things about it, and picks the RIGHT brain for the job. Small brains for small questions, big brains for hard ones, vision brains for pictures, specialist brains for survival knowledge. The goal is fast answers when fast is fine, and accurate answers when the question is hard.

## The two product modes

Sensei has two overall moods. You pick which one in `~/.master_ai_run_mode`.

| Mode | Default? | How it thinks |
|---|---|---|
| **Local Mode** (code name: `apocalypse`) | yes | Every answer comes from a brain on YOUR computer. Cloud brains only run if you explicitly ask for one. Works with no internet. This is the default because Master AI has to keep working when the world goes dark. |
| **Connected Mode** (code name: `peacetime`) | no — opt-in | If you have cloud API keys saved, Sensei prefers cloud brains because they're faster (Groq is ~400 tokens/second vs ~5 tokens/second local). Still falls back to local if cloud fails. |

**How to switch:** type `mode connected` or `mode local` inside Sensei.

## The decision ladder (first match wins)

Sensei walks through these checks in order. The FIRST one that matches picks the brain. If nothing matches, it falls through to the last default.

### 1. Context pressure — save & refresh

**Check:** total chat history ≥ 60,000 characters.
**Action:** snapshot the conversation, re-exec Sensei, auto-resume with the snapshot loaded.
**Why:** if Sensei is packing too much history into every API call, answers get slow and sometimes truncate. This keeps the conversation fresh without losing what you've said.

### 2. Explicit prefix — you override the router

You can force any route by starting your message with a prefix. These ALWAYS win.

| Prefix | Route | Brain | Example |
|---|---|---|---|
| `fast:` | Cloud | Groq (Llama 3.3 70B) | `fast: what's 2+2?` |
| `deep:` | Cloud | DeepSeek-R1 (if OpenRouter key) or qwen3.5:cloud | `deep: explain recursion` |
| `local:` | Local | qwen2.5:7b (brain) | `local: private question` |
| `private:` | Local | qwen2.5:7b (brain) | `private: personal stuff` |

### 3. Vision — picture or camera-related word

**Check:** image attached, or words like "look", "photo", "picture", "see", "camera", "image", "scan" in your message.
**Action:**
- Local Mode → `llava:latest` (local vision brain)
- Connected Mode with Gemini key → Gemini 2.0 Flash (cloud vision)
- No Gemini key → falls back to `llava:latest`

### 4. Ambiguous — ask the user

**Check:** your message is a single lone pronoun ("it", "that"), a bare action verb ("go", "fix"), or a "did you mean" clarification.
**Action:** Sensei asks you what you meant before committing to a brain.

### 5. Memory recall — explicit

**Check:** words like "remember", "what did we say", "earlier you mentioned".
**Action:** pull relevant bits from the chat cache and memory store, inject them into the question, then answer with the local 7B brain.

### 6. Scope check — vague + ambitious build requests

**Check:** you said something like "build me a..." without specifying what the thing does, inputs, or success criteria.
**Action:** Sensei asks clarifying questions before wasting a reasoning cycle on a moving target.

### 7. Connected Mode (if that mode is on AND you have a cloud key)

These fire only in Connected Mode. Local Mode skips them.

| Your message looks like | Brain picked |
|---|---|
| Has reasoning words ("why", "explain", "because", "debug") or complex words | DeepSeek-R1 (if OpenRouter key) or qwen3.5:cloud |
| Anything else | Groq (fastest free cloud) |

### 8. Survival / off-grid — Scrappy specialist

**Check:** words like "purify water", "build shelter", "rebuild from scratch", "from scrap", AND a `scrappy`-tagged model is pulled in Ollama.
**Action:** route to Scrappy. Works in BOTH modes — survival answers don't need the cloud because the specialist IS the strongest path.

### 9. Local Mode ladder (apocalypse path)

These fire in Local Mode (and as fallback in Connected Mode when no cloud key works).

| Your message looks like | Brain picked |
|---|---|
| Code keywords ("function", "bug", "script", "bash", "python", etc.) | `qwen2.5-coder:7b` — code specialist |
| Reasoning words or complex words | `qwen2.5:14b` if pulled, else `qwen2.5:7b` |
| Long message (> 100 words) | `qwen2.5:14b` if pulled, else `qwen2.5:7b` |
| Short message (≤ 20 words) | `qwen2.5:3b` — spark (fast for quick answers) |
| Anything else | `qwen2.5:7b` — brain (the default daily driver) |

## The brain catalog

| Name in this doc | Ollama tag | Size | Role |
|---|---|---|---|
| **Spark** | `qwen2.5:3b` | 1.9 GB | fast quick answers, idle thoughts, briefings |
| **Brain** | `qwen2.5:7b` | 4.7 GB | daily driver — chat, reasoning, general purpose |
| **Coder** | `qwen2.5-coder:7b` | 4.7 GB | code questions, bash/python/shell |
| **Eyes** | `llava:latest` | 4.7 GB | vision — images, scanners, multimodal |
| **Big brain** (optional) | `qwen2.5:14b` | ~8 GB | long / deep questions IF pulled |
| **Scrappy** (optional) | any `*scrappy*` tag | varies | survival / off-grid specialist IF pulled |
| **Cloud fast** | Groq (Llama 3.3 70B) | — | `fast:` prefix; Connected Mode default |
| **Cloud deep (primary)** | DeepSeek-R1 via OpenRouter | — | `deep:` prefix; reasoning in Connected Mode |
| **Cloud deep (fallback)** | `qwen3.5:cloud` (397B free) | — | when no OpenRouter key |
| **Cloud vision** | Gemini 2.0 Flash | — | vision in Connected Mode with Gemini key |

## Special: the reasoning loop

Separate from the router above. Type `think:` / `think fast:` / `think deep:` to run the **Sensei Reasoning Loop** — a 4-stage pipeline (Planner → Solver → Critic → Finalizer) that forces a small model to do multi-pass cognition. See `~/scripts/SENSEI_REASONING_LOOP.md`.

The reasoning loop uses local brains by default (`qwen2.5:7b` for planner/solver/critic, `qwen2.5:3b` for finalizer). It does NOT go through `orchestrate()` — it runs its own pipeline.

## Worked examples

| You type | Mode | Routed to | Why |
|---|---|---|---|
| `fast: what's the capital of France?` | either | Groq | explicit `fast:` prefix |
| `what's in this photo` (with image) | Local | llava | vision keyword + image |
| `what's in this photo` (with image) | Connected + Gemini key | Gemini 2.0 Flash | vision keyword in Connected Mode |
| `it` | either | ask_user | single pronoun, ambiguous |
| `remember what we said about ports yesterday` | either | recall_memory → 7b | explicit recall trigger |
| `build me a REST API` (no details) | either | scope_check | vague + ambitious |
| `why does my bash pipefail act weird` | Local | qwen2.5-coder:7b | code keywords |
| `hi` | Local | qwen2.5:3b (spark) | short (≤ 20 words) |
| `write a 500-word essay on stoicism` | Local | qwen2.5:14b or 7b | long message |
| `purify water` (Scrappy pulled) | either | Scrappy | survival keyword + model present |
| `think: why does my regex not match` | either | reasoning loop | `think:` prefix |

## How to see WHICH brain answered

Every routed request logs one line to `~/scripts/master.log`. Sample:
```
[timestamp] ORCHESTRATE: local | code → qwen2.5-coder:7b (local)
[timestamp] ROUTE: local | code → qwen2.5-coder:7b (local)
```

The `reason:` field is human-readable — open the log and you can always trace why any answer went where.
