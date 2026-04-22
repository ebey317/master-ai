# Master AI — Download Links

Every URL a buyer could need, in one place. Verified 2026-04-19. Free tiers only;
no paid upgrades required for the product to work.

---

## 1. The engine (required)

**Ollama** — local AI runtime. Master AI won't start without it.

| OS               | How                                                             |
|------------------|-----------------------------------------------------------------|
| Linux (any)      | `curl -fsSL https://ollama.com/install.sh \| sh`                |
| macOS            | Installer: <https://ollama.com/download/mac>                    |
| Windows          | Installer: <https://ollama.com/download/windows>                |
| Windows (WSL2)   | Same as Linux — use the curl line inside WSL                    |

Homepage: <https://ollama.com>

---

## 2. The trifecta models (required — pull after installing Ollama)

Run these three `ollama pull` commands. Total ~11 GB on disk.

| Model          | Role                     | Disk    | Command                      |
|----------------|--------------------------|---------|------------------------------|
| `qwen2.5:3b`   | spark — instant replies  | ~1.9 GB | `ollama pull qwen2.5:3b`     |
| `qwen2.5:7b`   | brain — daily driver     | ~4.7 GB | `ollama pull qwen2.5:7b`     |
| `llava:latest` | eyes — vision + chat     | ~4.7 GB | `ollama pull llava:latest`   |

Optional local "big brain" — unlocks on **24+ GB RAM**. This is the productive floor for local work. On a 32 GB box, 14B stops feeling small. Pull when your hardware supports it:

| Model          | Role                             | Disk    | Command                       |
|----------------|----------------------------------|---------|-------------------------------|
| `qwen2.5:14b`  | big brain — deep reasoning       | ~9 GB   | `ollama pull qwen2.5:14b`     |

Optional cloud-routed tiers (free via Ollama's own cloud):

| Model              | Size   | Use                        |
|--------------------|--------|----------------------------|
| `qwen3.5:cloud`    | 397B   | deep reasoning             |
| `kimi-k2.5:cloud`  | ~1T    | heavy vision + reasoning   |

---

## 3. Free web search — NO KEY NEEDED (always on)

These run automatically whenever you ask a time-sensitive or factual
question. No signup, no rate-limit surprise. Master AI calls each one
and blends the results.

| Source                          | What it's good for                     | Limits                     |
|---------------------------------|----------------------------------------|----------------------------|
| **Wikipedia REST API**          | encyclopedic facts, people, definitions | unlimited (be reasonable) |
| **DuckDuckGo** (via `ddgs`)     | general web results                     | unlimited                 |
| **DuckDuckGo Instant Answer**   | structured quick-facts                  | unlimited                 |
| **WikiHow** (via Google filter) | "how to..." questions (needs Gemini key) | uses Gemini quota        |

## 4. Free cloud API keys (optional — each one adds a capability)

All free to sign up. Copy keys into Master AI via menu 11 (terminal) or the
🔑 Any Key button in Pupil (browser). Pupil auto-detects which provider a
pasted key belongs to — no "is this Groq?" questions.

### Tier A — directly used by the router today

| Provider       | Signup URL                                  | What you get                                              |
|----------------|---------------------------------------------|-----------------------------------------------------------|
| **Groq**       | <https://console.groq.com/keys>             | `fast:` prefix · Llama 3.3 70B at ~400 tok/s · daily quota |
| **OpenRouter** | <https://openrouter.ai/keys>                | `deep:` prefix · DeepSeek R1, Hermes 405B · one key, many models |
| **Gemini**     | <https://aistudio.google.com/app/apikey>    | Google grounded search · current-events accuracy · vision |

### Tier B — additional free options (more keys = more fallback paths)

| Provider          | Signup URL                                    | What it adds                                         |
|-------------------|-----------------------------------------------|------------------------------------------------------|
| **xAI / Grok**    | <https://console.x.ai/>                       | Free credits · recent training data · current events |
| **Cerebras**      | <https://cloud.cerebras.ai/>                  | Very fast Llama inference · free tier               |
| **Hugging Face**  | <https://huggingface.co/settings/tokens>      | Free inference API · thousands of open models        |
| **Together AI**   | <https://api.together.xyz/>                   | Free credits · open models · decent quota            |
| **Mistral**       | <https://console.mistral.ai/>                 | Mistral models · free tier                           |

### Tier C — search engines (opt-in alternatives to DDG)

| Provider              | Signup URL                                  | Why you'd add it                                |
|-----------------------|---------------------------------------------|--------------------------------------------------|
| **Brave Search API**  | <https://api.search.brave.com/>             | 2000/month free · often better than DDG for news |
| **Tavily**            | <https://tavily.com/>                       | Purpose-built for LLMs · pre-synthesized results |
| **Serper**            | <https://serper.dev/>                       | Google results · 100/day free                    |
| **SearchAPI**         | <https://www.searchapi.io/>                 | Multi-engine · free tier                         |

### Tier D — specialist / computational

| Provider            | Signup URL                                   | Why you'd add it                             |
|---------------------|----------------------------------------------|-----------------------------------------------|
| **Wolfram Alpha**   | <https://products.wolframalpha.com/api/>     | Math, dates, conversions · 2000/month free   |
| **Perplexity API**  | <https://www.perplexity.ai/pplx-api>         | Real-time search-backed synthesis · limited free |

**Rule of thumb:** every key you paste adds one more path for Sensei to
route through. You don't need them all. Tier A gets you the product.
Tier B–D are belt-and-suspenders for when a Tier A tier hits a rate limit
or when you want a specific style of answer.

---

## 4. Remote access (optional — access Master AI from your phone)

| Tool           | URL                                  | Why                                                     |
|----------------|--------------------------------------|---------------------------------------------------------|
| **Tailscale**  | <https://tailscale.com/download>     | Zero-config VPN — phone sees your home AI over the net  |
| **RustDesk**   | <https://rustdesk.com/>              | Remote desktop — drive the terminal from your phone     |

Pupil opens in any browser once Tailscale is set up:
`http://<your-tailscale-ip>:8080/pupil.html`

---

## 5. Python dependencies (install.sh handles these)

Only listed here in case you want to see what's running. Installed automatically
by `install.sh`:

- **openai-whisper** — speech-to-text for the mic button in Pupil.
- **piper-tts** — offline text-to-speech (voice replies).
- Voice pack: <https://huggingface.co/rhasspy/piper-voices> (lessac-medium is the default — installer pulls it).

Run manually if the installer missed:
```
pip3 install --user openai-whisper piper-tts
```

---

## 6. Source + updates

Master AI is shipped as a single folder (`~/scripts/`). No external "phone home"
check, no auto-updates. To upgrade, grab the newest bundle and re-run `install.sh`
— your memory/chats/keys persist in your home directory outside the folder.

The source is NOT a public GitHub repo; the bundle is the distribution channel.
If you want newer versions, check wherever you bought this (Gumroad / direct).

---

## 7. Support + community

- **Included docs**: `README_FOR_BUYER.md` (full manual) · `slideshow.html` (click-through tour) · `howwework.txt` (reference).
- **In-app help**: `menu 10` (How We Work) · inside Sensei type `help` · inside Pupil open the ? panel.
- **Self-scan**: `menu 19` (or `bash ~/scripts/selfscan.sh`) — tells you what your box can run.

---

*"Your AI. Every entry point. Your hardware."*
