# Master AI

**Master AI is a local AI operating layer that turns your machine into an agent system with memory, coding ability, and tool execution — fully offline, with optional cloud acceleration.**

One product. Two doors:

- **Sensei** — the terminal side. Reads files, writes files, runs commands, remembers your projects.
- **Pupil** — the browser side. Brainstorm, learn, chat, check project status.

Same brain. Same memory. Same keys. Two surfaces so you can work how you work.

> **What you actually have:** your own AI, on your own hardware. It *knows you* — remembers your projects, reads your files, runs commands, builds apps, helps you study. Works fully offline. When you want cloud speed, it's one prefix away. *It's basically having a genius right next to you.*

> **The shift:** Master AI isn't another chat app. It's the moment you stop *using* a computer and start *programming* one.

---

## What's in the box

- **Sensei + Pupil** — the two doors above.
- **Menu (`master.sh`)** — front door to every feature, 20+ options.
- **Local model runtime (Ollama)** — ships with the trifecta: 3B spark (instant), 7B brain (daily driver), llava (vision). Unlimited. Private. Free.
- **Cloud acceleration (optional)** — paste a free Groq / OpenRouter / Gemini key and one-word prefixes route speed-critical asks to 70B+ cloud models.
- **Remote access** — phone-to-desktop bridge via Tailscale.
- **Self-scan** — tells you what your hardware can run before you ask.
- **Multi-user profiles** — up to 4 people per box, each with their own memory.
- **Curriculum** (included, not required) — 12 belt-graded lessons for Linux + Python.

Store/support docs are included in the bundle:

- `PRIVACY.md` — what stays local, when cloud is used, what is never collected.
- `SUPPORT.md` — first checks, common fixes, and what to include in a support request.
- `STORE_READINESS.md` — the release gate used before a buyer bundle is packed.

---

## 5-minute quickstart

```bash
master
```

You can also open the terminal agent directly:

```bash
sensei
```

Fallback if your shell PATH is not refreshed yet:

```bash
bash ~/scripts/master.sh
```

This opens the main menu. Hit **1** to start all services, then **5** to open Pupil in your browser. That's it.

If you're comfortable in a terminal, hit **4** instead — that's Sensei, the agent.

**Before first launch** — run `menu 19` (self-scan). It reads your machine and tells you which models will run comfortably (green / yellow / orange / red). If you have **24+ GB RAM**, the installer also offers the 14B "big brain" model — that's the tier where Sensei stops feeling small.

**Every URL you might need** — `menu 20` (download links): Ollama install, model pulls, free API keys, Tailscale, RustDesk. Also at `~/scripts/LINKS.md`.

---

## What each menu option does

| # | Option | What it does | When to use it |
|---|---|---|---|
| **1** | Full startup (all services) | Starts Ollama + Sensei + Pupil + Remote UI in one shot | First boot of the day, or after a reboot |
| **2** | Check Ollama | Verifies the local model runtime is responding | If AI feels offline / unresponsive |
| **3** | Check RustDesk | Verifies remote-desktop access is up | If remoting in from another device |
| **4** | Sensei (local) | The terminal AI agent. Opens immediately; project/task pinning is optional | When you want to *build* something |
| **5** | Pupil (local) | The browser AI UI. Open for brainstorm, learn, chat | When you want to *think* or *learn* something |
| **6** | Remote (connect to another node) | Prints your IPs + ports + URLs a second device would use | When setting up phone / second computer |
| **7** | Restart Sensei (force rebuild) | Kills and restarts the tmux session | If Sensei gets stuck |
| **8** | View chat sessions | Browse saved conversations from Pupil and Sensei | Reviewing past work |
| **9** | Log a new idea / POC | Captures an idea into `PROJECTS.md` under "Ideas / POCs" | When a thought strikes — don't lose it |
| **10** | How we work | Opens this doc's cousin (`howwework.txt`) for philosophy / style notes | For the long-form read |
| **11** | Update API keys | Manage cloud API keys (Groq, OpenRouter, OpenAI, etc.) in `~/.master_ai_keys` | Adding or replacing a cloud key |
| **12** | PC Clean + tune-up | System maintenance (apt clean, log rotation, etc.) | Periodic housekeeping |
| **13** | Learn Python + Build AI | Guided curriculum: Linux/bash first, then Python | You want to level up your skills |
| **14** | Uninstall | Removes Master AI and its data | Nuclear option |
| **15** | Add User (multi-user profile) | Creates a separate profile with its own memory/sessions | Sharing the node with another person |
| **16** | Projects (view · pick one for Sensei) | Browse all project boards without launching Sensei | Just looking, or picking before you go in |

---

## When you open a project — the "warm up" moment

When you pick a project in Pupil (or send one to Sensei), the AI reads your past chats, your memory file, and your project notes before it answers.

**First time through feels slow.** Think of it like a cold car engine — the AI has to load its model into memory and scan your history. You might wait 10–30 seconds.

**Once it's warm, it's quick.** After that first message, replies come fast because the model stays in memory (Master AI keeps it warm for 30 minutes at a time).

If a response is taking forever, check that Ollama is running (menu 2). If it is, the AI is probably just thinking. Give it a beat.

---

## The dojo philosophy (optional project focus)

Sensei is not a casual chat. It's an **execution dojo** — you enter to *build*. Sensei now opens directly from menu 4. When you want tighter focus, open Projects, pick a project, and pin a task. That pinned task is shown in the status bar and referenced every ~3000 characters of chat as a drift check: *"still on: X?"*

This is intentional, but optional. Direct entry keeps the flow fast. Pinning a project keeps longer work anchored to what you came for.

Dojo remains available as a project picker and task pinner. It is no longer a hard gate.

---

## Talking to Sensei — command reference

Inside Sensei (menu 4), type these at the prompt:

| Command | What it does |
|---|---|
| `dojo` / `status` | Shows your pinned project + task |
| `dojo tasks` / `tasks open` | Lists all unchecked tasks for the active project |
| `done` | Marks the current task complete in `PROJECTS.md`, auto-pins the next one |
| `project <path>` | Sets a filesystem path as project context (injects file tree into AI) |
| `mode plan` / `mode review` / `mode auto` | Controls execution: plan drafts only, review asks per step, auto runs non-destructive work |
| `A` / `finish` | From a ready plan, hand off Plan → Review → Auto and finish the project flow |
| `fast: <message>` | One quick cloud answer through Groq when configured |
| `deep: <message>` | One reasoning answer through DeepSeek-R1/OpenRouter when configured |
| `tight: <hard question>` | Best reasoning lane: DeepSeek-R1 if available, local deep reasoning loop otherwise |
| `think: <hard question>` | Local multi-pass reasoning loop, no cloud and no command execution |
| `image: <prompt>` | Submit a local image job; Sensei replies with a job id and Pupil shows the result |
| `remember: <text>` | Saves a fact to long-term memory |
| `forget: <text>` | Removes a memory |
| `task add <text>` | Adds a side-task (not tied to PROJECTS.md boards) |
| `task list` | Shows side-tasks |
| `save session` | Writes this chat to a named file |
| `transcript` / `copy chat` | Saves the full transcript |
| `preview` / `open preview` | Opens the latest product file, preferring browser demos |
| `log` | Shows recent Sensei engine log lines |
| `clear cache` | Clears exact-response cache for fresh work |
| `load summary` | Re-injects the last session summary |
| `refresh` | Soft restart (preserves session) |
| `kick` | Hard restart (tmux rebuild) |
| `,` / `;` / `.` / `/` | Command buckets to explore |
| `hub` / `help` / `tips` | Slideshow walkthroughs |
| `help buckets` | Shows the punctuation teaser |
| `x` | Clean exit |

---

## Sensei input, copy, and shortcuts

Sensei's input box is pinned at the bottom. Mouse events do not write into it
or submit it; text changes only from typing, bracketed paste, or Enter.
Ctrl+C interrupts the current reply and saves the session.
The layout adapts to small terminals: at 70x24 it compacts the header/status
line, shortens the shortcut legend, hides idle tips, and keeps chat plus input
inside framed boxes.

Default mouse profile is local-copy mode: `SENSEI_MOUSE=0`. That leaves mouse
selection to the terminal, so normal drag-select copy works without Shift. For
phone/RustDesk scrolling, type `mouse remote` and then `refresh`. To go back,
type `mouse local` and `refresh`.

Useful shortcuts:

| Shortcut | Action |
|---|---|
Mouse mode is changed only by typed commands: `mouse local`, `mouse remote`,
`mouse status`, or `mouse toggle`.

---

## Talking to Pupil — the shape

Pupil is a browser UI. Open it from menu **5** (or directly at `http://localhost:8080/pupil.html`). First time, you'll see the **template panel**:

- 🧠 **Brainstorm** — scope and clarify an idea
- 🔧 **Debug** — diagnose before fixing
- 💬 **Chat** — free conversation, no template
- 📁 **Projects ▾** — pick one of your projects, or open a lesson:
    - 🥋 **Linux / Bash** (start here — Class 1, 2, 3)
    - 🎓 **Python Path** (after Linux — Class 1, 2, 3)
    - …plus your actual projects
- 📋 **Plan ▾** — Budget, Diet, Project scope, Travel, Custom plans

**Lessons** are real digital tests — 5 questions each, loose answer matching, hint/skip/next/exit commands. Progress persists in your browser.

**Belt themes** — Pupil supports martial-arts belt color themes: white, yellow, blue (default — Sensei match), green, purple, brown, black, plus a hacker-green mode. Switch in Settings.

**Idle thoughts** — after 30s of no activity, a soft 💭 bubble appears with a tip, rotating every 5s until you move or type.

**Any-key finder** — paste any API key into the 🔑 Any Key card and Pupil detects which provider it belongs to, files it, and syncs it to `~/.master_ai_keys` so Sensei sees it too.

---

## Remote access (the Tailscale wedge)

Master AI runs on **one** machine. But you want it available from your **phone**, your **laptop**, a **guest computer**. That's what Remote (menu 6) is for.

When you hit menu 6, Master AI prints:
- Your machine's hostname
- LAN IP
- Tailscale IP (if Tailscale is installed)
- All 4 ports served (`:8080` Pupil + keys, `:5173` Remote UI, `:11434` Ollama, `:5050` TTS)
- Copy-ready URLs for a second device

**Recommended setup for phone access:**
1. Install Tailscale on both this machine and your phone
2. Both devices log into the same Tailscale account (use a free account)
3. On your phone's browser, open: `http://<your-tailscale-ip>:8080/pupil.html`

Now your phone and your desktop share the same Sensei + Pupil instance. Same memory. Same sessions. Same keys.

**This is the product's core promise:** your AI, at every entry point you use, powered by hardware you own.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Pupil says "Ollama offline" | `systemctl start ollama` in a terminal |
| Sensei won't start | Menu option 7 (Force rebuild) |
| Drag-copy needs Shift | In Sensei, type `mouse local`, then `refresh` |
| Preview opens an old note | Type `preview`; it now prefers `.html` / `.htm` product files |
| Lost the template panel in Pupil | Type `menu` or `back` inside a lesson — panel returns |
| Keys not syncing between menu 11 and Pupil | Make sure you opened Pupil via `http://localhost:8080/pupil.html`, not `file://` — only the served version syncs |
| Forgot how a command works | Type `help` inside Sensei, or open this README |

---

## Straight talk: what your AI can touch

Your AI runs as **you** — your user account, your permissions. Not root. Not administrator. Same reach as anything you type into your own terminal. That's worth knowing up front, because the scary part of any AI isn't that it's smart — it's that it can reach your files without you watching.

**What it CAN do (because you can):**
- Read and write files in your home folder
- Run any command your user can run without a password
- Make web calls using the API keys you pasted in
- Start and stop your own background services (the ones under your user, not system-level)

**What it CAN'T do — OS-enforced, not bypassable:**
- Use `sudo` or install packages — you run those yourself in a separate terminal
- Touch system files, other users' folders, or networks you aren't on
- See, store, or ask for your password — the rule is hard-coded into `~/.sensei_behavior.md`, every mode, every prefix, every override
- Phone home to anyone — there is no "us" on the other end

**Before anything destructive** (`rm -rf`, `git reset --hard`, `systemctl stop`, force-push, `drop table`), Sensei pauses, shows you the exact command, and waits for your "yes." That gate is in `master_ai.py`'s `confirm_run()` and it runs in every mode including auto.

Auto mode also stops a generated command chain after the first failed or refused `RUN:`. Pipelines are executed with `bash -o pipefail`, so a failing command in the middle of a pipeline does not get hidden by a successful final command. Interactive viewers such as `less`, `vim`, `top`, and `htop` are blocked from `RUN:` and must use `RUNTERM:`.

**Every action is logged** to `~/.master_ai_audit.log` in plain text. You can `cat` it, `grep` it, back it up, hand it to an auditor. There is no hidden history, no encrypted journal, no "trust us" layer. What happened is on disk.

**If you ever feel the reach is too broad**, the approval queue at `~/scripts/approval_queue.py` is already on disk (dormant by default). Flip it on and every file write from every agent queues for your review instead of running straight through. You trade some speed for a harder gate. It's there when you want it.

---

## What Master AI is NOT

- Not a ChatGPT replacement — local model capability is smaller than GPT-4 or Claude. For raw reasoning, cloud wins. Master AI leans on cloud fallback (Groq / OpenRouter) when you want that edge, while still owning the stack.
- Not a cloud service — there is no backend we operate. The machine in front of you is the service.
- Not a telemetry-laden app — it doesn't phone home. What you type stays local (unless you explicitly use a cloud key for a specific request).

---

## What Master AI IS

Your AI, that you own. Hardware you bought. Models you pulled. Memory you wrote. Projects you build. Available from every device you own. No subscription. No middle-man.

Welcome to the dojo.
