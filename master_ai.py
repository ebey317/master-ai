#!/usr/bin/env python3
# ============================================================
# MASTER AI — AI Agent · Vision · Voice · Web · PC Control
# Machine: Madam-Mary | User: Elijah
# Run: python3 ~/scripts/master_ai.py
# ============================================================
#
# ── USER PROFILE ────────────────────────────────────────────
# The default user profile for Master AI. Shaped around Elijah's
# working style but generalizes to ~80% of buyers — the "workflow
# user" archetype (delegates heavily, wants execution, watches live
# while the AI works). Also loaded into Sensei's system prompt via
# ~/.sensei_behavior.md (section "Elijah specifically").
#
# HOW THEY WORK:
# - Voice-to-text input from a phone / remote keyboard. Expect
#   run-ons, typos ("pseudo" means sudo, "NDPY" means .py), cut-off
#   words, misspoken homophones. Read for INTENT, not syntax.
# - Offline-focused: typically in front of the machine while the AI
#   runs. Not away. Watches output as it streams. Catches issues in
#   real time; less worried about "it did something while I was AFK."
# - Auto mode flows — they accept speed-for-attention tradeoff.
#   Destructive commands still pause; everything else runs.
# - Long sessions: 11–16 hours at a time, mixing build + talk +
#   review. "Where were we" means "give me the full logbook" not a
#   one-line summary.
#
# HOW THEY READ OUR OUTPUT:
# - Slower than the AI generates. Expect scroll-back as the natural
#   review flow. Place important info near the END of replies so the
#   final lines carry the weight.
# - Sudo / bash handoff: they like seeing the EXACT command on its
#   own line, copy-able, with a one-line "why." Never embed sudo
#   inline in prose. Never pipe passwords. Always: "paste this into
#   another terminal, I'll wait."
# - Diff-style +/- lines are how they audit our changes. Show diffs
#   when you modify a file; don't just describe the change.
#
# HOW THEY SPEAK THE PRODUCT:
# - Mindset quote: *"I'm not using the computer, I'm programming it."*
# - The brand line: *"Your AI. Every entry point. Your hardware."*
# - They think of the AI as a "person inside the digital world" —
#   creator/master-commander framing. Respect the frame; don't
#   collapse into "assistant" or "helper" copy.
# - North Star: off-grid, self-sufficient, apocalypse-capable AI on
#   hardware they own. Not cloud. Not subscription. Not rented.
#
# PERSONALITY + TONE:
# - Direct. Honest. Not sugar-coated. When something is scary or
#   broken or uncertain, name it plainly.
# - Not a tutor. Not Socratic. Answer first, offer study links only
#   as footer.
# - Teach to a smart 16-year-old. "Use" not "utilize." "Run" not
#   "execute." Name mistakes before they happen.
# - Short beats long. One sentence beats five. Bullets beat prose
#   when listing options.
#
# Full canonical profile + quotes + voice rules: ~/.sensei_behavior.md
# ────────────────────────────────────────────────────────────

import os, sys, json, subprocess, tempfile, urllib.request, urllib.error
import base64, re, time, shutil, hashlib, platform, atexit, signal, threading, queue
from datetime import datetime
from pathlib import Path

try:
    import harvest  # local cache + few-shot injection; ~/scripts/harvest.py
except Exception:
    harvest = None

try:
    import readline
    _HIST = str(Path.home() / '.master_ai_history')
    try: readline.read_history_file(_HIST)
    except FileNotFoundError: pass
    readline.set_history_length(500)
    atexit.register(readline.write_history_file, _HIST)

    _COMPLETIONS = [
        "hub", "menu", "home", "help", "tips", "model", "model auto", "mode plan", "mode review", "mode auto",
        "mode", "memory", "remember:", "forget:", "task", "task add ", "task list",
        "task done ", "task clear", "tasks", "save session", "load summary", "copy chat", "copy session",
        "load session", "clear", "clear history", "clear cache", "clear approved", "clear chats",
        "chats", "refresh", "reload", "restart", "kick",
        "up", "down", "top", "bottom", "last",
        "projects", "apps", "autotips", "slideshow", "tour",
        "keys", "approved", "cache", "harvest", "perms", "tutorial", "hints on", "hints off",
        "tts on", "tts off", "tts",
        "hints", "project", "search ", "dl ", "gdrive ", "git", "git status",
        "git diff", "git log", "git commit ", "go", "cancel", "accessibility", "x",
        "how", "how we work", "hww",
    ]
    def _completer(text, state):
        matches = [c for c in _COMPLETIONS if c.startswith(text)]
        return matches[state] if state < len(matches) else None
    readline.set_completer(_completer)
    readline.parse_and_bind("tab: complete")
except ImportError:
    pass

# ── SENSEI TUI — full-screen app, default ON; opt out with SENSEI_TUI=0 ──
_SENSEI_APP = None
_SENSEI_ENABLED = os.environ.get("SENSEI_TUI", "1") != "0"
if _SENSEI_ENABLED:
    try:
        from sensei_tui import SenseiApp
        _SENSEI_APP = SenseiApp()
    except Exception as _e:
        _SENSEI_APP = None
        _SENSEI_ENABLED = False

# ── PROFILE-AWARE PATHS ──────────────────────────────────────
# If ~/.master_ai_active_profile exists AND names a profile dir under
# ~/.master_ai_profiles/<name>/, all personal state (memory, chats,
# tasks, approved commands, cache) rebases there. Otherwise the
# legacy global paths in $HOME are used (backward-compat).
#
# KEYS_FILE stays global on purpose — keys are a SHARED resource
# across profiles (per profile.json's "keys": true sharing flag).
# If a future profile wants private keys, that's a later toggle.
_ACTIVE_PROFILE_FILE = Path.home() / ".master_ai_active_profile"
_PROFILE_NAME = ""
try:
    if _ACTIVE_PROFILE_FILE.exists():
        _PROFILE_NAME = _ACTIVE_PROFILE_FILE.read_text().strip()
except Exception:
    _PROFILE_NAME = ""

if _PROFILE_NAME and (Path.home() / ".master_ai_profiles" / _PROFILE_NAME).is_dir():
    _PROFILE_ROOT = Path.home() / ".master_ai_profiles" / _PROFILE_NAME
else:
    _PROFILE_ROOT = Path.home()         # legacy / default profile
    _PROFILE_NAME = ""

def _pfile(name):
    """Per-profile dotfile path.
    For the legacy/default profile, uses ~/.master_ai_<name>.
    For a named profile, uses ~/.master_ai_profiles/<profile>/<name> (no dot prefix)."""
    if _PROFILE_NAME:
        return _PROFILE_ROOT / name
    return Path.home() / (".master_ai_" + name)

# ── CONFIG ───────────────────────────────────────────────────
KEYS_FILE     = Path.home() / ".master_ai_keys"            # SHARED across profiles
CHATS_DIR     = _PROFILE_ROOT / ("chats" if _PROFILE_NAME else ".master_ai_chats")
MEMORY_FILE   = _pfile("memory")
TASKS_FILE    = _pfile("tasks")
APPROVED_FILE = _pfile("approved")
PERMS_FILE    = _pfile("permissions_done")
CACHE_FILE    = _pfile("cache.json")
HINTS_FILE    = _pfile("hints_off")
TUTORIAL_FILE = _pfile("tutorial_done")
OLLAMA_URL    = "http://localhost:11434"
PIPER_MODEL   = Path.home() / "scripts/voices/en_US-lessac-medium.onnx"
LOG_FILE      = Path.home() / "scripts/master.log"
WHISPER_MODEL = "base"

# Make sure a named profile's directory skeleton exists so reads don't 404
if _PROFILE_NAME:
    try:
        CHATS_DIR.mkdir(parents=True, exist_ok=True)
        _PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

# ── MODE / PLAN STATE ────────────────────────────────────────
MODE_FILE            = Path.home() / ".master_ai_mode"  # persists last-selected mode across sessions

def _load_saved_mode():
    """Read persisted mode from disk. Returns 'plan' (default) if missing,
    unreadable, or not one of the three valid modes."""
    try:
        v = MODE_FILE.read_text().strip()
        return v if v in ("plan", "review", "auto") else "plan"
    except Exception:
        return "plan"

def save_mode(mode):
    """Persist current mode so reopening Sensei restores it.
    Silently skips if write fails — don't let filesystem issues crash."""
    if mode not in ("plan", "review", "auto"):
        return
    try:
        MODE_FILE.write_text(mode)
    except Exception:
        pass

MODE                 = _load_saved_mode()  # Plan is the default if no file exists. Review = per-command confirm; Auto = flow-through.
LAST_ROUTE           = ""      # route used by the most recent handle() — for Review's "who" line
LAST_MODEL           = ""      # model name used by the most recent handle() — for Review's "who" line
PENDING_PLAN_TEXT    = ""
PENDING_USER_NOTE    = ""
PENDING_PLAN_REQUEST = ""
HINTS                = 0 if HINTS_FILE.exists() else 1
ACTIVE_PROJECT       = ""
_SETTINGS            = Path.home() / ".master_ai_settings"
TTS_ENABLED          = "TTS_OFF" not in (_SETTINGS.read_text() if _SETTINGS.exists() else "")

MODELS = {
    # THE TRIFECTA (2026-04-19, master rebuilt 2026-04-21):
    #   fast    — qwen2.5:3b   (spark — instant, <1s, ~2 GB RAM)
    #   master  — master-ai    (custom: qwen2.5:7b + baked-in behavior SYSTEM)
    #   vision  — llava        (eyes — image + multimodal chat, ~5 GB RAM)
    # master-ai is built from ~/scripts/Modelfile-master-ai via `ollama create`.
    # SYSTEM is baked into the model so behavior rules, directive taxonomy,
    # senior-engineer habits, and save-path taxonomy are KV-cached once — no
    # per-turn prompt cost. Rebuild after editing the Modelfile:
    #   ollama create master-ai -f ~/scripts/Modelfile-master-ai
    "fast":    "qwen2.5:3b",       # spark — briefings, idle, quick answers
    "master":  "master-ai",        # primary — qwen2.5:7b + baked senior-engineer behavior
    "vision":  "llava",            # eyes — scrap scanner, apothecary
    "coder":   "master-ai",        # shared with master (same 7B base + rules)
    "general": "master-ai",
    "heavy":   "llava",            # text-capable local fallback
    "qwen3":   "qwen3.5:cloud",    # cloud — complex analysis
    "kimi":    "kimi-k2.5:cloud",  # cloud — best vision when online
}

# All models with labels for the picker menu
MODEL_MENU = [
    # ── LOCAL (your machine — private, free, no token limit) ──
    ("qwen2.5:3b",         "LOCAL  · 3B · spark · instant · briefings · quick answers"),
    ("qwen2.5:7b",         "LOCAL  · 7B · primary · code · chat · reasoning"),
    ("llava",              "LOCAL  · multimodal · vision + chat · scanner"),
    ("qwen3.5:cloud",      "LOCAL  · 397B · thinking · tools · vision"),
    ("kimi-k2.5:cloud",    "LOCAL  · 1T params · deep reasoning · vision"),
    # ── CLOUD (free tiers — tokens tracked) ──
    ("groq",               "☁ FREE · Llama 3.3 70B — fastest"),
    ("deepseek-r1",        "☁ FREE · DeepSeek R1 — reasoning"),
    ("hermes-405b",        "☁ FREE · Hermes 405B — biggest free model"),
    ("gpt-oss-120b",       "☁ FREE · GPT-OSS 120B — OpenAI open source"),
    ("nemotron",           "☁ FREE · Nemotron 120B — NVIDIA reasoning"),
    ("qwen3-coder",        "☁ FREE · Qwen3 Coder — cloud code upgrade"),
    ("gemini",             "☁ FREE · Gemini 2.0 Flash — research + web"),
]

PINNED_MODEL = None  # set by 'model' command to override auto-routing

# ── AUTO-SAVE STATE ───────────────────────────────────────────
GLOBAL_HISTORY      = []          # shared reference for signal handlers
CHARS_SINCE_SAVE    = 0           # chars accumulated since last auto-save
CHARS_SINCE_REMIND  = 0           # chars accumulated since last drift reminder
AUTO_SAVE_THRESHOLD = 10000       # update session file every ~10000 chars (was 3000)
# Drift-reminder: if the user rolls past this many chars without touching the
# active project label, Sensei injects a gentle 'hey, you were on X' reminder.
DRIFT_REMINDER_CHARS = 3000
SESSION_TS          = int(time.time())  # fixed for entire session — overwrites same file
_SAVE_LOCK          = threading.Lock()

# ── ORCHESTRATOR STATE ────────────────────────────────────────
CONTEXT_WATERMARK   = 120000                     # total history chars → save-and-refresh (doubled 2026-04-19 — was auto-restarting every few min with 60k)
BEHAVIOR_FILE       = Path.home() / ".sensei_behavior.md"
RESUME_FLAG         = Path.home() / ".master_ai_resume"

# ── DOJO GATE STATE (written by dojo_gate.sh before launch) ──
ACTIVE_PROJECT_FILE = Path.home() / ".master_ai_active_project"
ACTIVE_TASK_FILE    = Path.home() / ".master_ai_active_task"
ACTIVE_MODEL_FILE   = Path.home() / ".master_ai_active_model"
ACTIVE_TASK         = ""
PROJECTS_MD_FILE    = Path.home() / "scripts" / "PROJECTS.md"

def _load_active_from_gate():
    """Pull project + task + model set by dojo_gate.sh into globals.
    Empty model file = auto-router stays active (PINNED_MODEL untouched)."""
    try:
        if ACTIVE_PROJECT_FILE.exists():
            proj = ACTIVE_PROJECT_FILE.read_text().strip()
            if proj:
                globals()['ACTIVE_PROJECT'] = proj
        if ACTIVE_TASK_FILE.exists():
            task = ACTIVE_TASK_FILE.read_text().strip()
            if task:
                globals()['ACTIVE_TASK'] = task
        if ACTIVE_MODEL_FILE.exists():
            mdl = ACTIVE_MODEL_FILE.read_text().strip()
            if mdl:
                globals()['PINNED_MODEL'] = mdl
    except Exception:
        pass

_load_active_from_gate()

# ── PROJECTS.md task-board helpers ──
# The dojo gate writes checkbox task lists under "### <Project>" headings inside
# the "## Project Boards" section of PROJECTS.md. Sensei edits them in place
# when a task is marked done.

def _dojo_unchecked(project):
    """Return list of unchecked task strings for the given project name."""
    if not project or not PROJECTS_MD_FILE.exists():
        return []
    try:
        lines = PROJECTS_MD_FILE.read_text().splitlines()
    except Exception:
        return []
    out, in_proj = [], False
    for ln in lines:
        stripped = ln.strip()
        if stripped == f"### {project}":
            in_proj = True; continue
        if in_proj and (ln.startswith("### ") or ln.startswith("## ")):
            break
        if in_proj:
            m = re.match(r"\s*- \[ \]\s*(.+?)\s*$", ln)
            if m:
                out.append(m.group(1))
    return out

def _dojo_next_task(project):
    tasks = _dojo_unchecked(project)
    return tasks[0] if tasks else ""

def _dojo_mark_done(project, task):
    """Flip the first '- [ ] <task>' → '- [x] <task>' under the project. Returns True if found."""
    if not project or not task or not PROJECTS_MD_FILE.exists():
        return False
    try:
        lines = PROJECTS_MD_FILE.read_text().splitlines(True)
    except Exception:
        return False
    target = task.strip()
    in_proj = False
    changed = False
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped == f"### {project}":
            in_proj = True; continue
        if in_proj and (ln.startswith("### ") or ln.startswith("## ")):
            break
        if in_proj:
            m = re.match(r"(\s*- \[) \](\s*)(.+?)\s*$", ln)
            if m and m.group(3).strip() == target:
                lines[i] = f"{m.group(1)}x]{m.group(2)}{m.group(3)}\n"
                changed = True
                break
    if changed:
        try:
            PROJECTS_MD_FILE.write_text("".join(lines))
        except Exception:
            return False
    return changed

def load_behavior():
    """Read ~/.sensei_behavior.md into the system prompt. Returns empty string if missing."""
    try:
        return BEHAVIOR_FILE.read_text().strip()
    except Exception:
        return ""

# ── THREAD LABEL (editable chat-thread locator on top rule line) ──
THREAD_FILE  = Path.home() / ".master_ai_thread"

def load_thread_label():
    try:
        return THREAD_FILE.read_text().strip()
    except Exception:
        return ""

def save_thread_label(name):
    try:
        THREAD_FILE.write_text((name or "").strip())
    except Exception:
        pass

def _term_cols():
    try:
        return shutil.get_terminal_size((80, 24)).columns
    except Exception:
        return 80

def print_thread_box_top():
    """Top rule of input frame — label sits BOTTOM-LEFT (inside the rule)."""
    cols = _term_cols()
    label = load_thread_label()
    tag = f" ✏ {label} " if label else f" ✏ "
    # Left-align the label on the rule (what user asked for: banner bottom-left)
    right = max(2, cols - 2 - len(tag))
    line = "┌──" + tag + "─" * (right - 3) + "┐"
    print(f"{BC}{line[:cols]}{X}")

def print_thread_box_bottom():
    """Closing rule with └ ┘ corners — drawn right after input is captured."""
    cols = _term_cols()
    line = "└" + "─" * (cols - 2) + "┘"
    print(f"{BC}{line[:cols]}{X}")

def print_legend():
    """Plain legend line — TYPE these commands at the prompt."""
    print(f"  {D}⌨ type:{X}  {BC}hub{X} · {BC}help{X} · {BC}tips{X} · {BC}model{X} · {BC}mode plan{X} · {BC}chats{X} · {BC}tts{X} · {BC}e{X}=edit label · {BC}x{X}=exit")

# ── Auto-label: after N exchanges, suggest a label if none is set ──
_AUTO_LABEL_LOCK = threading.Lock()
_AUTO_LABEL_TRIED = False  # per-session flag so we only auto-fire once

def _auto_label_bg(history_snapshot):
    """Background: generate a kebab-case label from recent exchanges, save it."""
    global _AUTO_LABEL_TRIED
    try:
        msgs = [m for m in history_snapshot if m.get("role") in ("user", "assistant")][-8:]
        transcript = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in msgs)
        prompt = (f"Give a 2-4 word kebab-case label for this conversation "
                  f"(lowercase, hyphens, no punctuation). Output ONLY the label.\n\n{transcript}")
        suggested = ask_cloud_groq([{"role": "user", "content": prompt}]) or ""
        suggested = re.sub(r'[^a-z0-9\-]+', '-', suggested.strip().split("\n")[0].strip().lower()).strip('-')[:40]
        if suggested and not load_thread_label():
            save_thread_label(suggested)
    except Exception as e:
        log(f"AUTO_LABEL_ERROR: {e}")

def maybe_auto_label(history):
    """Fire auto-label suggestion once per session after 3+ user messages.
    Only runs if no label is already set and we haven't tried yet."""
    global _AUTO_LABEL_TRIED
    with _AUTO_LABEL_LOCK:
        if _AUTO_LABEL_TRIED or load_thread_label():
            return
        user_msgs = [m for m in history if m.get("role") == "user"]
        if len(user_msgs) < 3:
            return
        _AUTO_LABEL_TRIED = True
    # run in background so we don't block the prompt
    threading.Thread(target=_auto_label_bg, args=(list(history),), daemon=True).start()

# ── QUERY QUEUE (up to 3 live) ───────────────────────────────
# User types Q1, Q2, Q3 while Sensei is still answering Q1 — each queues.
# Worker thread pops FIFO, runs handle() serially, prints reply.
_QUERY_QUEUE = queue.Queue(maxsize=3)
_WORKER_BUSY = threading.Event()
_WORKER_LOCK = threading.Lock()

# ── CONFIRM-PROMPT STDIN CHANNEL (two-channel stdin, 2026-04-21) ─
# When a confirm_run/confirm_create/confirm_edit/confirm_runterm is awaiting
# a 1/2/3/4 keystroke, any OTHER text the user types (type-ahead of the next
# question) would otherwise be eaten as the confirm answer. Fix: the TUI
# routes submits to _CONFIRM_IQ while _AWAITING_CONFIRM is set, and to the
# normal _iq otherwise. _tui_input pulls from whichever queue matches the
# flag. Confirm prompts wrap themselves via @_awaiting_confirm.
_CONFIRM_IQ = queue.Queue()
_AWAITING_CONFIRM = threading.Event()

def _awaiting_confirm(fn):
    """Mark a function as a confirm prompt — its lifetime sets _AWAITING_CONFIRM
    so the TUI routes typed input to _CONFIRM_IQ instead of the normal query
    queue. try/finally guarantees the flag clears on any exit path (return,
    exception, sys.exit)."""
    def _wrap(*args, **kwargs):
        _AWAITING_CONFIRM.set()
        try:
            return fn(*args, **kwargs)
        finally:
            _AWAITING_CONFIRM.clear()
    _wrap.__name__ = fn.__name__
    _wrap.__doc__ = fn.__doc__
    _wrap.__wrapped__ = fn
    return _wrap

# ── LOAD KEYS ────────────────────────────────────────────────
def load_keys():
    try:
        return json.loads(KEYS_FILE.read_text())
    except Exception:
        return {}

KEYS = load_keys()

# ── COLORS — matches brand.sh (visible on light + dark terminals) ──
G    = '\033[92m'    # bright green
C    = '\033[96m'    # bright cyan
Y    = '\033[33m'    # yellow
R    = '\033[91m'    # bright red
M    = '\033[95m'    # bright magenta
W    = '\033[1m'     # bold (readable on any background)
D    = '\033[0m'     # terminal default (black on light bg, white on dark)
X    = '\033[0m'     # reset
BOLD = '\033[1m'
BC   = '\033[1;34m'  # bold blue  — banner + INFO / scratchpad lines
BG   = '\033[1;32m'  # bold green — banner accent + AI VOICE (conversational prose)
BW   = '\033[97m'    # bright white — banner labels
BY   = '\033[1;33m'  # bold yellow — PLAN / numbered steps / RUN: EDIT: CREATE:
BO   = '\033[38;5;208m'  # orange — CAUTION / warnings / destructive-command previews
AMBER = '\033[38;2;199;118;26m'  # darker amber (#c7761a) — secondary yellow for footer hints / legend (distinct from BY/Y)
DIMB = '\033[2;34m'  # dim blue — SOURCES / URLs / reference footers
BM   = '\033[1;35m'  # bold magenta — YOUR input (distinct from AI cyan)

# Background-color buttons — black text on color bg, visible on ANY terminal
BTN_G = '\033[42m\033[30m'   # green  bg + black text
BTN_Y = '\033[43m\033[30m'   # yellow bg + black text
BTN_R = '\033[41m\033[30m'   # red    bg + black text
BTN_C = '\033[46m\033[30m'   # cyan   bg + black text

# ── LOGGING ──────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

# ── ROUTER ───────────────────────────────────────────────────
CODE_WORDS    = {"code","python","bash","javascript","js","script","debug","function",
                 "class","error","fix","bug","write","program","def","import","html","css"}
# Alter/mutate intent — verbs that imply changing a file or system state.
# In peacetime these route to the deep reasoning lane (DeepSeek-R1) because
# altering things reliably needs careful thought — Groq is the chat lane.
ALTER_WORDS   = {"edit","modify","refactor","patch","rewrite","replace","rename",
                 "install","uninstall","configure","setup","create","delete","remove",
                 "build","generate","make","update","upgrade","migrate"}
VISION_WORDS  = {"image","photo","picture","see","show","look","describe","what is this",
                 "analyze this","read this","whats in"}
WEB_WORDS     = {"latest","today","current","news","search","find","download","who is",
                 "what is happening","price","weather","2024","2025","2026","recently"}
COMPLEX_WORDS = {"explain","analyze","compare","difference","pros","cons","plan","strategy",
                 "why","how does","what causes","in depth","detailed","thorough","research",
                 "summarize","write a report","essay","deep dive"}
REASONING_WORDS = {"think","reason","logic","proof","math","calculate","step by step",
                   "walk me through","figure out","solve","puzzle","hypothesis"}
# Scrappy = the off-grid specialist fine-tune. Auto-activates WHEN any
# ollama-installed model has 'scrappy' in its name. No config needed —
# the moment the buyer pulls scrappy:13b, survival questions route there.
SURVIVAL_WORDS = {
    "survival","survive","off-grid","offgrid","bushcraft","apocalypse","apocalyptic",
    "shelter","tent","fire","forage","forage","trap","snare","hunt","purify",
    "water filter","rain catchment","compost","homestead","permaculture",
    "solar","battery","generator","hand pump","well","latrine","outhouse",
    "preserve","canning","smoking","curing","dehydrate","jerky","root cellar",
    "tarp","hut","cabin","log","wattle","daub","earthbag","cob","adobe",
    "first aid","splint","wound","remedy","herb","medicinal","plant id",
    "scrap","salvage","repurpose","fix broken","rebuild","from scratch",
    "grid down","no power","off the grid","doomsday","prepper","prep",
}

def _scrappy_model_present():
    """Return Ollama tag of the first 'scrappy' model pulled, else ''.
    Cached for 60s like _have_14b so orchestrator calls don't thrash."""
    import time as _t, urllib.request
    global _SCRAPPY_CACHE, _SCRAPPY_TS
    now = _t.time()
    try:
        if (now - globals().get('_SCRAPPY_TS', 0)) < 60:
            return globals().get('_SCRAPPY_CACHE', '')
    except Exception:
        pass
    tag = ''
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            body = r.read().decode()
        import re
        m = re.search(r'"(name|model)"\s*:\s*"([^"]*scrappy[^"]*)"', body, re.IGNORECASE)
        if m:
            tag = m.group(2)
    except Exception:
        pass
    globals()['_SCRAPPY_CACHE'] = tag
    globals()['_SCRAPPY_TS'] = now
    return tag

def detect_route(text, has_image=False):
    global PINNED_MODEL
    t = text.lower()
    words = set(t.split())

    # Manual pin overrides everything
    if PINNED_MODEL:
        if PINNED_MODEL == "groq":
            return "cloud", "groq", f"pinned → Groq"
        if PINNED_MODEL == "deepseek-r1":
            return "cloud", "deepseek-r1", f"pinned → DeepSeek R1"
        if PINNED_MODEL == "gemini":
            return "cloud", "gemini", f"pinned → Gemini"
        return "local", PINNED_MODEL, f"pinned → {PINNED_MODEL}"

    if has_image or any(w in t for w in VISION_WORDS):
        return "vision", MODELS["kimi"], "vision → kimi-k2.5 (1T) · llava locally in apocalypse mode"
    if words & CODE_WORDS:
        return "local", MODELS["coder"], f"code → {MODELS['coder']}"
    if words & WEB_WORDS:
        return "web", None, "web → Gemini + search"
    if any(w in t for w in REASONING_WORDS):
        return "cloud", "deepseek-r1", "reasoning → DeepSeek R1"
    if words & COMPLEX_WORDS:
        return "local", MODELS["qwen3"], "complex → qwen3.5:cloud (397B)"
    return "local", MODELS["master"], f"general → {MODELS['master']}"

# ── SMART ORCHESTRATOR ───────────────────────────────────────
# Returns a decision dict instead of dispatching a model directly.
# Possible routes: local | cloud_fast | cloud_vision | ask_user | recall_memory | save_refresh
# First match wins.

_RECALL_TRIGGERS = (
    "remember", "recall", "what did we", "earlier you", "before we",
    "last time", "previously", "you said", "we talked about",
)
_PRONOUNS_NEED_ANTECEDENT = {"it", "this", "that", "them", "those", "these"}

_ACTION_VERBS = {"do", "run", "fix", "delete", "remove", "edit", "change", "update",
                 "install", "start", "stop", "restart", "kill", "try"}

_GREETINGS = {"hi", "hello", "hey", "yo", "sup", "howdy", "hola",
              "thanks", "thank", "thx", "ty",
              "ok", "okay", "k", "cool", "nice", "great", "good",
              "yes", "yep", "yeah", "y", "no", "nope", "nah", "n",
              "bye", "goodbye", "cya", "later"}

def _is_ambiguous(stripped, words, history):
    low = stripped.lower()
    prior_assistant = [m for m in history if m.get("role") == "assistant"]
    first = words[0].lower().strip(".,!?") if words else ""

    # Opening pronoun — ambiguous if the query is 1-2 words total (e.g. "it", "this one").
    # Full sentences starting with a pronoun (e.g. "it works great") are exempt via len cap.
    if first in _PRONOUNS_NEED_ANTECEDENT and len(words) <= 2:
        return f"pronoun '{words[0]}' with no clear target"

    # Bare action verb with ≤2 words — always ambiguous even mid-chat
    # ("do it" after a list of 5 options — which?).
    if first in _ACTION_VERBS and len(words) <= 2:
        return f"action verb '{first}' with no target"

    # Lone non-greeting word — only ambiguous at the START of a fresh session
    # (mid-conversation "apothecary" could be a valid follow-up topic).
    if len(words) == 1 and first and first not in _GREETINGS and not prior_assistant:
        return f"lone word '{first}' with no context"

    # Explicit which/did-you-mean — user is asking US to choose; flip it back
    if any(p in low for p in ("did you mean", "which one", "which of", "pick for me")):
        return "explicit which/did-you-mean"

    return None

def _clarifying_question(stripped, reason):
    if reason.startswith("pronoun"):
        return f"Which one? I don't have a recent reference for '{stripped.split()[0]}' — tell me what you mean."
    if reason.startswith("action verb"):
        verb = stripped.split()[0]
        return f"'{verb}' what? Give me a target."
    if reason.startswith("lone word"):
        word = stripped.split()[0]
        return f"'{word}' — just one word? Tell me what you want done with it, or ask a full question."
    if "which" in reason.lower():
        return "I'd rather not guess between options. Which one do you want?"
    return "I'm not sure what you're asking — rephrase?"

def _memory_recall_payload(user_text):
    """Explicit recall triggers pull a memory snippet. Returns str or None."""
    low = user_text.lower()
    if not any(t in low for t in _RECALL_TRIGGERS):
        return None
    try:
        mem = MEMORY_FILE.read_text().strip()
    except Exception:
        return None
    if not mem:
        return None
    # Return the last 800 chars of memory — most recent session summaries live at the end
    return mem[-800:]

_BUILD_VERBS = {
    "make", "build", "create", "develop", "design", "write", "code", "program",
    "lets", "let's", "let", "generate", "start",
}
# Explicit triggers that flip Sensei FROM brainstorm INTO build mode.
# If any of these phrases appear, _scope_check_question returns empty so
# the request proceeds to the real model for code generation.
_BUILD_TRIGGERS = (
    "build it", "code it", "make it", "generate it", "write the code",
    "write code", "let's ship", "lets ship", "ship it", "ok go",
    "go ahead and build", "go ahead and code", "actually build",
    "actually code", "now build", "now code",
)
_GENERIC_NOUNS = {
    "app", "apps", "application", "applications", "tool", "tools", "thing",
    "project", "system", "software", "program", "website", "site", "platform",
    "bot", "service", "product", "prototype",
}
# Presence of ANY of these means the request already has specifics → skip scope check.
_SPECIFICITY_MARKERS = {
    "python", "javascript", "typescript", "js", "ts", "rust", "go", "ruby",
    "react", "vue", "svelte", "flask", "django", "fastapi", "node", "nextjs",
    "html", "css", "sql", "postgres", "sqlite", "redis", "mongo",
    "cli", "api", "rest", "graphql", "mobile", "ios", "android", "desktop",
    "web", "browser", "terminal", "bash", "shell",
    "chrome", "firefox", "extension",
}


def _project_keywords() -> list:
    """Keywords that mean 'still on the current project':
       - tokens from the active thread label (hyphen-split)
       - first 2-3 meaningful words of each active (not-done) task
       - words from the pinned dojo ACTIVE_PROJECT + ACTIVE_TASK
    Returns lowercase list of tokens >= 3 chars, dedup.
    """
    seen = set()
    out = []
    def add(w):
        w = w.lower().strip(".,!?:;\"'()[]")
        if len(w) >= 3 and w.isalpha() and w not in seen:
            seen.add(w); out.append(w)

    try:
        lbl = load_thread_label() or ""
        for tok in lbl.lower().replace("_", "-").split("-"):
            add(tok)
    except Exception:
        pass

    try:
        tasks = load_tasks()
        for t in tasks:
            if t.get("done"):
                continue
            words = (t.get("text", "") or "").split()
            for w in words[:4]:   # first few words of each task
                add(w)
    except Exception:
        pass

    # Dojo-gate pinned project + task keywords
    try:
        for w in (ACTIVE_PROJECT or "").split():
            add(w)
        for w in (ACTIVE_TASK or "").split()[:6]:
            add(w)
    except Exception:
        pass

    return out


def _maybe_drift_reminder(history_ref) -> None:
    """Fire a drift reminder only when recent user messages miss EVERY
    project keyword. Silent if we're still on-topic (no spam, no waste).

    If the dojo gate pinned a task, the reminder names it directly so the
    user sees exactly what they drifted from — not just a keyword list."""
    keywords = _project_keywords()
    if not keywords:
        return   # no active project context → nothing to drift from
    recent_user = " ".join(
        (m.get("content", "") or "").lower()
        for m in history_ref[-8:]
        if m.get("role") == "user"
    )
    matched = [k for k in keywords if k in recent_user]
    if matched:
        return   # on-topic, no reminder needed
    # Prefer the dojo-pinned task in the reminder text — that's the sharpest
    # anchor we have for the user's current intent.
    if ACTIVE_TASK:
        proj = ACTIVE_PROJECT or "(no project)"
        print(f"\n  {BC}🥷 [reminder]{X} still on: {BW}{ACTIVE_TASK}{X}  "
              f"{D}({proj}){X}")
        print(f"  {D}   type 'done' when finished · 'dojo' to see status · "
              f"'task add ...' for a sidetrack{X}\n")
        return
    lbl = load_thread_label() or "(unset)"
    kw_preview = ", ".join(keywords[:5])
    print(f"\n  {BC}💡 drift check:{X} recent chat hasn't touched "
          f"{BC}{lbl}{X} keywords ({D}{kw_preview}{X})")
    print(f"  {D}   still on this thread? Or type 'e' to rename, "
          f"or 'task add ...' to log a sidetrack task.{X}\n")


def _append_poc_stub(user_text: str) -> None:
    """Append a brief Ideas / POCs entry so brainstorms are captured even
    when the user doesn't explicitly run master.sh option 9."""
    try:
        p = Path.home() / "scripts" / "PROJECTS.md"
        if not p.exists():
            return
        content = p.read_text()
        marker = "## Ideas / POCs"
        if marker not in content:
            return
        stub = (
            f"\n### POC (auto-logged {datetime.now():%Y-%m-%d %H:%M})\n"
            f"- **Ask:** {user_text.strip()[:300]}\n"
            f"- **Status:** brainstorming — scope-check fired\n"
        )
        p.write_text(content.rstrip() + "\n" + stub)
    except Exception as e:
        log(f"POC_LOG_ERROR: {e}")


def _scope_check_question(stripped: str, words, word_set, history) -> str:
    """Return a clarifying question if this request is vague+ambitious,
    otherwise empty string (let later routes handle it).

    Triggers when ALL are true:
      - short (< 15 words)
      - contains a build-intent verb
      - contains a generic noun (app / tool / thing / project / ...)
      - lacks any specificity marker (no language, framework, or target)
      - this is a FIRST ask on the topic (no prior AI scope reply in history)
    """
    if len(words) == 0 or len(words) > 15:
        return ""
    low = stripped.lower()

    # Build trigger present? User has explicitly greenlit code generation —
    # skip the scope gate and let the model work.
    if any(t in low for t in _BUILD_TRIGGERS):
        return ""

    # Already in a back-and-forth about scope? Don't ask again.
    recent = [m.get("content", "") for m in history[-6:]
              if m.get("role") == "assistant"]
    for r in recent:
        if "clarify the scope" in r.lower() or "who is the end user" in r.lower():
            return ""

    has_build_verb = any(v in low for v in _BUILD_VERBS) or any(
        w in _BUILD_VERBS for w in word_set
    )
    has_generic_noun = bool(word_set & _GENERIC_NOUNS)
    if not (has_build_verb and has_generic_noun):
        return ""

    if word_set & _SPECIFICITY_MARKERS:
        return ""  # already has language / target info

    # Sensei is an administrator — not a chat bot. Vague build asks get a
    # short redirect to Pupil (where brainstorming + scoping belongs), plus a
    # one-line offer to act immediately if Elijah adds specifics.
    return (
        "That's a brainstorm-shaped ask — Sensei is built for execution, "
        "not scoping.\n\n"
        "  • For open-ended idea chat: run `master.sh` → option 5 (Pupil)\n"
        "  • To act here: add specifics (language / platform / "
        "first concrete feature) and I'll build it"
    )


def _read_run_mode():
    """Which product mode is the user running in?
      'apocalypse' (default) — local-first. Self-sufficient. Cloud is opt-in per-request.
      'peacetime'            — cloud-first when keys present. Speed over sovereignty.
    File: ~/.master_ai_run_mode. Empty / missing / unknown → 'apocalypse'.
    Elijah's North Star: the product has to work when it's just him and the machine."""
    try:
        p = Path.home() / ".master_ai_run_mode"
        if p.exists():
            v = p.read_text().strip().lower()
            if v in ("peacetime", "peace", "cloud", "cloud-first"): return "peacetime"
    except Exception:
        pass
    return "apocalypse"

def orchestrate(history, user_text, image_path=None):
    """Pick a route. Returns decision dict with 'route'/'model'/'reason'.

    Two product modes (read from ~/.master_ai_run_mode):
      APOCALYPSE (default) — local-first. The product has to work when it's
        just you and the machine. Cloud is explicit per-request only ('fast:'
        or 'deep:'). If the world goes dark, nothing about this changes.
      PEACETIME — cloud-first when keys are present. Groq is 400 tok/s vs
        local 5 tok/s — peacetime mode spends those cycles.

    Explicit prefixes (always win, regardless of mode):
      fast:    → Groq (opt-in speed)
      deep:    → DeepSeek-R1 or qwen3.5:cloud (opt-in reasoning)
      local:   → force local 7b (explicit privacy)
      private: → same as local:, intent-flagged
    """
    stripped = (user_text or "").strip()
    low = stripped.lower()
    words = stripped.split()
    word_set = set(w.lower().strip(".,!?") for w in words)

    run_mode = _read_run_mode()
    keys_now = load_keys()
    have_groq   = bool((keys_now.get('groq') or '').strip())
    have_or     = bool((keys_now.get('openrouter') or '').strip())
    have_gemini = bool((keys_now.get('gemini') or '').strip())
    any_cloud   = have_groq or have_or or have_gemini

    # 1. Context pressure — save & refresh before we blow context
    total_chars = sum(len(m.get("content", "") or "") for m in history)
    if total_chars >= CONTEXT_WATERMARK:
        return {"route": "save_refresh",
                "reason": f"history {total_chars} chars >= watermark {CONTEXT_WATERMARK}"}

    # 2. Explicit prefixes — user intent overrides mode
    if low.startswith("fast:") and have_groq:
        return {"route": "cloud_fast", "model": "groq",
                "stripped_text": stripped[5:].strip(),
                "reason": "explicit 'fast:' → Groq"}
    if low.startswith("deep:"):
        if have_or:
            return {"route": "cloud_deep", "model": "deepseek-r1",
                    "stripped_text": stripped[5:].strip(),
                    "reason": "explicit 'deep:' → DeepSeek-R1"}
        return {"route": "cloud_deep", "model": MODELS["qwen3"],
                "stripped_text": stripped[5:].strip(),
                "reason": "explicit 'deep:' → qwen3.5:cloud"}
    if low.startswith("local:") or low.startswith("private:"):
        prefix_len = 7 if low.startswith("private:") else 6
        return {"route": "local", "model": MODELS["master"],
                "stripped_text": stripped[prefix_len:].strip(),
                "reason": "explicit local/private → local 7b"}

    # 2b. Harvest cache lookup — if a very similar prompt has been answered
    # before (by local OR cloud), serve the stored answer. Zero-cost path.
    # Works offline. Makes the system smarter the more it's used. Strict 0.85
    # similarity so only near-duplicates hit; 90-day staleness cap. Explicit
    # prefixes already returned above — they bypass cache intentionally.
    # Plan mode also bypasses the cache: plan drafts are conversational +
    # stateful, cached "similar" prompts from a different session would
    # derail the reasoning. Elijah 2026-04-20: "bypass the cache when
    # MODE==plan" — option 4 of the cache-collision fix.
    _current_mode = globals().get("MODE", "plan")
    if harvest is not None and stripped and not image_path and _current_mode != "plan":
        try:
            cached_resp, sim, entry = harvest.lookup(
                stripped, min_similarity=0.85, max_age_days=90
            )
            if cached_resp:
                return {"route": "cached",
                        "response": cached_resp,
                        "similarity": sim,
                        "source_model": (entry or {}).get("model", "?"),
                        "reason": f"harvest cache hit sim={sim:.2f}"}
        except Exception as e:
            log(f"HARVEST_LOOKUP_ERROR: {e}")

    # 3. Vision — prefer local llava in apocalypse mode; cloud multimodal in peacetime
    if image_path or any(w in low for w in VISION_WORDS):
        if run_mode == "peacetime" and any_cloud and have_gemini:
            return {"route": "cloud_vision", "model": "gemini",
                    "reason": "peacetime vision → Gemini 2.0 Flash"}
        # Apocalypse default: use local llava (no internet needed). Fall
        # through to kimi:cloud only when llava isn't pulled.
        return {"route": "local", "model": MODELS["vision"],
                "reason": "apocalypse vision → llava (local, offline-capable)"}

    # 4. Ambiguous → ask the user
    amb = _is_ambiguous(stripped, words, history)
    if amb:
        return {"route": "ask_user",
                "question": _clarifying_question(stripped, amb),
                "reason": f"ambiguous: {amb}"}

    # 5. Recall-memory trigger (explicit)
    payload = _memory_recall_payload(stripped)
    if payload:
        return {"route": "recall_memory", "payload": payload,
                "reason": "explicit recall trigger"}

    # 5b. Scope check — vague+ambitious build requests need clarify first
    scope_q = _scope_check_question(stripped, words, word_set, history)
    if scope_q:
        return {"route": "scope_check", "question": scope_q,
                "reason": "vague+ambitious build → clarify scope first"}

    # 5c. Current-events check — local brains can't know what happened today.
    # In Local Mode the default path is a frozen offline model with no
    # internet. Asked "what happened at Wrestlemania last night?" it will
    # confidently fabricate an answer. Catch time-sensitive queries BEFORE
    # that happens and offer the user cloud/search options. Does not fire
    # in Connected Mode (peacetime path already routes to cloud). Does not
    # fire when the user typed a `fast:` / `deep:` / `local:` prefix — those
    # were handled at step 2 and returned early.
    if run_mode == "apocalypse" and _looks_time_sensitive(low, word_set):
        return {"route": "time_sensitive_warn",
                "original_query": stripped,
                "have_groq": have_groq,
                "have_or": have_or,
                "reason": "time-sensitive query — local brain can't know current events"}

    # 6. PEACETIME PATH — cloud-first, only when user explicitly chose it.
    #    Two-lane auto-route (no more typing 'fast:' / 'deep:'):
    #      Alter/code/reasoning → DeepSeek-R1 (deep lane — reasons through changes)
    #      Chat / quick text    → Groq        (fast lane — banter speed)
    if run_mode == "peacetime" and any_cloud:
        if (any(w in low for w in REASONING_WORDS)
                or (word_set & COMPLEX_WORDS)
                or (word_set & CODE_WORDS)
                or (word_set & ALTER_WORDS)):
            if have_or:
                return {"route": "cloud_deep", "model": "deepseek-r1",
                        "reason": "peacetime alter/code/deep → DeepSeek-R1"}
            return {"route": "cloud_deep", "model": MODELS["qwen3"],
                    "reason": "peacetime alter/code/deep → qwen3.5:cloud"}
        if have_groq:
            return {"route": "cloud_fast", "model": "groq",
                    "reason": "peacetime chat → Groq (fast lane)"}
        if have_or:
            return {"route": "cloud_deep", "model": "deepseek-r1",
                    "reason": "peacetime default → DeepSeek-R1"}

    # Content-routed chat — plain chat goes to Groq when a key exists,
    # regardless of mode. Chat doesn't need master-ai's directive discipline,
    # and on CPU master-ai takes 1-5 min then silent-falls-back to Groq anyway.
    # Route by fit, not mode. 'local:' prefix above still forces local.
    is_chat_class = not (
        (word_set & CODE_WORDS)
        or (word_set & ALTER_WORDS)
        or (word_set & COMPLEX_WORDS)
        or any(w in low for w in REASONING_WORDS)
    )
    if is_chat_class and have_groq:
        return {"route": "cloud_fast", "model": "groq",
                "reason": "chat → Groq (content-routed)"}

    # 6b. SCRAPPY — survival/off-grid specialist takes precedence over generic
    #     local models when the question is clearly on its home turf AND the
    #     fine-tune is pulled. Works in BOTH modes: even in Connected Mode, a
    #     survival question routes to Scrappy on-box (these answers don't need
    #     cloud — the specialist IS the strongest path).
    scrappy_tag = _scrappy_model_present()
    if scrappy_tag and (
        any(w in low for w in SURVIVAL_WORDS)
        or any(p in low for p in ("how do i build", "rebuild from scratch", "from scrap"))
    ):
        return {"route": "local", "model": scrappy_tag,
                "reason": f"survival/off-grid → Scrappy ({scrappy_tag}) specialist"}

    # 7. APOCALYPSE PATH — always local. Never depends on an internet connection
    #    that might not exist when you need the machine most.
    if word_set & CODE_WORDS:
        return {"route": "local", "model": MODELS["coder"],
                "reason": "code → qwen2.5-coder:7b (local, apocalypse-ready)"}
    if any(w in low for w in REASONING_WORDS) or (word_set & COMPLEX_WORDS):
        return {"route": "local",
                "model": "qwen2.5:14b" if _have_14b() else MODELS["master"],
                "reason": f"deep → {'14b big brain' if _have_14b() else '7b brain'} (local)"}
    if len(words) > 100:
        return {"route": "local",
                "model": "qwen2.5:14b" if _have_14b() else MODELS["master"],
                "reason": f"long ({len(words)} words) → {'14b' if _have_14b() else '7b'} local"}
    # 2026-04-21: short-prompt → qwen2.5:3b route REMOVED. Short ≠ simple —
    # "fix the bug" is 3 words but requires senior-engineer reasoning. The 3B
    # mushes directives ("master ai endurance" hallucinated folder from voice-to-
    # text garbage; RUNTERM doc parroted instead of emitted). 3B is now reserved
    # for idle tips and vision preprocessing. All user turns get master-ai.
    return {"route": "local", "model": MODELS["master"],
            "reason": "default → master-ai brain (qwen2.5:7b + baked behavior, local)"}


# Time-sensitive / current-events markers. Frozen local models can't know
# about events after their training cutoff, so Sensei intercepts these and
# routes to web_search(). Triggers are PHRASE-ONLY — single words like
# "latest" / "recent" / "currently" fired on casual phrasing (e.g. "my
# latest project", "currently working on X") so they're excluded. Phrases
# are unambiguous signals of asking about a specific recent event.
_TIME_WORDS = frozenset({
    "yesterday", "tonight",           # strong on their own
})
_TIME_PHRASES = (
    "last night", "this morning",
    "who won", "who's winning", "whos winning",
    "what happened at", "what happened last", "what happened yesterday",
    "what happened today", "what happened tonight",
    "score of", "result of", "results of",
    "as of today", "as of now",
    "who is the president", "who is the ceo of",
    "stock price of", "current stock", "stock market today",
    "weather in", "what's the weather", "whats the weather",
    "news today", "today's news", "todays news", "latest news",
    "breaking news", "headlines today",
    "playoff games", "playoff game tonight", "games tonight", "games today",
    "game tonight", "game today",
)

def _looks_time_sensitive(low, word_set):
    """Return True if the query is clearly asking about a recent/current
    event a frozen local model cannot know. Phrase-only to avoid false
    positives on casual single-word use. When in doubt we let the normal
    router handle it — a missed intercept costs one hallucination; a
    false positive costs every request going through web search when it
    shouldn't."""
    if word_set & _TIME_WORDS:
        return True
    for p in _TIME_PHRASES:
        if p in low:
            return True
    return False

def _have_14b():
    """Cheap check — is the 14B big-brain model pulled on this box?
    Cached for one minute so repeated orchestrator calls don't hammer Ollama."""
    import time as _t
    global _HAVE_14B_CACHE, _HAVE_14B_TS
    now = _t.time()
    try:
        if (now - globals().get('_HAVE_14B_TS', 0)) < 60:
            return globals().get('_HAVE_14B_CACHE', False)
    except Exception:
        pass
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            body = r.read().decode()
        present = '"qwen2.5:14b"' in body
    except Exception:
        present = False
    globals()['_HAVE_14B_CACHE'] = present
    globals()['_HAVE_14B_TS'] = now
    return present

# ── WEB SEARCH ───────────────────────────────────────────────
# Two engines, preferred in order:
#   1. GEMINI GROUNDED  — Google Search under the hood via gemini-2.0-flash
#      tool use. Needs the user's existing Gemini API key (free tier is
#      enough). Returns a synthesized answer + source URLs — closest thing
#      to "what you'd see on google.com" without needing a Custom Search
#      Engine ID.
#   2. DUCKDUCKGO        — library call, no key needed, works offline-
#      ready when anyone has internet. Fallback when Gemini has no key or
#      the request fails.
_GEMINI_MODEL_CHAIN = (
    "gemini-2.5-flash",        # newest flash — usually has free quota
    "gemini-flash-latest",     # alias that Google points at current free tier
    "gemini-2.0-flash",        # prior-gen fallback
    "gemini-2.5-flash-lite",   # smaller / cheaper — last resort
)

def gemini_grounded_search(query, timeout=20):
    """Google-grounded search via Gemini with Google Search tool enabled.
    Returns a formatted string with synthesized answer + source URLs, or
    None if no gemini model in the fallback chain has quota available.

    Why the chain: free-tier quota is granted per MODEL, not per project.
    Observed 2026-04-19 with limit=0 on gemini-2.0-flash even on a fresh
    key. Walking the chain tries newer models that may have their own
    allocation before giving up and letting DDG take over downstream."""
    try:
        keys = load_keys()
    except Exception:
        return None
    api_key = (keys.get('gemini') or '').strip()
    if not api_key:
        return None
    payload = {
        "contents": [{"parts": [{"text": query}]}],
        "tools": [{"googleSearch": {}}],
    }
    last_err = None
    body = None
    for model in _GEMINI_MODEL_CHAIN:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={api_key}")
        try:
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read().decode())
                log(f"GEMINI_SEARCH_OK: {model}")
                break
        except urllib.error.HTTPError as e:
            # 429 = quota for THIS model exhausted — try the next.
            # 4xx others = configuration issue, stop walking.
            last_err = f"HTTP {e.code} on {model}: {e.reason}"
            log(f"GEMINI_SEARCH_ERROR: {last_err}")
            if e.code == 429:
                continue
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            log(f"GEMINI_SEARCH_ERROR: {last_err} (on {model})")
            break
    if body is None:
        return None
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return None
    # Pull source URLs out of groundingMetadata if present — that's what
    # makes this "google-type" rather than "AI guessed."
    sources = []
    try:
        gm = body["candidates"][0].get("groundingMetadata", {})
        for chunk in gm.get("groundingChunks", [])[:5]:
            web = chunk.get("web", {})
            title = (web.get("title", "") or "").strip()
            uri   = (web.get("uri", "") or "").strip()
            if uri:
                if title:
                    sources.append(f"  • {title} — {uri}")
                else:
                    sources.append(f"  • {uri}")
    except Exception:
        pass
    if sources:
        return f"{text}\n\nSources (Google):\n" + "\n".join(sources)
    return text

def duckduckgo_search(query, max_results=4):
    """Raw DuckDuckGo results — title + snippet per hit. Returns a
    formatted string or None on error. Handles the 2026-era package
    rename from `duckduckgo_search` → `ddgs` by trying both imports."""
    DDGS = None
    # New name (ddgs) first — that's what `pip install ddgs` ships today.
    try:
        from ddgs import DDGS as _DDGS
        DDGS = _DDGS
    except ImportError:
        pass
    # Fall back to the old name if installed.
    if DDGS is None:
        try:
            from duckduckgo_search import DDGS as _DDGS
            DDGS = _DDGS
        except ImportError:
            log("DDG_SEARCH_ERROR: neither 'ddgs' nor 'duckduckgo_search' is installed")
            return None
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return None
        return "\n".join(f"• {r.get('title','')}: {r.get('body','')[:200]}"
                         for r in results)
    except Exception as e:
        log(f"DDG_SEARCH_ERROR: {e}")
        return None

def wikipedia_search(query, max_articles=3, timeout=8):
    """Wikipedia REST API — no key, no rate limit beyond "be reasonable."
    Returns the top N article summaries with titles + extract + canonical
    URL, or None on failure. Great for factual / encyclopedic queries
    ('who was X', 'what is Y', 'when did Z happen'). Rebuilds fresh each
    call; no caching yet — add at the web_search() layer when needed."""
    import urllib.parse as _up
    # First: search titles matching the query.
    search_url = ("https://en.wikipedia.org/w/api.php?action=query"
                  "&format=json&list=search&srlimit=" + str(max_articles)
                  + "&srsearch=" + _up.quote(query))
    try:
        req = urllib.request.Request(
            search_url,
            headers={"User-Agent": "MasterAI/1.8 (Elijah; contact ebey317@gmail.com)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            hits = json.loads(r.read().decode()).get("query", {}).get("search", [])
    except Exception as e:
        log(f"WIKIPEDIA_SEARCH_ERROR: {e}")
        return None
    if not hits:
        return None
    # Second: fetch the summary for each hit via the REST summary endpoint.
    lines = []
    for h in hits[:max_articles]:
        title = h.get("title", "")
        if not title:
            continue
        try:
            sum_url = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
                       + _up.quote(title.replace(" ", "_")))
            req = urllib.request.Request(
                sum_url,
                headers={"User-Agent": "MasterAI/1.8 (Elijah; contact ebey317@gmail.com)"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                s = json.loads(r.read().decode())
            extract = (s.get("extract", "") or "").strip()
            url     = (s.get("content_urls", {}).get("desktop", {}).get("page")
                       or f"https://en.wikipedia.org/wiki/{_up.quote(title.replace(' ', '_'))}")
            if extract:
                lines.append(f"• {title}: {extract[:400]}\n  {url}")
        except Exception:
            # Skip this hit but keep going; Wikipedia occasionally 404s on
            # titles with special characters.
            continue
    return "\n".join(lines) if lines else None

def ddg_instant_answer(query, timeout=6):
    """DuckDuckGo Instant Answer API — no key, returns structured answers
    for well-known facts (definitions, people, brands). Often empty for
    news-style queries; that's expected. Acts as a cheap first check
    before the full blended web_search."""
    import urllib.parse as _up
    url = (f"https://api.duckduckgo.com/?q={_up.quote(query)}"
           "&format=json&no_html=1&skip_disambig=1")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "MasterAI/1.8 (Elijah; contact ebey317@gmail.com)"
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
    except Exception as e:
        log(f"DDG_INSTANT_ERROR: {e}")
        return None
    abstract = (d.get("AbstractText") or "").strip()
    source   = (d.get("AbstractURL") or "").strip()
    heading  = (d.get("Heading") or "").strip()
    if abstract:
        return f"• {heading}: {abstract}\n  {source}" if source else f"• {heading}: {abstract}"
    return None

def brave_search(query, max_results=5, timeout=10):
    """Brave Search API — independent index, often better than DDG for
    news and recent events. Free tier: 2000 queries/month with a signup
    at api.search.brave.com. Returns a formatted string or None if the
    key is missing / the request fails. Keys file field: 'brave'."""
    try:
        keys = load_keys()
    except Exception:
        return None
    api_key = (keys.get('brave') or '').strip()
    if not api_key:
        return None
    import urllib.parse as _up
    url = (f"https://api.search.brave.com/res/v1/web/search?"
           f"q={_up.quote(query)}&count={max_results}")
    try:
        req = urllib.request.Request(
            url,
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
                "User-Agent": "MasterAI/1.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
    except Exception as e:
        log(f"BRAVE_SEARCH_ERROR: {e}")
        return None
    results = (body.get("web", {}) or {}).get("results", []) or []
    if not results:
        return None
    lines = []
    for r in results[:max_results]:
        title = (r.get("title") or "").strip()
        desc  = (r.get("description") or "").strip()
        href  = (r.get("url") or "").strip()
        if href:
            lines.append(f"• {title}: {desc[:200]}\n  {href}")
    return "\n".join(lines) if lines else None

def serper_search(query, max_results=5, timeout=10):
    """Serper — Google results via a simple API. Free tier: 2500 queries
    on signup at serper.dev, no recurring quota. Returns a formatted
    string or None. Keys file field: 'serper'."""
    try:
        keys = load_keys()
    except Exception:
        return None
    api_key = (keys.get('serper') or '').strip()
    if not api_key:
        return None
    payload = {"q": query, "num": max_results}
    try:
        req = urllib.request.Request(
            "https://google.serper.dev/search",
            data=json.dumps(payload).encode(),
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
    except Exception as e:
        log(f"SERPER_SEARCH_ERROR: {e}")
        return None
    organic = body.get("organic", []) or []
    if not organic:
        return None
    lines = []
    # Include the answerBox if Google returned one — it's a "featured snippet"
    # equivalent and is often the best single-line answer.
    abox = body.get("answerBox") or {}
    if abox:
        ans = (abox.get("answer") or abox.get("snippet") or "").strip()
        link = (abox.get("link") or "").strip()
        if ans:
            lines.append(f"★ Featured: {ans[:300]}" + (f"\n  {link}" if link else ""))
    for r in organic[:max_results]:
        title = (r.get("title") or "").strip()
        snippet = (r.get("snippet") or "").strip()
        link = (r.get("link") or "").strip()
        if link:
            lines.append(f"• {title}: {snippet[:200]}\n  {link}")
    return "\n".join(lines) if lines else None

def firecrawl_fetch(url, timeout=45):
    """Firecrawl — clean markdown from any URL. Different tool than the
    search engines above: instead of a list of snippets, this returns the
    FULL page content of one specific URL, scrubbed of ads/nav/scripts.
    Useful after web_search finds an interesting article and you want to
    read/summarize the full piece. Free tier: 500 credits on signup at
    firecrawl.dev. Keys file field: 'firecrawl' (prefix 'fc-...')."""
    try:
        keys = load_keys()
    except Exception:
        return None
    api_key = (keys.get('firecrawl') or '').strip()
    if not api_key:
        return "Firecrawl key not set — paste an fc-... key via Pupil or menu 11 to enable page fetching."
    if not (url.startswith('http://') or url.startswith('https://')):
        return f"Not a valid URL: {url}"
    payload = {"url": url, "formats": ["markdown"]}
    try:
        req = urllib.request.Request(
            "https://api.firecrawl.dev/v1/scrape",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode()
        except Exception:
            err_body = ""
        log(f"FIRECRAWL_ERROR: HTTP {e.code} {err_body[:200]}")
        return f"Firecrawl error {e.code}: {err_body[:200] or e.reason}"
    except Exception as e:
        log(f"FIRECRAWL_ERROR: {e}")
        return f"Firecrawl unavailable: {e}"
    if not body.get("success"):
        return f"Firecrawl returned unsuccessful: {body.get('error','(no error message)')}"
    data = body.get("data", {}) or {}
    markdown = (data.get("markdown") or "").strip()
    meta = data.get("metadata", {}) or {}
    title = (meta.get("title") or "").strip()
    # Cap at a reasonable length — full articles can be very long.
    if len(markdown) > 12000:
        markdown = markdown[:12000] + "\n\n[…truncated — full page is longer]"
    header = f"# {title}\n\n{url}\n\n" if title else f"{url}\n\n"
    return header + markdown

def wikihow_via_gemini(query, timeout=15):
    """WikiHow doesn't have a public API and scraping their site is
    against their ToS. Instead, use Gemini's grounded search with a
    site: filter to pull top WikiHow articles for how-to queries. This
    only runs if the user's question looks like a how-to. Returns the
    same shape as gemini_grounded_search (text + sources) or None."""
    low = (query or "").lower()
    if not (low.startswith("how to ") or low.startswith("how do i ")
            or low.startswith("how can i ") or "how to " in low[:60]):
        return None
    # Delegate to the grounded-search with a site: modifier. Gemini
    # respects site: in the underlying Google query when grounding.
    scoped = f"{query} site:wikihow.com"
    return gemini_grounded_search(scoped)

def web_search(query, max_results=4):
    """Top-level search. Queries several engines in parallel-ish priority,
    blends the best hits. Engines tried:
      1. Gemini grounded (Google) — synthesized answer + sources
      2. Wikipedia REST API       — encyclopedic grounding
      3. DuckDuckGo               — raw web hits
      4. DDG Instant Answer       — structured quick facts
      5. WikiHow via Gemini       — only for "how to..." queries
    Returns a formatted string combining whichever engines answered.
    Every engine returns None on error, so the combiner tolerates any
    subset being down. Explicit "Search unavailable" only when ALL fail."""
    log(f"WEB_SEARCH: {query}")
    gem    = gemini_grounded_search(query)
    brave  = brave_search(query, max_results=max_results)
    serper = serper_search(query, max_results=max_results)
    wiki   = wikipedia_search(query)
    ddg    = duckduckgo_search(query, max_results=max_results)
    instant = ddg_instant_answer(query)
    howto   = wikihow_via_gemini(query)
    blocks = []
    if gem:     blocks.append(f"[Google (via Gemini grounding)]\n{gem}")
    if brave:   blocks.append(f"[Brave Search]\n{brave}")
    if serper:  blocks.append(f"[Google (via Serper)]\n{serper}")
    if wiki:    blocks.append(f"[Wikipedia]\n{wiki}")
    if ddg:     blocks.append(f"[DuckDuckGo]\n{ddg}")
    if instant: blocks.append(f"[DuckDuckGo Instant Answer]\n{instant}")
    if howto:   blocks.append(f"[WikiHow (via Google site:)]\n{howto}")
    if blocks:
        return "\n\n".join(blocks)
    return ("Search unavailable: all engines failed or returned nothing "
            "(Gemini, Brave, Serper, Wikipedia, DuckDuckGo, Instant Answer, WikiHow).")

# ── DOWNLOAD FILE ────────────────────────────────────────────
def download_file(url, dest=None):
    log(f"DOWNLOAD: {url}")
    if not dest:
        fname = url.split("/")[-1].split("?")[0] or "download"
        dest = str(Path.home() / "Downloads" / fname)
    try:
        urllib.request.urlretrieve(url, dest)
        log(f"DOWNLOADED: {dest}")
        return dest
    except Exception as e:
        log(f"DOWNLOAD_ERROR: {e}")
        return None

# ── LOCAL AI (OLLAMA) ─────────────────────────────────────────
def ask_local(messages, model=None, image_path=None):
    model = model or MODELS["master"]
    log(f"LOCAL [{model}]")
    # num_ctx + timeout matched to ask_local_stream — see that function
    # for reasoning. Keeps non-streaming calls (briefings, memory recall)
    # from blocking the input loop for minutes on CPU.
    payload = {"model": model, "messages": messages, "stream": False,
               "keep_alive": "30m",
               "options": {"num_ctx": 4096}}
    if image_path:
        try:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            payload["messages"][-1]["images"] = [b64]
        except Exception as e:
            log(f"IMAGE_ERROR: {e}")
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat", data=data,
        headers={"Content-Type": "application/json"}
    )
    try:
        # See ask_local_stream timeout comment — 180s matches it. Don't
        # pre-empt local; Elijah prefers "a little weight" over cloud
        # fallback.
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read())
            response_text = result["message"]["content"]
            # Harvest this call so future identical questions don't re-run it
            if harvest is not None and response_text:
                try:
                    last_user = next((m.get("content", "") for m in reversed(messages)
                                      if m.get("role") == "user"), "")
                    if last_user:
                        harvest.record(last_user, model, response_text, task_type="local")
                except Exception as e:
                    log(f"HARVEST_RECORD_ERROR: {e}")
            return response_text
    except Exception as e:
        log(f"OLLAMA_ERROR: {e}")
        return None

# ── LOCAL AI STREAMING ───────────────────────────────────────
# ── REPLY LINE CLASSIFIER + SCRATCHPAD ────────────────────────
# Paints every complete reply line one of four Master AI brand colors
# based on what shape it is. The AI's stream still streams at the
# character level; color snaps in at newline boundaries. Lines get one
# of: PLAN (yellow), INFO (blue), CAUTION (orange), SOURCES (dim blue),
# or the default VOICE (green).
#
# Hooked from ask_local_stream and ask_cloud_stream — both buffer tokens
# until "\n" and call _paint_line() to wrap the assembled line.
SCRATCHPAD_SYSTEM_ADDITION = (
    "\n\n[SCRATCHPAD]\n"
    "For any non-trivial question, emit ONE short line in this exact "
    "shape before your answer:\n"
    "  [scratchpad: <one-sentence weighing of the approach>]\n"
    "Then a blank line, then your answer. For trivial questions "
    "(greetings, one-word replies, obvious commands) skip the "
    "scratchpad. Keep it to one line — never a chain-of-thought dump.\n"
    "\n"
    "Structure your answer in these shapes so the UI can color-code:\n"
    "  - PLAN lines: numbered steps ('1.', '2.') or directive lines (read/run/runterm/create/edit, each on its own line at column 0)\n"
    "  - CAUTION lines: start with '⚠' when something destructive or\n"
    "    risky is about to happen — rm, force-push, drop, systemctl stop\n"
    "  - SOURCES lines: when referencing URLs, end reply with a 'Sources:'\n"
    "    line followed by one URL per line\n"
    "  - Everything else is plain conversational prose (your voice)\n"
)

# Local models have no baked-in SYSTEM (vanilla qwen2.5:7b) and the system
# message is popped before dispatch to preserve KV cache. Without this hint,
# the model describes file changes in prose instead of emitting directives.
# Prepended to every local user message — stable bytes so KV cache still
# benefits across turns.
LOCAL_DIRECTIVE_HINT = (
    "[How to respond when the user wants a file created, edited, or a command run.]\n"
    "Reason in ONE short prose sentence describing the choice. The sentence must contain\n"
    "NO colon-suffixed directive words at all — those are reserved keywords the parser\n"
    "matches verbatim. Then on the NEXT LINE, at column 0, emit the directive itself.\n"
    "Available directive keywords: read, run, runterm, create, edit, ask, done — each\n"
    "followed by a colon, only on its own line, never inside a sentence.\n\n"
    "Available directive shapes (use each on its OWN line, never inline in prose):\n"
    "  - read followed by a colon and a filepath\n"
    "  - run followed by a colon and a bash command (captured output: ls, git, pytest, apt)\n"
    "  - runterm followed by a colon and a bash command (visual / animated / TTY scripts)\n"
    "  - create followed by a colon and a filepath, then a content block bounded by\n"
    "    triple-less-than CONTENT and triple-greater-than CONTENT markers\n"
    "  - edit followed by a colon and a filepath, then FIND and REPLACE blocks\n\n"
    "Pick runterm when the script clears the screen, animates, reads keyboard, or needs\n"
    "a real TTY. Pick run for everything else. For chat or explanation, reply as plain\n"
    "prose with no directive at all.\n\n"
    "User: "
)

import re as _re_classify
_RE_NUMBERED  = _re_classify.compile(r'^\s*\d+[.)]\s')
_RE_DIRECTIVE = _re_classify.compile(r'^\s*(RUN|RUNTERM|READ|CREATE|EDIT|THINK|DONE|PLAN):')
_RE_SCRATCH   = _re_classify.compile(r'^\s*\[scratchpad:', _re_classify.IGNORECASE)
_RE_URL       = _re_classify.compile(r'https?://\S+')

def _paint_line(line: str) -> str:
    """Classify a complete line and return it wrapped in the right ANSI
    color escape. Uses Master AI brand colors (BC/BG/BY/BO/DIMB).
    Unclassified lines get BG (the AI's conversational voice).
    """
    stripped = line.rstrip("\n\r")
    if not stripped.strip():
        return line  # blank lines stay uncolored

    low = stripped.lower()

    # CAUTION first — beats everything else
    if stripped.strip().startswith("⚠") or low.lstrip().startswith(("warning:", "caution:", "danger:")):
        return f"{BO}{stripped}{X}\n"

    # SCRATCHPAD + INFO quotes → blue
    if _RE_SCRATCH.match(stripped):
        return f"{BC}{stripped}{X}\n"
    if stripped.lstrip().startswith(">"):
        return f"{BC}{stripped}{X}\n"

    # PLAN — numbered steps + directives → yellow
    if _RE_NUMBERED.match(stripped) or _RE_DIRECTIVE.match(stripped):
        return f"{BY}{stripped}{X}\n"

    # SOURCES footer → dim blue; also bare URL-only lines
    low_strip = low.strip()
    if low_strip.startswith("sources:") or low_strip.startswith("source:"):
        return f"{DIMB}{stripped}{X}\n"
    if stripped.strip() and _RE_URL.fullmatch(stripped.strip()):
        return f"{DIMB}{stripped}{X}\n"

    # Default → VOICE (green)
    return f"{BG}{stripped}{X}\n"


def _stream_with_color(token_iter):
    """Wrap a token generator: buffer until newline, paint line, yield.
    Final partial line (no trailing \\n) gets painted and yielded at end."""
    buf = []
    for token in token_iter:
        if not token:
            continue
        buf.append(token)
        joined = "".join(buf)
        while "\n" in joined:
            line, _, rest = joined.partition("\n")
            yield _paint_line(line + "\n")
            joined = rest
        buf = [joined] if joined else []
    # Flush final partial line, if any
    if buf:
        tail = "".join(buf)
        if tail:
            yield _paint_line(tail + "\n")


def ask_local_stream(messages, model=None, image_path=None):
    """Stream tokens from Ollama directly to terminal. Returns full text.
    Shows a rotating 'thinking' animation until the first token lands.

    num_ctx capped at 4096 — qwen2.5:7b's default is 32k, which on a
    CPU box with long history makes prompt-processing take minutes
    before the first token emerges. 4096 matches Pupil (2026-04-19
    patch) and keeps first-token latency reasonable. Raise only when
    the 32 GB RAM upgrade lands."""
    model = model or MODELS["master"]
    log(f"LOCAL_STREAM [{model}]")
    payload = {"model": model, "messages": messages, "stream": True,
               "keep_alive": "30m",
               "options": {"num_ctx": 4096}}
    if image_path:
        try:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            payload["messages"][-1]["images"] = [b64]
        except Exception as e:
            log(f"IMAGE_ERROR: {e}")
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat", data=data,
        headers={"Content-Type": "application/json"}
    )
    _anim = local_thinking_start()
    try:
        full_text = []
        first_token_seen = False
        # Line-buffered color painter: tokens stream at char level but we
        # color-classify at newline boundaries so each complete line gets
        # the right Master AI brand color (PLAN/INFO/VOICE/CAUTION/SOURCES).
        line_buf = []
        def _flush_line(final=False):
            """Print complete lines in line_buf with the right brand color.
            Soft-wraps at SOFT_WRAP columns so the eye sees steady rolling
            progress on slow CPU inference instead of waiting for full
            newlines. Color classification still fires per soft-wrapped line.
            """
            SOFT_WRAP = 70  # phone-friendly + tmux-safe; narrower = smoother roll
            joined = "".join(line_buf)
            line_buf.clear()
            # Soft-wrap any long no-newline run at the last space before SOFT_WRAP.
            while len(joined) > SOFT_WRAP and "\n" not in joined[:SOFT_WRAP]:
                break_pos = joined.rfind(' ', 0, SOFT_WRAP)
                if break_pos < 30:  # no good space — hard-break at width
                    break_pos = SOFT_WRAP
                line, joined = joined[:break_pos], joined[break_pos:].lstrip()
                print(_paint_line(line + "\n"), end="", flush=True)
            while "\n" in joined:
                line, _, rest = joined.partition("\n")
                print(_paint_line(line + "\n"), end="", flush=True)
                joined = rest
            if final and joined:
                # Stream ended mid-line — paint what we have
                print(_paint_line(joined + "\n"), end="", flush=True)
            elif joined:
                # Partial line still forming; hold until newline or next soft-wrap
                line_buf.append(joined)
        # 300s timeout (2026-04-21 PM) — bumped from 180s after a direct
        # Ollama probe showed TTFT=220s on a cold context. 180s was firing
        # BEFORE the model produced its first token, making cloud fallback
        # the default path on every fresh turn. Groq then punts with
        # "what do you want to create?"-style replies because it doesn't
        # have the Modelfile baked. Giving master-ai 5 minutes before
        # giving up is the right trade: better a slow local answer than
        # a fast cloud punt. Revisit when 32 GB RAM + GPU upgrade lands.
        with urllib.request.urlopen(req, timeout=300) as resp:
            for line in resp:
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line.decode())
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        if not first_token_seen:
                            local_thinking_stop(_anim)
                            _anim = None
                            print(f"\n{M}  🥋{X} ", end="", flush=True)
                            first_token_seen = True
                        full_text.append(token)
                        line_buf.append(token)
                        # Only flush on newline — partial lines stream raw
                        if "\n" in token:
                            _flush_line()
                    if chunk.get("done"):
                        _flush_line(final=True)
                        break
                except Exception:
                    pass
        if not first_token_seen:
            # No tokens ever arrived — stop the animation cleanly
            local_thinking_stop(_anim)
            _anim = None
        print(f"\n", flush=True)
        result = "".join(full_text)
        # Harvest this call — streaming or not, the assembled answer is the payload
        if harvest is not None and result:
            try:
                last_user = next((m.get("content", "") for m in reversed(messages)
                                  if m.get("role") == "user"), "")
                if last_user:
                    harvest.record(last_user, model, result, task_type="local_stream")
            except Exception as e:
                log(f"HARVEST_RECORD_ERROR: {e}")
        return result if result else None
    except Exception as e:
        local_thinking_stop(_anim)
        _anim = None
        print(flush=True)
        log(f"STREAM_ERROR: {e}")
        return None
    finally:
        local_thinking_stop(_anim)

# ── LOCAL "THINKING" ANIMATION (before first Ollama token arrives) ──
# Ninja mood — shown while Sensei is actively working (model loading/generating).
# Loaded from ~/scripts/master_ai_voice.json so Sensei + Pupil share one voice;
# falls back to built-in list when the file is missing.
_VOICE_FILE = Path.home() / "scripts/master_ai_voice.json"
_VOICE_CACHE = None
def _load_voice():
    global _VOICE_CACHE
    if _VOICE_CACHE is not None:
        return _VOICE_CACHE
    try:
        if _VOICE_FILE.exists():
            _VOICE_CACHE = json.loads(_VOICE_FILE.read_text())
            return _VOICE_CACHE
    except Exception:
        pass
    _VOICE_CACHE = {}
    return _VOICE_CACHE

_DEFAULT_THINKING = [
    "Grinding...", "Pushing through...", "In deep meditation...",
    "Leveling up...", "Getting to the goal...", "Ninja-ing...",
    "Doing what ninjas do...",
]
_LOCAL_THINKING_LINES = _load_voice().get("thinking") or _DEFAULT_THINKING

def local_thinking_start():
    """Rotating narrative while Ollama loads/generates. Returns (stop_event, thread) or None.
    In TUI mode the rotation lives in the tip slot (not the scrollback) — the
    TUI refresh loop cycles the line every 1.8s until stop_thinking() fires."""
    if _SENSEI_APP is not None:
        try: _SENSEI_APP.start_thinking()
        except Exception: pass
        return ("tui", None)
    try:
        stop = threading.Event()
        def _run():
            i = 0
            while not stop.is_set():
                line = _LOCAL_THINKING_LINES[i % len(_LOCAL_THINKING_LINES)]
                sys.stdout.write(f"\r  {C}🥷 [thinking] {line}{X}" + " " * 20)
                sys.stdout.flush()
                stop.wait(1.8)
                i += 1
            sys.stdout.write("\r" + " " * 70 + "\r")
            sys.stdout.flush()
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return (stop, t)
    except Exception:
        return None

def local_thinking_stop(handle):
    if not handle:
        return
    # TUI-mode handle: tell the app to return the tip slot to idle mode.
    if isinstance(handle, tuple) and len(handle) == 2 and handle[0] == "tui":
        if _SENSEI_APP is not None:
            try: _SENSEI_APP.stop_thinking()
            except Exception: pass
        return
    try:
        stop, t = handle
        stop.set()
        t.join(timeout=1)
    except Exception:
        pass

# ── CLOUD AI ──────────────────────────────────────────────────
def ask_cloud_groq(messages):
    key = KEYS.get("groq")
    if not key:
        return None
    log("CLOUD [groq/llama-3.3-70b]")
    payload = {"model": "llama-3.3-70b-versatile", "messages": messages,
               "max_tokens": 1024, "stream": False}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions", data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                 "User-Agent": "python-requests/2.31.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        code = e.code
        label = {401:"AUTH FAIL — check API key", 403:"AUTH FAIL — check API key",
                 429:"RATE LIMIT hit", 402:"OUT OF CREDITS"}.get(code, f"HTTP {code}")
        log(f"GROQ_ERROR: {label}")
        return None
    except Exception as e:
        log(f"GROQ_ERROR: {e}")
        return None

def ask_cloud_openai(messages):
    key = KEYS.get("openai")
    if not key:
        return None
    log("CLOUD [openai/gpt-4o]")
    try:
        from openai import OpenAI
        resp = OpenAI(api_key=key).chat.completions.create(
            model="gpt-4o", messages=messages, max_tokens=1024)
        return resp.choices[0].message.content
    except Exception as e:
        log(f"OPENAI_ERROR: {e}")
        return None

def ask_cloud_gemini(messages):
    key = KEYS.get("gemini")
    if not key:
        return None
    log("CLOUD [gemini/1.5-flash]")
    text = "\n".join(m["content"] for m in messages if m["role"] != "system")
    payload = {"contents": [{"parts": [{"text": text}]}]}
    data = json.dumps(payload).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        log(f"GEMINI_ERROR: {e}")
        return None

def ask_cloud_anthropic(messages):
    key = KEYS.get("anthropic")
    if not key:
        return None
    log("CLOUD [anthropic/claude-sonnet-4-6]")
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msgs = [m for m in messages if m["role"] != "system"]
    payload = {"model": "claude-sonnet-4-6", "max_tokens": 1024, "system": system, "messages": user_msgs}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=data,
        headers={"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["content"][0]["text"]
    except Exception as e:
        log(f"ANTHROPIC_ERROR: {e}")
        return None

def ask_cloud_deepseek(messages):
    key = KEYS.get("deepseek")
    if not key:
        return None
    log("CLOUD [deepseek/R1-reasoner]")
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msgs = [m for m in messages if m["role"] != "system"]
    payload = {"model": "deepseek-reasoner", "max_tokens": 1024,
               "messages": [{"role": "system", "content": system}] + user_msgs if system else user_msgs}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions", data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
    except Exception as e:
        log(f"DEEPSEEK_ERROR: {e}")
        return None

def _ask_openrouter(messages, model, label, timeout=60):
    """Generic OpenRouter caller with token tracking."""
    key = KEYS.get("openrouter")
    if not key:
        return None
    log(f"CLOUD [openrouter/{label}]")
    payload = {"model": model, "messages": messages}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                 "HTTP-Referer": "http://localhost", "X-Title": "master-ai"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            tokens = result.get("usage", {}).get("total_tokens", 0)
            if tokens:
                try:
                    kf = str(Path.home() / ".master_ai_keys")
                    with open(kf) as _rf:
                        kd = json.load(_rf)
                    from datetime import date as _d
                    today = _d.today().isoformat()
                    if kd.get("openrouter_tokens_date") != today:
                        kd["openrouter_tokens_today"] = 0
                        kd["openrouter_tokens_date"] = today
                    kd["openrouter_tokens_today"] = kd.get("openrouter_tokens_today", 0) + tokens
                    with open(kf, "w") as _wf:
                        json.dump(kd, _wf, indent=2)
                    os.chmod(kf, 0o600)
                except Exception:
                    pass
            return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        code = e.code
        diag = {401:"AUTH FAIL — check API key", 403:"AUTH FAIL — check API key",
                429:"RATE LIMIT hit", 402:"OUT OF CREDITS"}.get(code, f"HTTP {code}")
        log(f"OPENROUTER_ERROR [{label}]: {diag}")
        return None
    except Exception as e:
        log(f"OPENROUTER_ERROR [{label}]: {e}")
        return None

def ask_cloud_openrouter_405b(messages):
    return _ask_openrouter(messages, "nousresearch/hermes-3-llama-3.1-405b:free", "hermes-405B", timeout=90)

def ask_cloud_openrouter_gptoss(messages):
    return _ask_openrouter(messages, "openai/gpt-oss-120b:free", "gpt-oss-120B", timeout=60)

def ask_cloud_openrouter_nemotron(messages):
    return _ask_openrouter(messages, "nvidia/nemotron-3-super-120b-a12b:free", "nemotron-120B", timeout=60)

def ask_cloud_openrouter_qwen3coder(messages):
    return _ask_openrouter(messages, "qwen/qwen3-coder:free", "qwen3-coder", timeout=60)

def ask_cloud_openrouter_r1(messages):
    return _ask_openrouter(messages, "deepseek/deepseek-r1:free", "deepseek-r1", timeout=90)

def ask_cloud_openrouter(messages):
    return _ask_openrouter(messages, "meta-llama/llama-3.3-70b-instruct:free", "llama-3.3-70b", timeout=30)

def ask_cloud(messages, provider="groq"):
    fn_map = {
        "groq":         ask_cloud_groq,
        "deepseek-r1":  ask_cloud_openrouter_r1,
        "gemini":       ask_cloud_gemini,
        "hermes-405b":  ask_cloud_openrouter_405b,
        "gpt-oss-120b": ask_cloud_openrouter_gptoss,
        "nemotron":     ask_cloud_openrouter_nemotron,
        "qwen3-coder":  ask_cloud_openrouter_qwen3coder,
        "openrouter":   ask_cloud_openrouter,
        "openai":       ask_cloud_openai,
        "anthropic":    ask_cloud_anthropic,
    }
    def _record(resp_text, used_model):
        if harvest is None or not resp_text:
            return
        try:
            last_user = next((m.get("content", "") for m in reversed(messages)
                              if m.get("role") == "user"), "")
            if last_user:
                harvest.record(last_user, used_model, resp_text, task_type="cloud")
        except Exception as e:
            log(f"HARVEST_RECORD_ERROR: {e}")

    r = fn_map.get(provider, ask_cloud_groq)(messages)
    if r:
        _record(r, provider)
        return r
    # Full fallback chain — biggest/best first, fastest last
    fallback_order = [
        ("hermes-405b", ask_cloud_openrouter_405b),
        ("deepseek-r1", ask_cloud_openrouter_r1),
        ("groq",        ask_cloud_groq),
        ("nemotron",    ask_cloud_openrouter_nemotron),
        ("gpt-oss-120b",ask_cloud_openrouter_gptoss),
        ("gemini",      ask_cloud_gemini),
        ("openrouter",  ask_cloud_openrouter),
    ]
    for used_model, fn in fallback_order:
        r = fn(messages)
        if r:
            _record(r, used_model)
            return r
    return None

# ── STT: WHISPER ──────────────────────────────────────────────
def record_audio(duration=5):
    print(f"{C}  🎤 Recording {duration}s — speak now...{X}")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    subprocess.run(["arecord", "-f", "cd", "-t", "wav", "-d", str(duration), tmp.name],
                   stderr=subprocess.DEVNULL)
    return tmp.name

def transcribe(audio_file):
    print(f"{Y}  📝 Transcribing...{X}")
    try:
        import warnings, io
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import whisper
            # Suppress CUDA/torch stderr noise
            devnull = open(os.devnull, 'w')
            old_stderr = os.dup(2)
            os.dup2(devnull.fileno(), 2)
            try:
                model = whisper.load_model(WHISPER_MODEL)
                result = model.transcribe(audio_file)
            finally:
                os.dup2(old_stderr, 2)
                os.close(old_stderr)
                devnull.close()
        text = result["text"].strip()
        if text:
            log(f"HEARD: {text}")
        os.unlink(audio_file)
        return text
    except Exception as e:
        log(f"WHISPER_ERROR: {e}")
        return ""

# ── TTS: PIPER ────────────────────────────────────────────────
TTS_MAX_CHARS = 500  # truncate long replies so TTS doesn't hang on documents

def speak(text):
    if not text:
        return
    # Strip directives and code blocks — not useful to hear
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL).strip()
    text = re.sub(r'(RUNTERM:|RUN:|READ:|CREATE:|EDIT:|THINK:|DONE:)\s*\S+.*', '', text).strip()
    if not text:
        return
    if len(text) > TTS_MAX_CHARS:
        text = text[:TTS_MAX_CHARS] + "... message truncated."
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        proc = subprocess.run(
            ["piper", "--model", str(PIPER_MODEL), "--output_file", tmp.name],
            input=text.encode(), capture_output=True, timeout=30
        )
        if proc.returncode == 0:
            subprocess.run(["aplay", tmp.name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        else:
            log(f"PIPER_ERROR: {proc.stderr.decode()[:100]}")
    except subprocess.TimeoutExpired:
        log("TTS_TIMEOUT: piper/aplay took too long, skipping")
    except Exception as e:
        log(f"TTS_ERROR: {e}")
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

# ── TASK TRACKER ─────────────────────────────────────────────
def load_tasks():
    try:
        return json.loads(TASKS_FILE.read_text())
    except Exception:
        return []

def save_tasks(tasks):
    try:
        TASKS_FILE.write_text(json.dumps(tasks, indent=2))
    except Exception:
        pass

def active_task_count():
    return sum(1 for t in load_tasks() if not t.get("done", False))

def show_tasks():
    tasks = load_tasks()
    if not tasks:
        print(f"  {W}No tasks. Use: task add <text>{X}\n")
        return
    print(f"\n{C}  Tasks:{X}")
    for i, t in enumerate(tasks, 1):
        done = t.get("done", False)
        icon = f"{G}✅{X}" if done else f"{Y}○ {X}"
        print(f"  {icon} {i}) {W}{t.get('text','')}{X}")
    print()

def handle_task_cmd(cmd):
    """Handle task add/done/list/clear/toggle commands."""
    lo = cmd.lower().strip()
    tasks = load_tasks()

    if lo in ("task", "task list", "tasks"):
        show_tasks()
        return True

    if lo == "task clear":
        save_tasks([])
        print(f"  {G}✅ All tasks cleared.{X}")
        return True

    if lo.startswith("task add "):
        text = cmd[9:].strip()
        if text:
            tasks.append({"text": text, "done": False})
            save_tasks(tasks)
            play_anim(_A_PUNCH, delay=0.1, color=Y)
            print(f"  {G}✅ Task added: {W}{text}{X}")
        return True

    if lo.startswith("task done ") or lo.startswith("task rm "):
        prefix_len = 10 if lo.startswith("task done ") else 8
        try:
            n = int(cmd[prefix_len:].strip()) - 1
            if 0 <= n < len(tasks):
                tasks[n]["done"] = True
                save_tasks(tasks)
                print(f"  {G}✅ Done: {W}{tasks[n]['text']}{X}")
            else:
                print(f"  {R}❌ No task #{n+1}{X}")
        except (ValueError, IndexError):
            print(f"  {Y}Usage: task done <number>{X}")
        return True

    if re.match(r'^task\s+\d+$', lo):
        try:
            n = int(lo.split()[1]) - 1
            if 0 <= n < len(tasks):
                tasks[n]["done"] = not tasks[n]["done"]
                save_tasks(tasks)
                state = "done" if tasks[n]["done"] else "undone"
                print(f"  {G}✅ Marked {state}: {W}{tasks[n]['text']}{X}")
        except Exception:
            pass
        return True

    return False

# ── HISTORY COMPACT ───────────────────────────────────────────
def compact_history(history):
    """Keep system message + last 20 exchanges (40 msgs). Silent."""
    system = [m for m in history if m.get("role") == "system"]
    convo  = [m for m in history if m.get("role") != "system"]
    if len(convo) > 40:
        history[:] = system + convo[-40:]

# ── AUTO FILE INJECTION ───────────────────────────────────────
def auto_inject_context(user_text):
    """Scan message for file paths/names, inject up to 3 files as [AUTO-CONTEXT]."""
    search_dirs = [Path.home() / "scripts", Path(os.getcwd())]
    injected = []
    seen = set()

    path_re = re.compile(
        r'(?:~/[\w/.\-]+\.[\w]+|\.\/[\w/.\-]+\.[\w]+|/[\w/.\-]+\.[\w]+|'
        r'[\w\-]+\.(?:py|sh|js|ts|html|css|json|txt|md|yaml|yml|conf|cfg|toml))'
    )
    candidates = path_re.findall(user_text)

    for c in candidates:
        if len(injected) >= 3:
            break
        expanded = os.path.expanduser(c)
        if expanded in seen:
            continue
        seen.add(expanded)

        path = None
        if os.path.isfile(expanded):
            path = Path(expanded)
        else:
            fname = Path(c).name
            for d in search_dirs:
                candidate = d / fname
                if candidate.is_file():
                    path = candidate
                    break

        if path:
            try:
                content = path.read_text(errors='replace')[:3000]
                injected.append(f"--- {path} ---\n{content}")
            except Exception:
                pass

    if not injected:
        return ""
    labels = ", ".join(str(Path(s.split('\n')[0].strip('- ')).name) for s in injected)
    print(f"  {D}[auto-context: {labels}]{X}")
    return "\n\n[AUTO-CONTEXT — files mentioned in your message]\n" + "\n\n".join(injected)

# ── MEMORY ────────────────────────────────────────────────────
def load_memory():
    try:
        return MEMORY_FILE.read_text().strip()
    except Exception:
        return ""

# ── APPROVED COMMANDS ─────────────────────────────────────────
def load_approved():
    try:
        return set(l for l in APPROVED_FILE.read_text().splitlines() if l.strip())
    except Exception:
        return set()

def save_approved(cmd):
    approved = load_approved()
    approved.add(cmd)
    APPROVED_FILE.write_text('\n'.join(sorted(approved)) + '\n')

# ── RESPONSE CACHE ───────────────────────────────────────────
_RICH_OK = False
try:
    from rich.console import Console as _RichConsole
    from rich.markdown import Markdown as _RichMarkdown
    _RICH_CONSOLE = _RichConsole(soft_wrap=True)
    _RICH_OK = True
except ImportError:
    pass

def render_reply(text, prefix=None, suffix=None):
    """Render AI reply as markdown via rich when available. Falls back to
    plain colored print.

    NOTE: rich.console.Console caches sys.stdout at construction time, so the
    module-level _RICH_CONSOLE points at the ORIGINAL stdout. Under the TUI
    shim that means AI replies never reach the scrollable output region.
    We construct a fresh Console each call so it picks up whatever stdout
    is live right now (shim or original).
    """
    if prefix:
        print(prefix, end="", flush=True)
    if _RICH_OK:
        try:
            # Fresh console → always writes to CURRENT sys.stdout.
            _RichConsole(soft_wrap=True, file=sys.stdout).print(
                _RichMarkdown(text or "", code_theme="monokai")
            )
        except Exception:
            print(text or "")
    else:
        print(text or "")
    if suffix:
        print(suffix)

_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]|\x1b[@-_]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
def sanitize(text):
    if not isinstance(text, str):
        return text
    cleaned = _ANSI_RE.sub('', text)
    return cleaned.strip()

def read_nav_key(prompt):
    """Read a single navigation key OR a full typed line.
    Returns one of: 'next', 'prev', 'quit', '' (empty stay), or the typed text.
    Arrows: → / ↑ = next, ← / ↓ = prev, Esc/q/x = quit, Enter = next."""
    sys.stdout.write(prompt); sys.stdout.flush()
    if not sys.stdin.isatty():
        try: return sanitize(input(""))
        except EOFError: return "quit"
    try:
        import termios, tty, select
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)   # keep echo + signals; just disable line buffering
            # os.read bypasses Python's stdin buffer — critical for arrow keys
            b = os.read(fd, 1)
            ch = b.decode('utf-8', errors='ignore')
            if ch == '\x1b':
                r, _, _ = select.select([fd], [], [], 0.15)
                seq_bytes = os.read(fd, 4) if r else b''
                seq = seq_bytes.decode('utf-8', errors='ignore')
                if seq.startswith(('[C', '[A', 'OC', 'OA')):
                    sys.stdout.write('\n'); return "next"
                if seq.startswith(('[D', '[B', 'OD', 'OB')):
                    sys.stdout.write('\n'); return "prev"
                sys.stdout.write('\n'); return "quit"
            if ch in ('\r', '\n', ' '):
                sys.stdout.write('\n'); return "next"
            if ch in ('n', 'N'):
                sys.stdout.write('\n'); return "next"
            if ch in ('b', 'B', 'p', 'P'):
                sys.stdout.write('\n'); return "prev"
            if ch in ('q', 'Q', 'x', 'X'):
                sys.stdout.write('\n'); return "quit"
            if ch == '\x03':
                raise KeyboardInterrupt
            if ch == '\x7f':
                sys.stdout.write('\n'); return ""
            # Printable non-nav char → fall back to cooked-mode line entry
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        try:
            rest = input("")
            return sanitize(ch + rest)
        except EOFError:
            return "quit"
    except Exception as e:
        log(f"READ_NAV_ERROR: {e}")
        try: return sanitize(input("")) or "next"
        except EOFError: return "quit"

def cache_key(text):
    return hashlib.md5(text.strip().lower().encode()).hexdigest()

_ERROR_MARKERS = ("unavailable", "timed out", "no response", "error:", "failed")

def _is_error_reply(r):
    if not r:
        return True
    lo = r.lower()
    return any(m in lo for m in _ERROR_MARKERS) and len(r) < 200

def cache_lookup(text):
    try:
        cache = json.loads(CACHE_FILE.read_text())
        k = cache_key(text)
        entry = cache.get(k)
        if entry and (time.time() - entry.get("ts", 0)) < 86400:
            reply = entry["reply"]
            if _is_error_reply(reply):
                del cache[k]
                CACHE_FILE.write_text(json.dumps(cache))
                return None
            entry["hits"] = entry.get("hits", 0) + 1
            CACHE_FILE.write_text(json.dumps(cache))
            return reply
    except Exception:
        pass
    return None

def cache_store(text, reply):
    if _is_error_reply(reply):
        return
    try:
        try:
            cache = json.loads(CACHE_FILE.read_text())
        except Exception:
            cache = {}
        cache[cache_key(text)] = {"reply": reply, "ts": time.time(), "hits": 0}
        if len(cache) > 200:
            oldest = sorted(cache.items(), key=lambda x: x[1].get("ts", 0))
            for k, _ in oldest[:40]:
                del cache[k]
        CACHE_FILE.write_text(json.dumps(cache))
    except Exception:
        pass

# ── GIT CONTEXT ───────────────────────────────────────────────
def git_context():
    try:
        cwd = os.getcwd()
        branch = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3).stdout.strip()
        if not branch or branch == "HEAD":
            return ""
        log_out = subprocess.run(
            ["git", "-C", cwd, "log", "--oneline", "-3"],
            capture_output=True, text=True, timeout=3).stdout.strip()
        return f"[GIT] branch={branch}\n{log_out}" if log_out else f"[GIT] branch={branch}"
    except Exception:
        return ""

# ── NINJA ANIMATIONS ─────────────────────────────────────────
def play_anim(frames, delay=0.13, color=None):
    """Print ASCII animation frames in-place."""
    color = color or BC
    if not frames:
        return
    # If not a real interactive terminal, just print final frame silently
    if not sys.stdout.isatty():
        return
    h = len(frames[0])
    for i, frame in enumerate(frames):
        if i > 0:
            sys.stdout.write(f"\033[{h}A")
        for line in frame:
            sys.stdout.write(f"\033[2K  {color}{line:<26}{X}\n")
        sys.stdout.flush()
        time.sleep(delay)
    print()

# ── SAFE MODE — guard stance ──────────────────────────────────
_A_SAFE = [
    ["      ___        ",
     "   ══(o_o)══     ",
     "      \\*/        ",
     "      /|\\        ",
     "     /   \\       "],
    ["   /  ___  \\     ",
     "  ║ =(o_o)= ║    ",
     "  ║   \\*/   ║    ",
     "   \\  /|\\  /     ",
     "      / \\        "],
    ["  ╔══(___) ══╗   ",
     "  ║  (o_o)  ║    ",
     "  ║   \\*/   ║    ",
     "  ╚═══/|\\═══╝    ",
     "     [GUARDED]   "],
]

# ── PLAN MODE — meditation ────────────────────────────────────
_A_PLAN = [
    ["      ___        ",
     "   ══(o_o)══     ",
     "      /|\\        ",
     "     / | \\       ",
     "    /  |  \\      "],
    ["      ___        ",
     "   ══(-_-)══     ",
     "    __(|)__      ",
     "   /  /|\\  \\     ",
     "  /  /   \\  \\    "],
    ["      ___        ",
     "   ══(~_~)══     ",
     "  /‾‾‾|‾‾‾\\     ",
     " |  z z z  |     ",
     "  \\_______/      "],
    ["      ___        ",
     "   ══(- -)══     ",
     "  /‾‾‾|‾‾‾\\     ",
     " |   ─OM─  |     ",
     "  \\_______/      "],
]

# ── AUTO MODE — charging ninja ────────────────────────────────
_A_AUTO = [
    ["  ___            ",
     "=(o▶o)=          ",
     "  )|( >>         ",
     " / \\ >>          ",
     "/   \\            "],
    ["      ___        ",
     "   >=(o▶o)=      ",
     "      )|( >>>    ",
     "     / \\         ",
     "    /   \\        "],
    ["           ___   ",
     "  >>> >>> =(o▶o)=",
     "           )|(⚡  ",
     "          / \\    ",
     "         /   \\   "],
]

# ── MODEL PICKER — spinning shuriken ─────────────────────────
_A_SHURIKEN = [
    ["   ✦  ─┼─  ✦    ",
     "      ─┼─        ",
     "   ✦  ─┼─  ✦    "],
    ["    ╲  ─╬─  ╱   ",
     "       ─╬─       ",
     "    ╱  ─╬─  ╲   "],
    ["   ✧  ═╬═  ✧    ",
     "      ═╬═        ",
     "   ✧  ═╬═  ✧    "],
    ["  ★★  ═╬═  ★★   ",
     "      ═╬═        ",
     "  ★★  ═╬═  ★★   "],
]

# ── SAVE SESSION — bow ────────────────────────────────────────
_A_BOW = [
    ["      ___        ",
     "   ══(o_o)══     ",
     "      /|\\        ",
     "     /   \\       "],
    ["      ___        ",
     "   ══(o_o)══     ",
     "     \\|/         ",
     "     / \\         "],
    ["   ___           ",
     "  (o_o)══        ",
     "  _\\|            ",
     "   / \\           "],
    ["  ___            ",
     " (^_^)══         ",
     "  _\\|            ",
     "   / \\           "],
]

# ── TASK ADD — punch ─────────────────────────────────────────
_A_PUNCH = [
    ["   o             ",
     "  /|\\            ",
     "  / \\            "],
    ["   o             ",
     "  \\|~>           ",
     "  / \\            "],
    ["   o             ",
     "  \\| ~~> ✦       ",
     "  / \\            "],
]

# ── EXIT — vanish ─────────────────────────────────────────────
_A_VANISH = [
    ["      ___        ",
     "   ══(o_o)══     ",
     "      /|\\        ",
     "     /   \\       "],
    ["      ___        ",
     "   ══(o_o)══  ~  ",
     "      /|\\   ~~   ",
     "     /   \\ ~~~   "],
    ["      ___        ",
     "   ══(._.)══ ~~~ ",
     "      /|\\ ~~~~~  ",
     "     /   \\       "],
    ["       _         ",
     "    ══(.)══ ~~~  ",
     "       |  ~~~~~  ",
     "       |         "],
    ["                 ",
     "       ~ ~~~~    ",
     "      ~  ~~~~    ",
     "                 "],
]

# ── STARTUP — ninja appears ───────────────────────────────────
_A_APPEAR = [
    ["                 ",
     "                 ",
     "    ~ ~~~~       ",
     "   ~  ~~~~       ",
     "                 "],
    ["       _         ",
     "    ══(.)══      ",
     "       |  ~~~~   ",
     "       |         "],
    ["      ___        ",
     "   ══(._.)══     ",
     "      /|\\        ",
     "     /   \\       "],
    ["      ___        ",
     "   ══(o_o)══     ",
     "      /|\\        ",
     "     /   \\       "],
]

# ── HINT SYSTEM ───────────────────────────────────────────────
def show_hint(title, body):
    global HINTS
    if not HINTS:
        return
    print(f"\n  {C}◈ {Y}{title}{X}")
    print(f"  {C}{'─'*55}{X}")
    for line in body.strip().splitlines():
        if line.strip():
            print(f"  {W}▸ {line}{X}")
    print(f"  {C}{'─'*55}{X}")
    print(f"  {W}{Y}type hints off to disable tips{X}\n")

# ── MODE HELPERS ──────────────────────────────────────────────
def mode_label():
    global MODE
    labels = {"review": f"{R}REVIEW{X}", "plan": f"{Y}PLAN{X}", "auto": f"{G}AUTO{X}"}
    return labels.get(MODE, MODE.upper())

def show_plan_demo():
    os.system("clear")
    steps = [
        (f"{Y}STEP 1{X} — Switch to plan mode",
         f"  {C}🥷{X}  {W}mode plan{X}",
         f"  {G}✅ Mode: PLAN — AI shows plan first, 'go' to run{X}"),
        (f"{Y}STEP 2{X} — Ask AI to do something",
         f"  {C}🥷{X}  {W}check my disk space and show free memory{X}",
         f"  {M}  🥋{X} {C}Here is my plan:\n"
         f"         1. Run: df -h\n"
         f"         2. Run: free -h\n"
         f"  {Y}  Type 'go' to execute or 'cancel' to clear.{X}"),
        (f"{Y}STEP 3{X} — Type 'go' to run it",
         f"  {C}🥷{X}  {W}go{X}",
         f"  {W}  Pending plan: check my disk space and show free memory{X}\n"
         f"  {C}  Execute plan? (y/N):{X}  {W}y{X}"),
        (f"{Y}STEP 4{X} — AI runs the commands",
         f"  {M}  🥋{X} {C}RUN: df -h{X}",
         f"  {G}  Filesystem  Size  Used  Avail\n"
         f"  /dev/sda1   232G  121G   99G   56%{X}\n"
         f"  {M}  🥋{X} {C}RUN: free -h{X}\n"
         f"  {G}  Mem: 32G used: 12G free: 18G{X}"),
        (f"{Y}OTHER OPTIONS{X}",
         f"  {W}cancel{X}        — discard the plan, start over",
         f"  {W}mode review{X}   — switch to per-command confirm (asks before each action)\n"
         f"  {W}mode auto{X}     — run ALL commands without any prompts"),
    ]
    bar = f"{BC}{'═'*60}{X}"
    print(f"\n{bar}")
    print(f"{BC}  🥷  PLAN MODE — How it works{X}")
    print(f"{bar}\n")
    for title, user_line, ai_line in steps:
        print(f"  {title}")
        print(f"  {user_line}")
        print(f"  {ai_line}")
        print()
        try:
            input(f"  {D}[ press Enter for next step ]{X}  ")
        except (EOFError, KeyboardInterrupt):
            break
        os.system("clear")
        print(f"\n{bar}")
        print(f"{BC}  🥷  PLAN MODE — How it works{X}")
        print(f"{bar}\n")
    print(f"  {G}That's it! Type 'mode plan' and try it for real.{X}\n")
    print(f"  {C}Switch back to Plan mode anytime:{X}  {W}mode plan{X}\n")

# Single source of truth for what each mode means. draw_status_bar,
# show_mode_status, and the mode-change handler in main() all read from
# here — so the top overlay, the mid-screen animation, and the hint
# banner stay in sync. Adding a mode? Add ONE entry here.
MODE_CONTRACTS = {
    "plan": {
        "tagline": "brainstorm + draft plans — default, no execution",
        "contract": (
            "1. Chat freely — I won't touch the system unless you approve a plan.\n"
            "2. Ask me to do something, I draft a plan; press 1 or Enter to run it.\n"
            "3. Press 2 to edit the plan, 3 to discard, 4 to keep talking.\n"
            "4. Good for thinking out loud, mapping out work, learning."
        ),
    },
    "review": {
        "tagline": "asks before every command (per-action confirm)",
        "contract": (
            "1. Every RUN: / EDIT: / CREATE: asks '1/2/3/4/5 — Yes/Always/No/Edit/Ask'.\n"
            "2. Shows who / what / why / where before the prompt.\n"
            "3. Destructive patterns (rm -rf, drop table, force-push) still pause.\n"
            "4. Sudo is always handed off to your terminal — never runs inline.\n"
            "5. Use this when you want to watch every step land."
        ),
    },
    "auto": {
        "tagline": "commands flow without asking (destructive still pauses)",
        "contract": (
            "1. Execute immediately — RUN: / EDIT: / CREATE: fire without asking.\n"
            "2. Minimize interruptions — no pauses for routine questions.\n"
            "3. Prefer action over planning — start working.\n"
            "4. Course corrections welcome — 'mode plan' or 'mode review' takes the wheel back.\n"
            "5. Destructive actions still pause — rm -rf, drop table, force-push,\n"
            "   package uninstall, ollama rm, chmod -R, systemctl stop.\n"
            "6. No data exfiltration — secrets/keys never sent to external services."
        ),
    },
}

# Title shown atop the contract.
MODE_HINT_TITLES = {
    "plan": "Plan Mode — brainstorm + draft plans",
    "review": "Review Mode — confirm every command",
    "auto": "⚠  Auto Mode Active — you are allowing:",
}


def show_mode_status():
    global MODE
    anims = {"review": (_A_SAFE, R), "plan": (_A_PLAN, Y), "auto": (_A_AUTO, G)}
    frames, color = anims.get(MODE, (_A_PLAN, Y))
    play_anim(frames, delay=0.12, color=color)
    contract = MODE_CONTRACTS.get(MODE, {})
    print(f"  {C}Mode: {mode_label()}  —  {contract.get('tagline','')}{X}\n")
    # Always print the full contract so switching modes never leaves an
    # older mode's hint as the last visible text in scrollback.
    if contract.get("contract"):
        show_hint(MODE_HINT_TITLES.get(MODE, f"Mode: {MODE}"),
                  contract["contract"] + "\n\nType 'mode plan' to go back to default.")

# ── TUTORIAL ─────────────────────────────────────────────────
def run_tutorial():
    STEPS = [
        ("Welcome to Master AI",
         "I'm an AI agent that runs directly on this PC.\nI can execute commands, write files, search the web, and more.\nJust type what you need — in plain English."),
        ("How to talk to me",
         "Type any request and press Enter.\nExamples:\n  List files in my home folder\n  Install ffmpeg\n  Write a Python script that renames files\n  What is my IP address?"),
        ("Modes: Plan / Review / Auto",
         "mode plan    → brainstorm + draft plans (default, no execution)\nmode review  → ask before every command (per-action confirm)\nmode auto    → run commands without asking (destructive still pauses)"),
        ("Memory",
         "remember: I prefer dark mode\n  → teaches me a fact to keep across sessions\nforget: dark mode\n  → removes matching facts\nmemory\n  → shows all stored facts"),
        ("Voice Input",
         "Type 'v' and press Enter to record your voice.\nI'll transcribe and send it.\nType 'r 10' to record for 10 seconds."),
        ("Projects",
         "project ~/myapp\n  → sets the active project; I'll scan the file structure\n  → all my commands will run relative to that directory"),
        ("Scrolling the chat",
         "up          → scroll chat output up one page (typed word)\ndown        → scroll down one page\nup 3        → scroll up 3 pages\ntop         → jump to the oldest message\nbottom      → jump back to the latest (auto-follow)\nlast        → re-print the last AI reply inline\n\nThe input box stays pinned at the bottom — scrolling never moves your cursor.\nOn a phone where mouse wheel is unreliable, typed words work every time."),
        ("Hints and Help",
         "help        → quick reference card\nhints off   → disable these tips\nhints on    → re-enable tips\ntutorial    → replay this walkthrough"),
    ]
    total = len(STEPS)
    step = 0
    while step < total:
        os.system("clear")
        print(f"\n{D}  {'━'*60}{X}")
        print(f"  {C}Tutorial  —  Step {step+1} of {total}{X}")
        print(f"{D}  {'━'*60}{X}\n")
        title, body = STEPS[step]
        print(f"  {BOLD}{W}{title}{X}\n")
        for line in body.strip().splitlines():
            print(f"  {W}{line}{X}")
        print(f"\n{D}  {'━'*60}{X}\n")
        if step == total - 1:
            input(f"  {G}Press Enter to finish...{X}")
            break
        nav = input(f"  {Y}n{X}=next  {Y}b{X}=back  {Y}s{X}=skip  ").strip().lower()
        if nav == 'b' and step > 0:
            step -= 1
        elif nav == 's':
            break
        else:
            step += 1
    TUTORIAL_FILE.touch()

# ── MODEL PICKER ──────────────────────────────────────────────
def show_model_menu():
    global PINNED_MODEL
    os.system("clear")
    play_anim(_A_SHURIKEN, delay=0.1, color=BC)
    print(f"\n{BC}  ╔{'═'*62}╗{X}")
    print(f"{BC}  ║{X}  {BW}🥷  Model Selector — pick one or type 'auto'{' '*20}{BC}║{X}")
    print(f"{BC}  ╠{'═'*62}╣{X}")
    print(f"{BC}  ║{X}  {D}LOCAL MODELS (your machine — private, free){' '*17}{BC}║{X}")
    local_entries = [(i+1, m, d) for i,(m,d) in enumerate(MODEL_MENU) if not m.startswith('☁') and '☁' not in d]
    cloud_entries = [(i+1, m, d) for i,(m,d) in enumerate(MODEL_MENU) if '☁' in d]
    for idx, (num, m, desc) in enumerate(local_entries):
        active = f"{G} ◀ active{X}" if PINNED_MODEL == m else ""
        print(f"{BC}  ║{X}  {Y}{num}){X}  {W}{m:<24}{C}{desc}{active}")
    print(f"{BC}  ║{X}")
    print(f"{BC}  ║{X}  {D}CLOUD MODELS (free — via your keys){' '*25}{BC}║{X}")
    for idx, (num, m, desc) in enumerate(cloud_entries):
        display_num = len(local_entries) + idx + 1
        active = f"{G} ◀ active{X}" if PINNED_MODEL == m else ""
        print(f"{BC}  ║{X}  {Y}{display_num}){X}  {W}{m:<24}{C}{desc}{active}")
    print(f"{BC}  ║{X}")
    if PINNED_MODEL:
        print(f"{BC}  ║{X}  {G}Pinned: {W}{PINNED_MODEL}{X}  {D}(type 'model auto' to clear){X}")
    else:
        print(f"{BC}  ║{X}  {C}Routing: {G}AUTO{X}  {D}(smart routing by task type){X}")
    print(f"{BC}  ╚{'═'*62}╝{X}")
    print(f"\n  {D}Type a number to pin that model, or 'model auto' to use smart routing.{X}\n")
    choice = input(f"  {C}Select (1-{len(MODEL_MENU)} or auto): {X}").strip().lower()
    if choice in ("auto", "a", ""):
        globals()['PINNED_MODEL'] = None
        print(f"  {G}✅ Smart routing restored.{X}")
    else:
        try:
            n = int(choice) - 1
            model_name = MODEL_MENU[n][0]
            globals()['PINNED_MODEL'] = model_name
            print(f"  {G}✅ Pinned to: {W}{model_name}{X}")
        except (ValueError, IndexError):
            print(f"  {Y}  Invalid choice — routing unchanged.{X}")

# ── THOUGHT-CLOUD: rotating tips line above prompt while idle ─────
# Pulled from master_ai_voice.json — trademark quotes mixed with command tips,
# so the idle bubble occasionally drops a brand line like "Your AI. Every entry
# point. Your hardware." alongside practical hints. One voice, one accord.
# Tuple form: ("QUOTE" entries use "" in cmd slot + quote in desc; "TIP" entries
# use cmd + desc like before.) The rendering code handles both.
def _build_idle_tips():
    v = _load_voice()
    out = []
    # Command tips first (solid practical value)
    for t in (v.get("tips") or []):
        cmd, desc = t.get("cmd", ""), t.get("desc", "")
        if cmd and desc:
            out.append((cmd, desc))
    # Trademark quotes interleaved every few tips — they'll rotate past regularly
    for q in (v.get("quotes") or []):
        out.append(("", q))     # empty cmd = render as italic quote line
    # Fallback to a tiny default pool so Sensei never has an empty rotator
    if not out:
        out = [
            ("hub",     "18-action control panel"),
            ("help",    "8-slide command reference"),
            ("refresh", "soft-restart if screen glitches"),
            ("",        "Your AI. Every entry point. Your hardware."),
        ]
    return out

_IDLE_TIPS = _build_idle_tips()

_IDLE_STOP = threading.Event()
_IDLE_THREAD = None
_IDLE_IDX = 0

# Post-reply grace: the user needs a window to READ what just came back
# before Sensei starts flashing tips above the prompt. Without this, a
# tip can appear 30 seconds after the reply finishes while the user is
# still absorbing the answer. 10s is enough breathing room for short
# replies; long replies they'll still be reading past the grace, but
# that's handled by the 30s grace-sec after they actually stop reading.
_POST_REPLY_GRACE = 10.0
_LAST_BUSY_CLEARED_TS = 0.0

def _is_sensei_idle():
    """True-idle predicate used by the idle-tips thread. The user is
    TRULY idle only when ALL of these are true:
      - No worker is currently generating a reply (_WORKER_BUSY cleared)
      - No queued work is waiting to be picked up (queue empty)
      - At least _POST_REPLY_GRACE seconds since the last reply finished
    Any 'no' here means don't rotate tips — respect their flow."""
    if _WORKER_BUSY.is_set():
        return False
    try:
        if _QUERY_QUEUE.qsize() > 0:
            return False
    except Exception:
        pass
    if _LAST_BUSY_CLEARED_TS > 0:
        if (time.time() - _LAST_BUSY_CLEARED_TS) < _POST_REPLY_GRACE:
            return False
    return True

_DIM   = '\033[3m'          # italic only — visible on light bg
_THINK = '\033[3;38;5;240m' # italic + darker grey, readable on light terminal

def _idle_tips_runner():
    """Background: cycle tips on the reserved line above the prompt.
    Waits 15s of continuous empty-buffer idle before first tip. Polls
    readline's buffer — if user types anything, wipes tip and re-starts
    the 15s idle counter. Tips rotate every ~5s while idle stays true."""
    global _IDLE_IDX
    tip_on_screen = False
    idle_since = time.time()   # reset whenever buffer becomes non-empty or stays non-empty
    GRACE_SEC = 30.0
    ROTATE_SEC = 5.0
    last_rotate = 0.0

    def _buffer_has_text():
        try:
            import readline as _rl
            return bool(_rl.get_line_buffer().strip())
        except Exception:
            return False

    while not _IDLE_STOP.is_set():
        # True-idle check — worker busy OR queued work OR just-finished-a-reply
        # all count as "not idle." Keeps tips from stomping on fresh replies
        # the user is still reading.
        if not _is_sensei_idle():
            if tip_on_screen:
                try:
                    sys.stdout.write("\x1b[s\x1b[1A\r\x1b[2K\x1b[u")
                    sys.stdout.flush()
                except Exception: pass
                tip_on_screen = False
            idle_since = time.time()
            last_rotate = 0.0
            if _IDLE_STOP.wait(0.4):
                break
            continue

        if _buffer_has_text():
            # User is composing — wipe tip, reset the idle counter
            if tip_on_screen:
                try:
                    sys.stdout.write("\x1b[s\x1b[1A\r\x1b[2K\x1b[u")
                    sys.stdout.flush()
                except Exception: pass
                tip_on_screen = False
            idle_since = time.time()   # whenever they clear the line, 30s starts fresh
            last_rotate = 0.0
            if _IDLE_STOP.wait(0.4):
                break
            continue

        # Buffer is empty — but have we been idle long enough to show anything?
        idle_for = time.time() - idle_since
        if idle_for < GRACE_SEC:
            if _IDLE_STOP.wait(0.4):
                break
            continue

        # We're past the grace period. Show or rotate tip.
        now = time.time()
        if (now - last_rotate) >= ROTATE_SEC or not tip_on_screen:
            cmd, desc = _IDLE_TIPS[_IDLE_IDX % len(_IDLE_TIPS)]
            _IDLE_IDX += 1
            try:
                cols = shutil.get_terminal_size((80, 24)).columns
                sys.stdout.write("\x1b[s\x1b[1A\r\x1b[2K")
                if cmd == "":
                    # Trademark quote — italic, full width, centered mood
                    quote_trim = desc[: max(0, cols - 6)]
                    sys.stdout.write(f"  💭  {_DIM}{C}“{quote_trim}”{X}")
                else:
                    # Command tip — yellow cmd column + cyan desc
                    desc_trim = desc[: max(0, cols - 6 - 14 - 1)]
                    sys.stdout.write(f"  💭  {Y}{cmd:<14}{X}{C}{desc_trim}{X}")
                sys.stdout.write("\x1b[u")
                sys.stdout.flush()
                tip_on_screen = True
                last_rotate = now
            except Exception:
                pass
        if _IDLE_STOP.wait(0.4):
            break

    # Thread exit — clear the tip row so no stale text lingers
    try:
        sys.stdout.write("\x1b[s\x1b[1A\r\x1b[2K\x1b[u")
        sys.stdout.flush()
    except Exception:
        pass

def start_idle_tips():
    """Reserve a line above the prompt and spin up the rotation thread."""
    global _IDLE_THREAD
    if not sys.stdout.isatty():
        return
    print()
    _IDLE_STOP.clear()
    _IDLE_THREAD = threading.Thread(target=_idle_tips_runner, daemon=True)
    _IDLE_THREAD.start()

def stop_idle_tips():
    """Signal the idle thread to clear the tip line and exit."""
    _IDLE_STOP.set()
    t = _IDLE_THREAD
    if t is not None:
        try: t.join(timeout=0.3)
        except Exception: pass

# ── THOUGHT-CLOUD while AI is thinking (not idle — model generating) ──
_THINK_TIPS = [
    ("thinking...",     "checking memory for context"),
    ("thinking...",     "routing through fallback chain"),
    ("type ahead",      "I'll queue your next message"),
    ("slow?",           "try 'model groq' next time"),
    ("cache",           "response cache stats"),
    ("save session",    "archive now + generate summary"),
    ("scrollback",      "50k lines — drag to copy back"),
]
_THINK_STOP = threading.Event()
_THINK_THREAD = None
_THINK_IDX = 0

def _think_runner():
    global _THINK_IDX
    while not _THINK_STOP.is_set():
        cmd, desc = _THINK_TIPS[_THINK_IDX % len(_THINK_TIPS)]
        _THINK_IDX += 1
        try:
            cols = shutil.get_terminal_size((80, 24)).columns
            desc_trim = desc[: max(0, cols - 6 - 14 - 1)]
            sys.stdout.write("\x1b[s\x1b[1A\r\x1b[2K")
            sys.stdout.write(f"  💭  {Y}{cmd:<14}{X}{C}{desc_trim}{X}")
            sys.stdout.write("\x1b[u")
            sys.stdout.flush()
        except Exception:
            pass
        if _THINK_STOP.wait(2.5):
            break
    try:
        sys.stdout.write("\x1b[s\x1b[1A\r\x1b[2K\x1b[u")
        sys.stdout.flush()
    except Exception:
        pass

def start_thinking_tips():
    global _THINK_THREAD
    if not sys.stdout.isatty():
        return
    print()
    _THINK_STOP.clear()
    _THINK_THREAD = threading.Thread(target=_think_runner, daemon=True)
    _THINK_THREAD.start()

def stop_thinking_tips():
    _THINK_STOP.set()
    t = _THINK_THREAD
    if t is not None:
        try: t.join(timeout=0.3)
        except Exception: pass

# ── AUTO-TIPS SLIDESHOW (self-advancing, any key skips) ────────
def show_autotips(slide_delay=4.0):
    """Auto-advancing tips carousel. Any key skips to next slide. Letter 'q' quits."""
    slides = [
        ("Quick Start", [
            "Type anything — sends to AI (no prefix needed)",
            "'hub'    → 18-action control panel",
            "'projects' → your apps at a glance",
            "'x' or Ctrl+C → exit (auto-saves)",
        ]),
        ("Models & Modes", [
            "'model' → pick a specific AI (11 options)",
            "'mode plan' → AI plans first, 'go' to run",
            "'mode auto' → no confirmation prompts",
            "'mode plan' → brainstorm + draft plans (default)   ·   'mode review' → ask before each command",
        ]),
        ("Memory & Context", [
            "'remember: <fact>' → persist across sessions",
            "'memory' → view all stored facts",
            "'forget: <word>' → remove matching facts",
            "'project <path>' → inject file tree to AI",
        ]),
        ("Recovery (if stuck)", [
            "'refresh' → soft-restart engine in place",
            "'kick'    → supervisor-loop hard restart",
            "~/scripts/master_ai_refresh.sh → from any shell",
            "~/scripts/master_ai_kick.sh    → full tmux rebuild",
        ]),
        ("Mobile Tips", [
            "Letter keys (n/b/q) > arrows — RustDesk eats Esc",
            "Drag-select in tmux → copies to phone (needs xclip)",
            "'tts on' → replies spoken aloud",
            "'last' → re-print last AI reply inline",
        ]),
    ]

    import select
    w = 62
    first = True
    for idx, (title, bullets) in enumerate(slides):
        if not first:
            print(f"\n{D}  {'─' * w}  auto-tip  {'─' * 4}{X}\n")
        first = False
        head = f"🥷  TIP {idx+1}/{len(slides)} — {title}"
        pad = max(0, w - len(head))
        print(f"\n{BC}  ╔{'═'*w}╗{X}")
        print(f"{BC}  ║{X}  {BW}{head}{' '*pad}{BC}║{X}")
        print(f"{BC}  ╠{'═'*w}╣{X}")
        for b in bullets:
            print(f"{BC}  ║{X}  {Y}  • {C}{b}{X}")
        print(f"{BC}  ╚{'═'*w}╝{X}")
        dots = "●" * (idx + 1) + "○" * (len(slides) - idx - 1)
        print(f"  {D}── auto-advancing in {int(slide_delay)}s  {BC}{dots}{X}  {D}── press any key to skip  {BC}q{X}=quit{X}")

        # Wait slide_delay seconds, OR until a key is pressed
        if not sys.stdin.isatty():
            time.sleep(slide_delay); continue
        try:
            import termios, tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                r, _, _ = select.select([fd], [], [], slide_delay)
                if r:
                    ch = os.read(fd, 1).decode('utf-8', errors='ignore')
                    if ch in ('q', 'Q', 'x', 'X', '\x03'):
                        print(f"\n  {G}── tips stopped ──{X}")
                        return
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            time.sleep(slide_delay)

    print(f"\n  {G}── end of tips ──  {D}type 'autotips' anytime to replay{X}\n")

# ── HUB MENU (master control panel — numbered actions) ────────
def show_hub():
    """Show the Master AI hub with all features as numbered options.
    Returns the command string selected, or None if user quit."""
    items = [
        # (number shown, command executed, description)
        ("help",         "paginated command reference"),
        ("tips",         "quick-start tips screen"),
        ("tutorial",     "replay feature walkthrough"),
        ("model",        "pick AI model (11 models)"),
        ("mode",         "switch safe / plan / auto"),
        ("memory",       "view / edit facts AI remembers"),
        ("tasks",        "task list"),
        ("chats",        "browse saved sessions"),
        ("save session", "save session + summary now"),
        ("refresh",      "redraw screen + reload engine"),
        ("kick",         "force-restart engine"),
        ("clear cache",  "wipe cached responses"),
        ("keys",         "API key status"),
        ("tts",          "voice toggle / status"),
        ("cache",        "cache stats"),
        ("approved",     "auto-approved commands"),
        ("perms",        "permissions wizard"),
        ("accessibility","input-method settings"),
    ]

    w = 62
    groups = [
        ("COMMUNICATE", [0, 1, 2]),
        ("AI & MODE",   [3, 4, 5]),
        ("WORK",        [6, 7, 8]),
        ("RECOVERY",    [9, 10, 11]),
        ("SYSTEM",      [12, 13, 14, 15, 16, 17]),
    ]
    gidx = 0
    total = len(groups)
    first = True
    while True:
        gname, idxs = groups[gidx]
        title = f"🥷  HUB — {gname}"
        pad = max(0, w - len(title))
        if not first:
            print(f"\n{D}  {'─' * w}  page break  {'─' * 4}{X}\n")
        first = False
        print(f"\n{BC}  ╔{'═'*w}╗{X}")
        print(f"{BC}  ║{X}  {BW}{title}{' '*pad}{BC}║{X}")
        print(f"{BC}  ╠{'═'*w}╣{X}")
        for i in idxs:
            cmd_txt, desc = items[i]
            num = i + 1
            print(f"{BC}  ║{X}   {Y}{num:>2}.{X} {W}{cmd_txt:<18}{X}{C}{desc}{X}")
        print(f"{BC}  ╚{'═'*w}╝{X}")
        dots = "●" * (gidx + 1) + "○" * (total - gidx - 1)
        print(f"  {D}── hub  {BC}{dots}{X}  {D}── {X}{BC}#{X}=pick  {BC}n{X}=next  {BC}b{X}=back  {BC}q{X}=close")

        try:
            ans = read_nav_key(f"🥷 hub > ")
        except KeyboardInterrupt:
            return None

        if ans == "quit":
            return None
        if ans == "prev":
            gidx = max(0, gidx - 1); continue
        if ans == "next" or ans == "":
            if gidx < total - 1:
                gidx += 1; continue
            else:
                print(f"  {G}── end of hub ──{X}")
                return None
        # User typed a number → pick that action
        try:
            n = int(ans) - 1
            if 0 <= n < len(items):
                return items[n][0]
        except ValueError:
            pass
        # Anything else → pass through as a command / question
        return ans

# ── PROJECTS SLIDE SHOW ───────────────────────────────────────
def show_projects():
    """Paginated view of Elijah's shipped projects — one per slide."""
    projects = [
        {
            "name":   "Sunkissed Soul",
            "kind":   "music / spiritual web app",
            "url":    "http://localhost:5173",
            "tailscale": "http://100.101.249.96:5173  (via Tailscale from phone)",
            "launch": "cd ~/sunkissed-soul && npm run dev",
            "status": "dev server (Vite)",
        },
        {
            "name":   "Master AI",
            "kind":   "personal AI terminal + web UI",
            "url":    "http://localhost:8080  (web UI)",
            "tailscale": "http://100.101.249.96:8080/pupil.html  (phone/remote)",
            "launch": "~/scripts/launch_master_ai.sh  (tmux + supervisor loop)",
            "status": "UI + TTS auto-start via systemd user units",
        },
    ]

    w = 62
    idx = 0
    total = len(projects)
    first = True
    while True:
        p = projects[idx]
        title = f"🥷  PROJECT — {p['name']}"
        pad = max(0, w - len(title))
        if not first:
            print(f"\n{D}  {'─' * w}  page break  {'─' * 4}{X}\n")
        first = False
        print(f"\n{BC}  ╔{'═'*w}╗{X}")
        print(f"{BC}  ║{X}  {BW}{title}{' '*pad}{BC}║{X}")
        print(f"{BC}  ╠{'═'*w}╣{X}")
        print(f"{BC}  ║{X}  {Y}  type    {X}{C}{p['kind']}{X}")
        print(f"{BC}  ║{X}  {Y}  local   {X}{C}{p['url']}{X}")
        if p.get("tailscale"):
            print(f"{BC}  ║{X}  {Y}  phone   {X}{G}{p['tailscale']}{X}")
        print(f"{BC}  ║{X}  {Y}  launch  {X}{C}{p['launch']}{X}")
        print(f"{BC}  ║{X}  {Y}  status  {X}{C}{p['status']}{X}")
        print(f"{BC}  ╚{'═'*w}╝{X}")
        dots = "●" * (idx + 1) + "○" * (total - idx - 1)
        print(f"  {D}── project  {BC}{dots}{X}  {D}── {X}{BC}n{X}=next  {BC}b{X}=back  {BC}q{X}=quit")

        try:
            ans = read_nav_key(f"🥷  ")
        except KeyboardInterrupt:
            return None

        if ans == "quit":
            return None
        if ans == "prev":
            idx = max(0, idx - 1); continue
        if ans == "next" or ans == "":
            if idx < total - 1:
                idx += 1; continue
            else:
                print(f"  {G}── end of projects ──{X}")
                return None
        return ans  # user typed a question → caller sends it as a message

# ── HELP CARD (slide show — one section per slide, mobile-friendly) ──
_HELP_HIDDEN_FILE = Path.home() / ".master_ai_help_hidden"


def _load_hidden_help_sections() -> set:
    try:
        return set(
            line.strip().upper()
            for line in _HELP_HIDDEN_FILE.read_text().splitlines()
            if line.strip()
        )
    except Exception:
        return set()


def _save_hidden_help_sections(hidden: set) -> None:
    try:
        _HELP_HIDDEN_FILE.write_text("\n".join(sorted(hidden)))
    except Exception as e:
        log(f"HIDE_HELP_SAVE_ERROR: {e}")


def show_help():
    """Paginated help. Returns None if user quit, or a string if user
    typed a question mid-help (caller should treat it as a new message)."""
    hidden = _load_hidden_help_sections()
    all_sections = [
        ("THE CAST", [
            ("Sensei",               "result-driven. Productive. Sets things in stone."),
            ("",                     "Terminal (tmux). Call Sensei when you need action."),
            ("Pupil",                "inquisitive, eager student. Browser UI (option 5)."),
            ("",                     "Call Pupil when you want to explore before you act."),
            ("Messenger",            "the router. Picks which brain answers the ask."),
            ("",                     "Not a separate UI — lives inside Sensei & Pupil."),
            ("",                     "Future: Scribe · Watcher · Healer"),
        ]),
        ("INPUT", [
            ("v",                    "record voice (5 sec)"),
            ("r <secs>",             "record for N seconds"),
            ("<text> + Enter",       "send message directly — no prefix needed"),
            ("↑ / ↓",               "scroll command history"),
            ("← →  Ctrl+A/E",       "move cursor within line"),
            ("i <path>",             "analyze an image file"),
            ("dl <url>",             "download a file"),
        ]),
        ("AI ROUTING", [
            ("model",                "open model picker — choose any model"),
            ("model auto",           "back to smart auto-routing"),
            ("search <query>",       "force web search, show results"),
            ("mode plan",            "brainstorm + draft plans (default — no execution)"),
            ("mode review",          "ask before every command (per-action confirm)"),
            ("mode plan",            "AI shows plan first — type 'go' to run"),
            ("mode auto",            "commands run without asking"),
            ("go  /  cancel",        "execute or discard a pending plan"),
        ]),
        ("MEMORY & CONTEXT", [
            ("remember: <fact>",     "teach AI a fact (persists across sessions)"),
            ("forget: <word>",       "remove facts matching word"),
            ("memory",               "show all stored facts"),
            ("project <path>",       "set active project — scans files, injects context"),
            ("project",              "show active project"),
        ]),
        ("TASKS", [
            ("task add <text>",      "add a task to your persistent list"),
            ("task list / tasks",    "show all tasks with status"),
            ("task done <n>",        "mark task #n as done"),
            ("task <n>",             "toggle task #n done/undone"),
            ("task clear",           "wipe all tasks"),
        ]),
        ("GIT SHORTCUTS", [
            ("git / git status",     "show status + last 5 commits"),
            ("git diff",             "show diff stat vs HEAD"),
            ("git log",              "last 10 commits"),
            ("git commit <msg>",     "stage all + commit with message"),
            ("git <any>",            "run any git command (with confirm)"),
        ]),
        ("SESSIONS & CACHE", [
            ("save session",         "save full chat + auto-generate summary now"),
            ("load summary",         "inject last session summary into context"),
            ("load session",         "inject full last session transcript"),
            ("clear / clear history","wipe conversation context"),
            ("cache",                "show response cache stats"),
            ("clear cache",          "wipe cached responses"),
            ("approved",             "show auto-approved command list"),
            ("clear approved",       "wipe auto-approved list"),
        ]),
        ("HOW TO SCROLL", [
            ("up",                   "scroll up one page"),
            ("down",                 "scroll down one page"),
            ("top",                  "jump to the beginning"),
            ("bottom",               "jump to latest"),
            ("copy",                 "copy last AI reply to clipboard"),
        ]),
        ("RECOVERY", [
            ("refresh",              "restart engine in-place (screen glitch)"),
            ("kick",                 "force-restart via supervisor (engine stuck)"),
            ("~/scripts/master_ai_kick.sh", "from any shell: rebuild tmux session"),
        ]),
        ("SYSTEM", [
            ("keys",                 "show API key status"),
            ("perms",                "re-run permissions wizard"),
            ("gdrive <query>",       "route query to Google Drive via Claude CLI"),
            ("tts on / tts off",     "toggle voice replies"),
            ("hints on / off",       "toggle contextual tips"),
            ("tutorial",             "replay the feature walkthrough"),
            ("help",                 "show this card"),
            ("help hide <name>",     "hide a slide (e.g. 'help hide SCROLL')"),
            ("help show <name>",     "re-enable a hidden slide"),
            ("help reset",           "show every slide again"),
            ("x",                    "exit Master AI"),
        ]),
    ]

    # Filter out sections the user has hidden via `help hide <name>`
    sections = [s for s in all_sections
                if s[0].upper() not in hidden]
    if not sections:
        print(f"  {Y}(all help sections are hidden — type `help reset` to restore){X}")
        return None

    w = 62
    idx = 0
    total = len(sections)
    first = True
    while True:
        section_name, rows = sections[idx]
        title = f"🥷  MASTER AI — {section_name}"
        pad = max(0, w - len(title))
        if not first:
            print(f"\n{D}  {'─' * w}  page break  {'─' * 4}{X}\n")
        first = False
        print(f"\n{BC}  ╔{'═'*w}╗{X}")
        print(f"{BC}  ║{X}  {BW}{title}{' '*pad}{BC}║{X}")
        print(f"{BC}  ╠{'═'*w}╣{X}")
        for cmd_txt, desc in rows:
            print(f"{BC}  ║{X}  {Y}  {cmd_txt:<28}{C}{desc}{X}")
        print(f"{BC}  ╚{'═'*w}╝{X}")
        dots = "●" * (idx + 1) + "○" * (total - idx - 1)
        print(f"  {D}── help  {BC}{dots}{X}  {D}── {X}{BC}n{X}=next  {BC}b{X}=back  {BC}q{X}=quit  {D}(Enter also = next; type a question to ask){X}")

        try:
            ans = read_nav_key(f"🥷  ")
        except KeyboardInterrupt:
            return None

        if ans == "quit":
            return None
        if ans == "prev":
            idx = max(0, idx - 1)
            continue
        if ans == "next" or ans == "":
            if idx < total - 1:
                idx += 1
            else:
                print(f"  {G}── end of help ──{X}")
                return None
            continue
        # User typed a real question mid-help — exit and route it
        return ans

# ── TIPS SCREEN ───────────────────────────────────────────────
def show_tips():
    os.system("clear")
    cols = shutil.get_terminal_size().columns
    w = min(cols - 4, 72)
    bar = '═' * w

    def row(label, text, lw=26):
        print(f"{BC}  ║{X}  {Y}{label:<{lw}}{X}{C}{text}{X}")

    def section(title):
        print(f"{BC}  ╠{bar}╣{X}")
        print(f"{BC}  ║{X}  {BG}{'  ' + title}{X}")

    def blank():
        print(f"{BC}  ║{X}")

    print(f"\n{BC}  ╔{bar}╗{X}")
    print(f"{BC}  ║{X}  {BW}🥷  MASTER AI — Tips & Tricks{' '*(w-28)}{BC}║{X}")

    section("QUICK INPUT")
    blank()
    row("v",               "voice input — record 5 seconds, then send")
    row("r 10",            "voice input — record for 10 seconds")
    row("i ~/photo.jpg",   "analyze any image file")
    row("dl <url>",        "download a file to ~/Downloads")
    row("search <query>",  "force web search and show raw results")
    blank()

    section("AI MODES")
    blank()
    row("mode plan",       "default — AI drafts plans, you approve to execute")
    row("mode review",     "AI asks before each command (per-action confirm)")
    row("mode plan",       "AI shows a plan first, you type 'go' to run")
    row("mode auto",       "commands run instantly, no prompts (careful!)")
    row("go / cancel",     "execute or discard a pending plan")
    blank()

    section("MODEL ROUTING  (what runs what)")
    blank()
    row("General talk",    "→ qwen2.5:7b (7B local, fast)")
    row("Code / scripts",  "→ qwen2.5-coder:7b (7B local, specialized)")
    row("Complex / analysis","→ qwen3.5:cloud (397B — deep thinking)")
    row("Vision / images", "→ kimi-k2.5:cloud (1T — best vision)")
    row("Reasoning / math","→ DeepSeek R1 (cloud)")
    row("Web / news",      "→ Gemini + DuckDuckGo search")
    row("type 'model'",    "open picker — pin any model manually")
    row("type 'model auto'","restore smart auto-routing")
    blank()

    section("MEMORY")
    blank()
    row("remember: <fact>","saves a fact across all sessions forever")
    row("forget: <word>",  "removes facts that contain that word")
    row("memory",          "show all stored facts (injected into every message)")
    row("load summary",    "inject last session's summary into context")
    row("load session",    "inject full last session transcript")
    blank()

    section("TASKS")
    blank()
    row("task add <text>", "add a task to your persistent list")
    row("tasks",           "show all tasks with done/undone status")
    row("task done 2",     "mark task #2 as done")
    row("task 3",          "toggle task #3 done / undone")
    row("task clear",      "wipe all tasks")
    blank()

    section("GIT SHORTCUTS")
    blank()
    row("git",             "status + last 5 commits")
    row("git log",         "last 10 commits")
    row("git diff",        "diff stat vs HEAD")
    row("git commit <msg>","stage all + commit with message")
    blank()

    section("SESSIONS & CONTEXT")
    blank()
    row("save session",    "save chat + generate 4-bullet summary now")
    row("project ~/path",  "set active project — file tree injected into AI context")
    row("clear history",   "wipe conversation context (keeps memory)")
    row("clear cache",     "wipe cached responses")
    blank()

    section("SYSTEM")
    blank()
    row("refresh",         "restart engine in-place — use when screen glitches")
    row("kick",            "force-restart engine via supervisor loop (use when stuck/hung)")
    row("tts on / tts off","toggle voice — replies spoken aloud (saved across restarts)")
    row("tts",             "show current voice status")
    row("hints on/off",    "toggle contextual tips after commands")
    row("keys",            "show which API keys are loaded")
    row("approved",        "show auto-approved command list")
    row("clear approved",  "wipe approved commands (AI will ask again)")
    row("accessibility",   "toggle no-mouse / phone mode settings")
    row("help",            "full command reference card")
    row("tips",            "this screen")
    row("x",               "exit (saves session automatically)")
    blank()

    section("POWER TIPS")
    blank()
    row("Tab",             "auto-complete any command")
    row("↑ / ↓",          "scroll through command history")
    row("Ctrl+C",          "interrupt + save session")
    row("file mentions",   "AI auto-reads files you name in your message")
    row("RUN: / READ:",    "AI can run commands and read files for you")
    row("chain tasks",     "just describe multi-step work in plain English")
    blank()

    print(f"{BC}  ╚{bar}╝{X}")
    print(f"\n  {D}Press Enter to return...{X}")
    try:
        input()
    except Exception:
        pass

# ── SAFETY BLOCK ─────────────────────────────────────────────
BLOCKED_PATTERNS = [
    "rm -rf /", "rm -rf ~", "rm -rf $HOME",
    "mkfs", "dd if=", ":(){:|:&};:"
]

def is_blocked(cmd):
    return any(b in cmd for b in BLOCKED_PATTERNS)

# ── DESTRUCTIVE HEURISTIC ────────────────────────────────────
# In auto mode the explicit policy is "flow like Claude Code — let it go
# when I'm present, I'll watch" (Elijah, 2026-04-19). Low-risk commands
# auto-run; THESE patterns still pause for the 5-button prompt even in
# auto, because they can delete, force-overwrite, stop services, or
# mass-mutate permissions. Conservative by design: a false positive just
# makes auto mode prompt you once; a false negative means a destructive
# command runs unattended. Bias toward prompt.
_DESTRUCTIVE_PATTERNS = (
    # deletion / shredding
    "shred ", "unlink ", "rmdir ", "trash-put ",
    # git destructive
    "git reset --hard", "git push --force", "git push -f",
    "git clean -f", "git checkout --", "git branch -d", "git branch -D",
    # systemd state changes
    "systemctl stop", "systemctl disable", "systemctl mask",
    "systemctl --user stop", "systemctl --user disable",
    # database
    "drop table", "drop database", "truncate table",
    # mass perm/ownership changes
    "chmod -r", "chmod -rf", "chown -r", "chattr +i",
    # aggressive process kills
    "pkill -9", "killall -9", "kill -kill", "kill -9 -1",
    # filesystem low-level (BLOCKED_PATTERNS catches mkfs+dd, list for completeness)
    "mkswap", "fdisk ", "parted ",
    # package uninstall — banner promises these pause. sudo-apt already
    # hands off, but user-level pip/npm/snap/pipx can uninstall without
    # sudo and would otherwise flow through auto mode silently.
    "pip uninstall", "pip3 uninstall", "pipx uninstall",
    "npm uninstall", "npm rm ", "npm remove",
    "yarn remove", "pnpm remove", "pnpm uninstall",
    "snap remove", "flatpak uninstall", "flatpak remove",
    "apt remove", "apt purge", "apt autoremove",
    "gem uninstall", "cargo uninstall",
    "ollama rm ",  # don't auto-drop a model — user paid time to pull it
    # overwriting redirections against real files (heuristic — `> /tmp/` is fine)
    "> /etc/", "> /usr/", "> /var/", "> /boot/",
)

def _hallucination_warn(cmd):
    """Warn if the first-token binary doesn't exist on PATH.

    Local models sometimes emit commands that don't exist on this OS
    (classic: `ipconfig` on Linux when the user asked for network info,
    or `tailscale config` which isn't a real subcommand). We can't always
    catch subcommand hallucinations (the parent binary DOES exist), but
    we can catch the common case — a fully fabricated top-level command.

    Pure warning, non-blocking. Elijah still owns the decision at the
    5-button confirm prompt. Prints only when we're confident the binary
    is missing — absolute paths, shell builtins, and PATH lookups all
    get a pass.
    """
    import shlex, shutil as _shutil
    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError:
        return  # malformed quoting — skip check
    # Skip env-var assignments (FOO=bar ... cmd)
    i = 0
    while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith(("/", "./", "../")):
        i += 1
    if i >= len(tokens):
        return
    first = tokens[i]
    # Absolute / relative path → let the shell resolve it
    if first.startswith(("/", "./", "../", "~")):
        return
    # Shell builtins and common control words — shutil.which won't find
    # these but they're valid. Subset focused on what models actually emit.
    BUILTINS = {"cd", "echo", "export", "set", "unset", "source", ".", "exec",
                "if", "then", "else", "fi", "for", "while", "do", "done",
                "true", "false", ":", "test", "[", "alias", "eval"}
    if first in BUILTINS:
        return
    if _shutil.which(first):
        return
    print(f"{R}  ⚠ '{first}' not found on PATH — may be a hallucinated command.{X}")
    print(f"  {D}  (on Linux: try `ip addr` instead of `ipconfig`, etc.){X}")

def _is_destructive(cmd):
    """True if `cmd` matches a destructive pattern. Case-insensitive
    substring match against the allow-prompt list. `rm ` gets its own
    word-boundary check so 'firm' / 'alarm' / 'form' don't trigger."""
    low = (cmd or "").lower().strip()
    if not low:
        return False
    # rm specifically — word boundary match
    if low.startswith("rm ") or low.startswith("rm\t") or " rm " in f" {low} ":
        return True
    return any(p in low for p in _DESTRUCTIVE_PATTERNS)

# ── AUTO-MODE SANDBOX ────────────────────────────────────────
# Three real constraints that only apply when MODE == "auto" (safe/plan
# already gate every command behind a manual prompt):
#   1. CWD fence   — EDIT:/CREATE: paths must resolve under an allowlist
#   2. Sudo block  — RUN: commands starting with sudo/su are rejected
#   3. Audit log   — every executed action appended to ~/.master_ai_audit.log
# The point is: auto-mode shouldn't rely on the model's judgment alone.
AUDIT_LOG = Path.home() / ".master_ai_audit.log"

def _audit(kind, detail):
    """Append one line: ISO timestamp · profile · mode · cwd · kind · detail.
    Safe to fail silently — audit is observability, not a blocker."""
    try:
        import os as _os
        line = "\t".join([
            time.strftime("%Y-%m-%dT%H:%M:%S"),
            (_PROFILE_NAME or "default"),
            globals().get("MODE", "?"),
            _os.getcwd(),
            kind,
            (detail or "").replace("\n", " \u21b5 ")[:500],
        ])
        with AUDIT_LOG.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ── SAFE PROMPT ─────────────────────────────────────────────
# Safeguards must never deadlock but must ALSO never answer for the user.
# If the pane has no TTY (e.g. a subprocess called confirm_run), we cannot
# prompt anyone — so refuse the run outright. If a TTY exists, we wait
# forever for the user's answer — that is the intended behavior. Reason:
# 2026-04-19 freeze where input() hung in a stdin-less pane with no way
# out. Claude is NOT permitted to auto-answer; only the user consents.
def _safe_input(prompt, audit_cmd=None):
    """input() with one guardrail: refuse if stdin isn't a TTY.

    Returns None (and audits DENY-NO-TTY) when no live stdin is attached.
    Otherwise behaves exactly like input().strip() — waits for the user
    as long as needed. An absent user is NOT a consenting user, and Claude
    never gets to answer on their behalf."""
    if not sys.stdin.isatty():
        if audit_cmd is not None:
            _audit("DENY-NO-TTY", audit_cmd)
        return None
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        if audit_cmd is not None:
            _audit("DENY-EOF", audit_cmd)
        return None

def _is_sudo_cmd(cmd):
    """Cheap detector — does this command invoke privilege escalation?
    Used in auto mode to force a manual accept-every-time flow and to
    defer password-required commands to the user's own terminal."""
    c = (cmd or "").lstrip()
    # Strip leading env-var assignments like FOO=bar sudo ...
    while c and "=" in c.split(None, 1)[0] and not c.startswith(("sudo", "su ")):
        parts = c.split(None, 1)
        if len(parts) < 2:
            break
        c = parts[1].lstrip()
    return (c.startswith("sudo ") or c.startswith("sudo\t") or
            c.startswith("su ") or c.startswith("su\t") or
            c == "sudo" or c == "su")

def _sudo_handoff(cmd):
    """sudo commands NEVER run inside Sensei. Password prompts must happen
    in a separate terminal that the user controls end-to-end. This is a
    hard product rule — see `feedback_passwords_other_terminal.md`.

    Sensei's job here: print the command clearly, confirm the rule out
    loud, wait for the user to acknowledge, then move on without running.
    Accept-every-time — Sensei asks again on the NEXT sudo line."""
    print(f"\n{Y}  🔒  sudo command — NOT running here. Run it in a SEPARATE terminal.{X}")
    print(f"  {BOLD}{cmd}{X}")
    print(f"  {D}──────────────────────────────────────────────────────────{X}")
    print(f"  {D}Why: any password you type MUST NEVER pass through Sensei.{X}")
    print(f"  {D}  Open another terminal window. Paste the command above. Type{X}")
    print(f"  {D}  your password there. Come back here when it's done.{X}")
    print(f"  {D}──────────────────────────────────────────────────────────{X}")
    _audit("RUN-SUDO-HANDOFF", cmd)
    try:
        input(f"  {C}[press Enter when you've handled it — or just to skip]{X} ")
    except Exception:
        pass
    return None

def _cwd_fence_ok(filepath):
    """Return (ok, reason) — is this path under a writable allowlist?
    Only enforced when MODE == 'auto'. Safe/plan ask the user explicitly."""
    if globals().get("MODE", "plan") != "auto":
        return (True, "")
    import os as _os
    try:
        abspath = _os.path.realpath(_os.path.expanduser(filepath))
    except Exception:
        return (False, "could not resolve path")

    home = _os.path.expanduser("~")
    cwd  = _os.path.realpath(_os.getcwd())
    # Allowlist: CWD, /tmp, home's Desktop, home's scripts (project root),
    # home's Downloads, home's .master_ai_* (profile data)
    allowed = [
        cwd,
        "/tmp",
        "/var/tmp",
        _os.path.join(home, "Desktop"),
        _os.path.join(home, "scripts"),
        _os.path.join(home, "Downloads"),
        _os.path.join(home, ".master_ai_chats"),
        _os.path.join(home, ".master_ai_profiles"),
        _os.path.join(home, "off_grid_kit"),
    ]
    for root in allowed:
        try:
            if abspath == root or abspath.startswith(root + _os.sep):
                return (True, "")
        except Exception:
            continue
    # Denylist for clarity in the rejection message
    for bad in ("/etc", "/boot", "/root", "/usr", "/sys", "/proc", "/dev", "/var/log"):
        if abspath.startswith(bad + _os.sep) or abspath == bad:
            return (False, f"auto-mode refuses writes under {bad}")
    return (False, f"auto-mode refuses writes outside CWD/Desktop/scripts/tmp (got {abspath})")

# ── ACTION PILLS ─────────────────────────────────────────────
# Visual color-badges for action outcomes — matches Claude Code's
# per-action status pills. Each kind renders as a short colored
# chiclet that scans at a glance: green for success, red for
# failure/blocked, yellow for skipped/warned.
def _pill(kind, detail=""):
    """Return a colored pill badge + optional trailing detail."""
    badges = {
        "RAN":     f"{BTN_G} RAN     {X}",
        "CREATED": f"{BTN_G} CREATED {X}",
        "EDITED":  f"{BTN_G} EDITED  {X}",
        "BLOCKED": f"{BTN_R} BLOCKED {X}",
        "SKIPPED": f"{BTN_Y} SKIPPED {X}",
        "ERROR":   f"{BTN_R} ERROR   {X}",
        "WARN":    f"{BTN_Y} WARN    {X}",
    }
    tag = badges.get(kind, f"[{kind}]")
    return f"  {tag}  {detail}" if detail else f"  {tag}"

# ── RUN COMMAND ───────────────────────────────────────────────
def run_command(cmd):
    print(f"\n🥷  {BOLD}Running:{X} {Y}{cmd}{X}")
    try:
        # 300s (5 min) covers git clone, npm install, apt update, slow curls —
        # the 30s cap was killing legitimate long-running utility commands.
        # Anything truly interactive/visual belongs on RUNTERM: (new terminal).
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        output = (result.stdout + result.stderr).strip()
        if output:
            print(f"{G}{output}{X}")
        if result.returncode == 0:
            print(_pill("RAN", f"{D}{cmd[:70]}{X}"))
        else:
            print(_pill("ERROR", f"{D}exit {result.returncode} · {cmd[:60]}{X}"))
        log(f"PC_CMD: {cmd}")
        return output
    except subprocess.TimeoutExpired:
        print(_pill("ERROR", f"{D}timeout (5 min) · {cmd[:60]}{X}"))
        return "timeout"
    except Exception as e:
        print(_pill("ERROR", f"{D}{e}{X}"))
        return str(e)

def run_in_terminal(cmd):
    """Spawn cmd in a fresh graphical terminal window. Fire-and-forget —
    we do NOT wait, do NOT capture output, do NOT impose a timeout.
    For visual / interactive scripts (matrix-rain, htop, vim, curses apps)
    that need a real TTY. Keeps the terminal open after exit with a
    'press Enter to close' so brief output doesn't vanish.
    Fallback chain: x-terminal-emulator (Debian alt) → gnome-terminal → xterm.
    Returns a status string; the actual run happens in the spawned window."""
    print(f"\n🥷  {BOLD}Spawning in new terminal:{X} {Y}{cmd}{X}")
    wrapped = f"{cmd}; echo; read -p 'Press Enter to close...'"
    candidates = [
        ["x-terminal-emulator", "-e", "bash", "-c", wrapped],
        ["gnome-terminal", "--", "bash", "-c", wrapped],
        ["xterm", "-e", f"bash -c \"{wrapped}\""],
    ]
    for argv in candidates:
        try:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True)
            print(_pill("SPAWNED", f"{D}{argv[0]} · {cmd[:50]}{X}"))
            log(f"PC_RUNTERM: {cmd} via {argv[0]}")
            return f"[spawned in {argv[0]}]"
        except FileNotFoundError:
            continue
        except Exception as e:
            log(f"RUNTERM_ERROR ({argv[0]}): {e}")
            continue
    print(_pill("ERROR", f"{D}no graphical terminal available (tried x-terminal-emulator, gnome-terminal, xterm){X}"))
    return "no-terminal-available"

# ── KICK ESCAPE FROM CONFIRM PROMPTS ─────────────────────────
# Born from the 2026-04-21 clarify-prompt trap: typing 'kick' at a
# Choose (1/2/3) prompt was being SKIPPED, then the input got routed
# as a fresh chat turn instead of restarting the engine. This helper
# is called from every confirm prompt so 'kick' always escapes cleanly.
def _check_kick_escape(choice):
    lo = (choice or "").strip().lower()
    if lo in ("kick", "force restart", "hard restart"):
        print(f"\n  {R}💥 kick at confirm prompt — restarting engine in 3s...{X}", flush=True)
        sys.exit(42)

# ── 4-OPTION CONFIRM ─────────────────────────────────────────
@_awaiting_confirm
def confirm_run(cmd):
    if is_blocked(cmd):
        print(_pill("BLOCKED", f"{D}dangerous command refused: {cmd[:60]}{X}"))
        log(f"BLOCKED: {cmd}")
        _audit("RUN-BLOCK", cmd)
        return None

    # Sudo handoff — accept-every-time, never auto-run, never auto-approve.
    # In every mode (safe/plan/auto), sudo pauses and hands the command to
    # the user so they can paste it into their own terminal for the
    # password prompt. Sensei never stores sudo in the approved list.
    if _is_sudo_cmd(cmd):
        return _sudo_handoff(cmd)

    # Hallucination guard — the local model sometimes emits binaries that
    # don't exist on this OS (e.g. `ipconfig` on Linux, `tailscale config`
    # which is not a real subcommand). Check the first real token against
    # PATH before running. Pure warning — doesn't block, but gives Elijah
    # a chance to cancel before a 127 / unknown-subcommand error.
    _hallucination_warn(cmd)

    if cmd in load_approved():
        print(f"{C}  ⚡ Auto-approved: {Y}{cmd}{X}")
        _audit("RUN", cmd)
        return run_command(cmd)

    # Auto-mode flow — Elijah's explicit policy is "let it go when I'm
    # present, I'll watch" (2026-04-19). In auto mode, anything that
    # isn't destructive runs without the 5-button prompt. Destructive
    # commands (rm, git reset --hard, systemctl stop, drop table, etc.)
    # still pause for approval because those are the ones a watching
    # user would want to catch before they fire. Sudo already handed
    # off above; blocked already refused above.
    if globals().get("MODE", "plan") == "auto" and not _is_destructive(cmd):
        print(f"{C}  ⚡ auto-flow: {Y}{cmd}{X}")
        _audit("RUN-AUTO", cmd)
        return run_command(cmd)

    # Review-mode context block: who proposed this + where it'll run.
    # Shown only in Review (not Auto, not Plan) so the extra lines don't
    # clutter auto-flow output. "why" is omitted until .sensei_behavior.md
    # gets a rule that requires the model to emit a WHY: rationale line.
    if globals().get("MODE", "plan") == "review":
        _who_route = globals().get('LAST_ROUTE') or 'local'
        _who_model = globals().get('LAST_MODEL') or ''
        _who = f"{_who_route}{' · ' + _who_model if _who_model else ''}"
        _where = os.getcwd()
        print(f"\n  {C}who:{X}   {_who}")
        print(f"  {C}what:{X}  {Y}{cmd}{X}")
        print(f"  {C}where:{X} {_where}")
    print(f"\n{D}╔══════════════════════════════════════════════════════╗{X}")
    print(f"{D}║  🥷 {BOLD}AI wants to run:{X}")
    print(f"{D}║  {Y}  {cmd}{X}")
    print(f"{D}╠══════════════════════════════════════════════════════╣{X}")
    print(f"{D}║  {BTN_G} 1) Yes     — run once                      {X}")
    print(f"{D}║  {BTN_C} 2) Always  — never ask again              {X}")
    print(f"{D}║  {BTN_R} 3) No      — skip                          {X}")
    print(f"{D}║  {BTN_Y} 4) Edit    — tweak the shell command      {X}")
    print(f"{D}║  {BTN_C} 5) Ask     — send new instructions to AI  {X}")
    print(f"{D}╚══════════════════════════════════════════════════════╝{X}")
    # Safeguard: if this pane has no live TTY, refuse rather than deadlock.
    # See feedback_safeguards_never_deadlock.md — born from the 2026-04-19
    # freeze. We do NOT timeout-to-No: if the user IS present, the prompt
    # waits as long as it takes. Only a stdin-less caller is refused.
    choice = _safe_input(f"  {BOLD}Choose (1/2/3/4/5): {X}", audit_cmd=cmd)
    if choice is None:
        print(f"{R}  🚫 no live terminal — refusing this run. Re-issue from an interactive Sensei pane.{X}")
        return None
    _check_kick_escape(choice)

    if choice == '1':
        _audit("RUN", cmd)
        return run_command(cmd)
    elif choice == '2':
        save_approved(cmd)
        print(f"{G}  ✅ Added to approved list.{X}")
        _audit("RUN-ALWAYS", cmd)
        return run_command(cmd)
    elif choice == '4':
        try:
            edited = input(f"{C}  Edit command (shell): {X}").strip() or cmd
        except Exception:
            edited = cmd
        # Heuristic: if the edit clearly isn't a shell command (spaces + no
        # leading bin/flag + mostly alpha), reroute to option 5 behavior so
        # "save as project" doesn't get `exec`'d as a binary.
        if _looks_like_english(edited):
            print(f"{Y}  That looks like an instruction, not a shell command — sending it back to the AI instead.{X}")
            globals()['PENDING_USER_NOTE'] = edited
            return None
        if is_blocked(edited):
            print(f"{R}  🚫 BLOCKED.{X}")
            return None
        return run_command(edited)
    elif choice == '5':
        try:
            note = input(f"{C}  Tell the AI what to do instead: {X}").strip()
        except Exception:
            note = ""
        if note:
            globals()['PENDING_USER_NOTE'] = note
            print(f"{C}  → will send to AI on next turn.{X}")
        else:
            print(f"{Y}  ⏭  Skipped.{X}")
        return None
    else:
        print(f"{Y}  ⏭  Skipped.{X}")
        return None


@_awaiting_confirm
def confirm_runterm(cmd):
    """Confirm + spawn in a fresh graphical terminal. Same safety gates as
    confirm_run (block list + sudo handoff), but skips hallucination_warn
    (user/model explicitly signaled this is interactive/visual — they know
    what the script is). Auto mode spawns directly; Plan/Review prompts."""
    if is_blocked(cmd):
        print(_pill("BLOCKED", f"{D}dangerous command refused: {cmd[:60]}{X}"))
        log(f"BLOCKED-TERM: {cmd}")
        _audit("RUNTERM-BLOCK", cmd)
        return None

    if _is_sudo_cmd(cmd):
        return _sudo_handoff(cmd)

    if cmd in load_approved():
        print(f"{C}  ⚡ Auto-approved: {Y}{cmd}{X}")
        _audit("RUNTERM", cmd)
        return run_in_terminal(cmd)

    if globals().get("MODE", "plan") == "auto":
        print(f"{C}  ⚡ auto-flow (new terminal): {Y}{cmd}{X}")
        _audit("RUNTERM-AUTO", cmd)
        return run_in_terminal(cmd)

    print(f"\n{D}╔══════════════════════════════════════════════════════╗{X}")
    print(f"{D}║  🥷 {BOLD}AI wants to run in a NEW terminal:{X}")
    print(f"{D}║  {Y}  {cmd}{X}")
    print(f"{D}╠══════════════════════════════════════════════════════╣{X}")
    print(f"{D}║  {BTN_G} 1) Yes     — spawn in new terminal       {X}")
    print(f"{D}║  {BTN_R} 3) No      — skip                          {X}")
    print(f"{D}╚══════════════════════════════════════════════════════╝{X}")
    choice = _safe_input(f"  {BOLD}Choose (1/3): {X}", audit_cmd=cmd)
    if choice is None:
        print(f"{R}  🚫 no live terminal — refusing this run.{X}")
        return None
    _check_kick_escape(choice)
    if choice == '1':
        _audit("RUNTERM", cmd)
        return run_in_terminal(cmd)
    print(f"{Y}  ⏭  Skipped.{X}")
    return None


def _looks_like_english(s: str) -> bool:
    """True if `s` looks like a natural-language instruction rather than a
    shell command. Heuristic only — users can force-run via plain `edit`
    and a proper command string."""
    s = (s or "").strip()
    if not s or len(s.split()) < 2:
        return False
    # A shell command usually has a recognizable first token (binary, path,
    # sudo, env var, pipe, redirect). English sentences tend to be all-alpha
    # words with no slashes/dashes on the first token.
    first = s.split()[0]
    if any(c in first for c in "/-=\"'|&><$"):
        return False
    if first in ("sudo", "bash", "sh", "python3", "python", "git", "npm",
                 "pip", "curl", "wget", "ls", "cd", "cat", "echo", "mkdir",
                 "rm", "cp", "mv", "chmod", "chown", "ssh", "rsync",
                 "tmux", "systemctl", "apt", "snap"):
        return False
    # If all tokens are plain alpha words → probably a sentence.
    tokens = s.split()
    alpha_tokens = sum(1 for t in tokens if t.replace("'", "").isalpha())
    return alpha_tokens >= max(2, len(tokens) - 1)

# ── FILE CREATE CONFIRM ───────────────────────────────────────
@_awaiting_confirm
def confirm_create(filepath, content):
    filepath = os.path.expanduser(filepath)
    # Auto-mode CWD fence
    ok, why = _cwd_fence_ok(filepath)
    if not ok:
        print(f"{R}  🚫 AUTO-MODE SANDBOX — refused CREATE:{X}")
        print(f"  {filepath}")
        print(f"  {D}reason: {why}{X}")
        print(f"  {D}switch to 'mode review' to confirm manually.{X}")
        _audit("CREATE-FENCE-BLOCK", filepath)
        return
    line_count = content.count('\n') + 1
    lines = content.splitlines()
    # Diff-style preview — green `+` prefix with line numbers, same shape as
    # confirm_edit. Elijah 2026-04-21: "I see the green plus … I would love
    # to see that [for creates too]." Shows up to 30 lines inline; larger
    # files keep option 2 to see the rest.
    preview_n = 30
    print(f"\n{D}╔══════════════════════════════════════════════════════╗{X}")
    print(f"{D}║  🥷 {BOLD}AI wants to create:{X} {Y}{os.path.basename(filepath)}{X}  "
          f"{D}({line_count} line{'s' if line_count != 1 else ''}){X}")
    print(f"{D}║  {D}{filepath}{X}")
    print(f"{D}╠══════════════════════════════════════════════════════╣{X}")
    for i, line in enumerate(lines[:preview_n]):
        print(f"{D}║  {G}+{i + 1:>4}: {line}{X}")
    if line_count > preview_n:
        remaining = line_count - preview_n
        print(f"{D}║  {D}  … {remaining} more line{'s' if remaining != 1 else ''} "
              f"— press 2 to see all{X}")
    print(f"{D}╠══════════════════════════════════════════════════════╣{X}")
    print(f"{D}║  {BTN_G} 1) Create   — write file         {X}")
    if line_count > preview_n:
        print(f"{D}║  {BTN_C} 2) Review   — see all {line_count} lines   {X}")
    print(f"{D}║  {BTN_R} 3) No       — skip               {X}")
    print(f"{D}╚══════════════════════════════════════════════════════╝{X}")
    choice = input(f"  {BOLD}Choose (1/2/3): {X}").strip()
    _check_kick_escape(choice)

    if choice in ('1', '2'):
        if choice == '2':
            lines = content.splitlines()
            print(f"\n{D}  ── File Preview ──────────────────────────────────{X}")
            for line in lines[:50]:
                print(f"  {line}")
            if len(lines) > 50:
                print(f"{C}  ... (truncated at 50 lines){X}")
            print(f"{D}  ─────────────────────────────────────────────────{X}")
            if input(f"{C}  Create this file? (y/N): {X}").strip().lower() != 'y':
                print(f"{Y}  ⏭  Skipped.{X}")
                return
        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            Path(filepath).write_text(content)
            # Auto-chmod +x when the file starts with a shebang — otherwise
            # the model's follow-up `RUN: ./script.sh` fails with exit 126
            # (Permission denied). Only fires on shebanged files so we don't
            # make arbitrary data files executable.
            if content.startswith("#!"):
                try:
                    st = os.stat(filepath)
                    os.chmod(filepath, st.st_mode | 0o111)
                except Exception:
                    pass
            print(_pill("CREATED", f"{W}{filepath}{X}"))
            log(f"PC_CREATE: {filepath}")
            _audit("CREATE", filepath)
        except Exception as e:
            print(_pill("ERROR", f"create failed: {e}"))
    else:
        print(_pill("SKIPPED"))

# ── FILE EDIT CONFIRM ────────────────────────────────────────
@_awaiting_confirm
def confirm_edit(filepath, find_text, replace_text):
    filepath = os.path.expanduser(filepath)
    ok, why = _cwd_fence_ok(filepath)
    if not ok:
        print(f"{R}  🚫 AUTO-MODE SANDBOX — refused EDIT:{X}")
        print(f"  {filepath}")
        print(f"  {D}reason: {why}{X}")
        print(f"  {D}switch to 'mode review' to confirm manually.{X}")
        _audit("EDIT-FENCE-BLOCK", filepath)
        return
    if not os.path.isfile(filepath):
        print(f"{R}  ❌ EDIT: file not found: {filepath}{X}")
        return
    try:
        content = Path(filepath).read_text(errors='replace')
    except Exception as e:
        print(f"{R}  ❌ EDIT: read failed: {e}{X}")
        return
    if find_text not in content:
        print(f"{R}  ❌ EDIT: text not found in {os.path.basename(filepath)}{X}")
        print(f"{D}  looking for: {find_text[:80]!r}{X}")
        return

    # Full diff — no 120-char truncation. Line numbers prefixed so Elijah
    # can locate the change. The starting line is derived from the byte
    # offset of find_text within the file, converted to a line number.
    start_byte = content.find(find_text)
    start_line = content[:start_byte].count("\n") + 1 if start_byte >= 0 else 0
    old_lines = find_text.rstrip("\n").split("\n")
    new_lines = replace_text.rstrip("\n").split("\n")
    print(f"\n{D}╔══════════════════════════════════════════════════════╗{X}")
    print(f"{D}║  🥷 {BOLD}AI wants to edit:{X} {Y}{os.path.basename(filepath)}{X}  "
          f"{D}(line {start_line}){X}")
    print(f"{D}╠══════════════════════════════════════════════════════╣{X}")
    for i, line in enumerate(old_lines):
        print(f"{D}║  {R}-{start_line + i:>4}: {line}{X}")
    for i, line in enumerate(new_lines):
        print(f"{D}║  {G}+{start_line + i:>4}: {line}{X}")
    print(f"{D}╠══════════════════════════════════════════════════════╣{X}")
    print(f"{D}║  {BTN_G} 1) Apply     — make the edit          {X}")
    print(f"{D}║  {BTN_R} 2) No        — skip                   {X}")
    print(f"{D}╚══════════════════════════════════════════════════════╝{X}")
    choice = input(f"  {BOLD}Choose (1/2): {X}").strip()
    _check_kick_escape(choice)
    if choice == '1':
        new_content = content.replace(find_text, replace_text, 1)
        try:
            Path(filepath).write_text(new_content)
            print(_pill("EDITED", f"{W}{filepath}{X}  {D}(line {start_line}){X}"))
            log(f"PC_EDIT: {filepath}")
            _audit("EDIT", filepath)
        except Exception as e:
            print(_pill("ERROR", f"edit failed: {e}"))
    else:
        print(_pill("SKIPPED"))

# ── REPLY PROCESSOR ──────────────────────────────────────────
def process_reply(reply, history, streamed=False):
    """Parse RUN: / READ: / CREATE: directives from AI reply and execute."""
    lines = reply.splitlines()

    # Strip surrounding backticks/quotes from extracted commands — local
    # models sometimes wrap commands in `backticks` or 'quotes'. Shell
    # would mis-interpret those (backticks trigger command substitution).
    def _strip_command_wrap(s):
        s = s.strip()
        for pair in (("`", "`"), ("'", "'"), ('"', '"'), ("“", "”"), ("‘", "’")):
            if s.startswith(pair[0]) and s.endswith(pair[1]) and len(s) >= 2:
                s = s[1:-1].strip()
                break
        return s

    # Use re.search with a word boundary — catches "RUN:" anywhere on the
    # line, not just at the start. This handles the 2026-04-20 case where
    # the local model echoed "PLAN ONLY: RUN: cmd" and the prior `re.match`
    # at start-of-line missed it entirely, leaving the command un-parsed.
    # \bRUN: deliberately does NOT match RUNTERM: — "RUN" is followed by "T"
    # in "RUNTERM:", not ":", so the regex skips it. RUNTERM: has its own
    # extraction below.
    read_paths   = [_strip_command_wrap(l.split('READ:', 1)[1])
                    for l in lines if re.search(r'\bREAD:', l, re.IGNORECASE)]
    run_cmds     = [_strip_command_wrap(l.split('RUN:', 1)[1])
                    for l in lines if re.search(r'\bRUN:', l, re.IGNORECASE)]
    runterm_cmds = [_strip_command_wrap(re.split(r'RUNTERM:', l, maxsplit=1, flags=re.IGNORECASE)[1])
                    for l in lines if re.search(r'\bRUNTERM:', l, re.IGNORECASE)]

    # Parse CREATE: ... <<<CONTENT ... >>>CONTENT blocks
    create_files = []
    # Parse EDIT: ... <<<FIND ... >>>FIND <<<REPLACE ... >>>REPLACE blocks
    edit_ops = []
    in_block, cur_path, cur_content = False, None, []
    cur_find, cur_replace, in_find, in_replace = None, None, False, False
    for line in lines:
        if re.match(r'^\s*CREATE:', line, re.IGNORECASE):
            cur_path = os.path.expanduser(
                re.split(r'CREATE:', line, maxsplit=1, flags=re.IGNORECASE)[1].strip())
            cur_content = []
            in_block = False
        elif line.strip() == '<<<CONTENT' and cur_path:
            in_block = True
        elif line.strip() == '>>>CONTENT' and in_block:
            in_block = False
            create_files.append((cur_path, '\n'.join(cur_content)))
            cur_path = None
        elif in_block:
            cur_content.append(line)
        elif re.match(r'^\s*EDIT:', line, re.IGNORECASE):
            cur_path = os.path.expanduser(
                re.split(r'EDIT:', line, maxsplit=1, flags=re.IGNORECASE)[1].strip())
            cur_find = []; cur_replace = []; in_find = False; in_replace = False
        elif line.strip().upper() == '<<<FIND' and cur_path:
            in_find = True
        elif line.strip().upper() == '>>>FIND' and in_find:
            in_find = False
        elif line.strip().upper() == '<<<REPLACE' and cur_path:
            in_replace = True
        elif line.strip().upper() == '>>>REPLACE' and in_replace:
            in_replace = False
            if cur_find is not None and cur_replace is not None:
                edit_ops.append((cur_path, '\n'.join(cur_find), '\n'.join(cur_replace)))
            cur_path = None; cur_find = None; cur_replace = None
        elif in_find and cur_find is not None:
            cur_find.append(line)
        elif in_replace and cur_replace is not None:
            cur_replace.append(line)

    has_directives = bool(read_paths or run_cmds or runterm_cmds or create_files or edit_ops)

    # Print non-directive narrative text
    skip_prefixes = ('run:', 'runterm:', 'read:', 'create:', 'edit:', '<<<content', '>>>content',
                     '<<<find', '>>>find', '<<<replace', '>>>replace')
    narrative = '\n'.join(
        l for l in lines
        if not any(l.strip().lower().startswith(p) for p in skip_prefixes)
    ).strip()

    if narrative and not streamed:
        render_reply(narrative, prefix=f"\n{M}  🥋{X} ", suffix="")
    elif not has_directives and not streamed:
        render_reply(reply, prefix=f"\n{M}  🥋{X} ", suffix="")

    # READ: — inject file content and signal caller to re-ask
    if read_paths:
        injected_block = []
        for rpath in read_paths:
            exp = os.path.expanduser(rpath)
            if os.path.isfile(exp):
                content = Path(exp).read_text(errors='replace')[:8000]
                injected_block.append(f"--- {exp} ---\n{content}")
                print(f"{C}  📄 Read: {Y}{exp}{C} ({len(content)} chars){X}")
            elif os.path.isdir(exp):
                listing = subprocess.run(['ls', '-la', exp],
                                         capture_output=True, text=True).stdout
                injected_block.append(f"--- {exp} (directory) ---\n{listing}")
                print(f"{C}  📁 Dir: {Y}{exp}{X}")
            else:
                print(f"{R}  ❌ READ: not found: {exp}{X}")
        if injected_block:
            history.append({
                "role": "user",
                "content": "[File contents]\n" + '\n\n'.join(injected_block) + "\n\nNow proceed."
            })
            return None  # caller re-asks AI with injected context

    # CREATE: / EDIT: run BEFORE RUN: — so RUN: bash <path> works on a file
    # the same reply just created. Prior order produced exit-127s when the
    # model emitted CREATE: + RUN: together.
    for filepath, content in create_files:
        confirm_create(filepath, content)

    for filepath, find_text, replace_text in edit_ops:
        confirm_edit(filepath, find_text, replace_text)

    for cmd in run_cmds:
        confirm_run(cmd)

    # RUNTERM: runs after RUN: — if the model pairs "build output" (RUN:) with
    # "now open the demo" (RUNTERM:), the demo spawns after the build finishes.
    for cmd in runterm_cmds:
        confirm_runterm(cmd)

    return reply

# ── PERMISSIONS WIZARD ────────────────────────────────────────
def permissions_wizard():
    PERMISSIONS = [
        ("Shell Command Execution",
         "The AI translates your requests into bash commands and runs them on this machine.",
         True),
        ("File: Memory Store  (~/.master_ai_memory)",
         "Reads and writes facts you teach the AI so it remembers them across sessions.",
         True),
        ("File: Approved Commands  (~/.master_ai_approved)",
         "Saves commands marked always-approved so it never prompts for them again.",
         True),
        ("Network: Ollama API  (localhost:11434)",
         "Sends your prompts to the local Ollama model to generate AI responses.",
         True),
        ("Network: Cloud AI  (Groq / OpenAI / OpenRouter)",
         "Routes complex queries to cloud models when local AI is insufficient.",
         False),
        ("Web Search  (DuckDuckGo)",
         "Searches the web and injects results into AI context for current information.",
         False),
        ("TTS Server  (localhost:5050)",
         "Forwards AI replies to the TTS server so responses can be spoken aloud.",
         False),
        ("File: Session Log  (~/scripts/master.log)",
         "Records every command and AI response to a local file for your review.",
         False),
    ]

    print(f"\n{D}  ┌─────────────────────────────────────────────────────────┐{X}")
    print(f"{D}  │{X}  {C}🔐  Permissions Walkthrough{X}")
    print(f"{D}  │{X}  {C}Review each permission before Master AI starts.{X}")
    print(f"{D}  └─────────────────────────────────────────────────────────┘{X}\n")
    time.sleep(0.4)

    total = len(PERMISSIONS)
    grant_all = False
    denied_required = 0

    for i, (name, why, required) in enumerate(PERMISSIONS):
        req_label = f"{R}[required]{X}" if required else f"{C}[optional]{X}"

        print(f"\n{D}  ────────────────────────────────────────────────────────────{X}")
        print(f"  {BOLD}Permission {i + 1} of {total}   {req_label}{X}")
        print(f"\n  {BOLD}{name}{X}")
        print(f"\n  {BOLD}Why:{X} {why}")
        print(f"\n{D}  ────────────────────────────────────────────────────────────{X}\n")

        if grant_all:
            print(f"  {G}✅ Granted (Yes to All){X}")
            time.sleep(0.25)
            continue

        print(f"  {BTN_G} 1) Yes          — grant this permission {X}")
        print(f"  {BTN_C} 2) Yes to All   — grant this and all remaining {X}")
        print(f"  {BTN_R} 3) No           — deny this permission {X}\n")

        choice = input(f"  {BOLD}Choose (1/2/3): {X}").strip()
        _check_kick_escape(choice)

        if choice == '2':
            grant_all = True
            print(f"\n  {G}✅ Granted — all remaining permissions also granted.{X}")
        elif choice == '3':
            if required:
                print(f"\n  {R}⚠  This permission is required. Some features may not work.{X}")
                denied_required += 1
            else:
                print(f"\n  {Y}⏭  Skipped — optional feature disabled.{X}")
        else:
            print(f"\n  {G}✅ Granted.{X}")

    print(f"\n{D}  ────────────────────────────────────────────────────────────{X}")
    print(f"  {C}Permission Review Complete{X}\n")

    if denied_required > 0:
        print(f"  {R}⚠  {denied_required} required permission(s) denied.{X}")
        print(f"  {Y}  Some features may not function correctly.{X}\n")
        if input(f"  {Y}Continue anyway? (y/N): {X}").strip().lower() != 'y':
            print(f"{R}  Exiting.{X}")
            sys.exit(0)
    else:
        print(f"  {G}✅ All permissions granted.{X}")
        time.sleep(0.6)
    print()

# ── STARTUP CHECK ─────────────────────────────────────────────
def startup_check():
    errors = 0
    print(f"\n{D}  ┌─────────────────────────────────────────────┐{X}")
    print(f"{D}  │{X}  {C}⚙  System Check{X}")
    print(f"{D}  └─────────────────────────────────────────────┘{X}\n")

    # Ollama — retry to survive boot race against ollama.service
    ollama_ok = False
    for attempt in range(3):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(f"{OLLAMA_URL}/api/tags"), timeout=3):
                ollama_ok = True
                break
        except KeyboardInterrupt:
            break
        except Exception:
            if attempt < 2:
                time.sleep(1)
    if ollama_ok:
        print(f"  {G}✅ Ollama       {C}running at {OLLAMA_URL}{X}")
    else:
        print(f"  {R}❌ Ollama       {C}not running — start with: ollama serve{X}")
        errors += 1

    # Memory / Approved counts
    def _count(f):
        try:
            return len([l for l in f.read_text().splitlines() if l.strip()])
        except Exception:
            return 0
    print(f"  {G}✅ Memory       {C}{_count(MEMORY_FILE)} facts | "
          f"{_count(APPROVED_FILE)} auto-approved commands{X}")

    # Cloud keys
    if any(KEYS.get(k) for k in ['anthropic', 'deepseek', 'gemini', 'groq', 'openai', 'openrouter']):
        print(f"  {G}✅ Cloud AI     {C}keys loaded (Groq / OpenAI / OpenRouter){X}")
    else:
        print(f"  {Y}⚠  Cloud AI     {C}no keys found — local Ollama only{X}")

    # Web search
    try:
        import importlib
        importlib.import_module('duckduckgo_search')
        print(f"  {G}✅ Web search   {C}duckduckgo_search available{X}")
    except ImportError:
        print(f"  {Y}⚠  Web search   {C}pip install duckduckgo-search to enable{X}")

    print()
    if errors > 0:
        print(f"  {R}⚠  Fix the issues above before using Master AI.{X}")
        if input(f"  {Y}  Continue anyway? (y/N): {X}").strip().lower() != 'y':
            print(f"{R}  Exiting.{X}")
            sys.exit(0)
    else:
        print(f"  {G}  All systems ready.{X}")
        time.sleep(0.6)
    print()

# ── STATUS BAR ───────────────────────────────────────────────
def draw_status_bar():
    """Active status — bold blue, right-aligned at TOP RIGHT. No bg color.
    Shows only what's currently ON/active (modes, TTS, memory, tasks, model).
    """
    def _count(f):
        try:
            return len([l for l in f.read_text().splitlines() if l.strip()])
        except Exception:
            return 0
    mem = _count(MEMORY_FILE)
    tasks = active_task_count()
    has_cloud = any(KEYS.get(k) for k in ['anthropic', 'deepseek', 'gemini', 'groq', 'openai', 'openrouter'])
    model_label = PINNED_MODEL if PINNED_MODEL else ("AUTO+CLOUD" if has_cloud else "AUTO")
    tts_on = os.path.exists(Path.home() / ".master_ai_tts_on")

    parts = [f"MODE:{MODE.upper()}"]
    if tts_on:
        parts.append("TTS:ON")
    parts.append(f"MODEL:{model_label}")
    if mem:
        parts.append(f"MEM:{mem}")
    if tasks:
        parts.append(f"TASKS:{tasks}")
    # Dojo gate: pinned project + current task from PROJECTS.md board
    if ACTIVE_PROJECT:
        proj_short = ACTIVE_PROJECT[:18]
        parts.append(f"PROJ:{proj_short}")
    if ACTIVE_TASK:
        task_short = ACTIVE_TASK[:40] + ("…" if len(ACTIVE_TASK) > 40 else "")
        parts.append(f"TASK:{task_short}")

    content = "  │  ".join(parts)
    # Status line is ninja-free — the header already carries the brand
    # ninja. Two ninjas across the top row reads as clutter (Elijah
    # 2026-04-20: "🥷 MASTER AI — SENSEI … 🥷 MODE:SAFE … too much").
    tag = content

    # In TUI mode, the status lives in the top-right overlay — not the scrollback.
    if _SENSEI_APP is not None:
        _SENSEI_APP.set_status(tag)
        return

    cols = _term_cols()
    display_len = len(tag) + 3  # ninja emoji = 2 cols + padding
    pad = max(0, cols - display_len)
    if display_len > cols:
        tag = tag[:cols - 1]
        pad = 0
    print(f"\n{' ' * pad}{BC}{tag}{X}")

# ── MAIN HANDLER ─────────────────────────────────────────────
# ── LOOP MODE — plan / execute / critique / refine ──────────────
# Sensei's self-critique loop. Explicit opt-in via `loop:` prefix.
# Each step runs through the normal handle() path, so all existing
# sandbox gates (sudo handoff, CWD fence, confirm prompts, blocked
# patterns) stay enforced. The loop adds a THIN layer of planning +
# critiquing around it — it does not bypass anything.
LOOP_MAX_CYCLES  = 5
LOOP_MAX_SECONDS = 600   # 10 minutes wall-clock ceiling

def _loop_ai(prompt, history, max_tokens=600):
    """Single AI call used inside the loop — plan, critique, or refine.
    Uses the default local path (keeps the loop offline-capable).
    Not routed through handle() because we don't want sandbox prompts
    inside the planner/critic — these are pure text calls."""
    msgs = [{"role": "user", "content": prompt}]
    try:
        from copy import deepcopy
        # Use the behavior contract so tone stays consistent
        if BEHAVIOR_FILE.exists():
            msgs = [{"role": "system", "content": BEHAVIOR_FILE.read_text()}] + msgs
        import urllib.request
        body = json.dumps({
            "model": MODELS["master"],
            "messages": msgs,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.2},
            "keep_alive": "30m",
        }).encode()
        req = urllib.request.Request("http://localhost:11434/api/chat",
            data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read())
        return (d.get("message") or {}).get("content", "").strip()
    except Exception as e:
        return f"(loop ai error: {e})"

def _loop_parse_steps(plan_text):
    """Extract numbered steps from an AI-generated plan. Accepts:
        1. Step one
        2. Step two
       or:
        - Step
        - Step
       Returns a list of step strings. Caps at 8 to prevent runaway plans."""
    import re
    lines = [ln.strip() for ln in (plan_text or "").splitlines() if ln.strip()]
    steps = []
    for ln in lines:
        m = re.match(r"^(?:\d+[\).]\s*|[-*•]\s+)(.*\S)$", ln)
        if m:
            steps.append(m.group(1).strip())
    return steps[:8]

def _loop_critique_verdict(critique_text):
    """Parse the AI critic's verdict from the critique reply.
    Expected tokens: DONE | RETRY | CONTINUE | STOP.
    Default to CONTINUE if unclear — the loop will move forward; the
    cycle cap stops runaways."""
    t = (critique_text or "").upper()
    for tok in ("DONE", "STOP", "RETRY", "CONTINUE"):
        if tok in t[:200]:
            return tok
    return "CONTINUE"

def handle_loop_task(task, history):
    """Run a task through plan → (execute → critique → refine) × N.
    Bounded by LOOP_MAX_CYCLES and LOOP_MAX_SECONDS. Every step goes
    through handle() so sandbox stays enforced end-to-end."""
    import time as _t
    start = _t.time()
    print()
    print(f"  {BC}🔁  LOOP MODE — {task}{X}")
    print(f"  {D}max {LOOP_MAX_CYCLES} cycles · max {LOOP_MAX_SECONDS//60} min · Ctrl+C to abort{X}")
    print()

    # Phase 1 — plan
    print(f"  {BC}[planning]{X}")
    plan = _loop_ai(
        "Break this task into 3 to 5 numbered steps. Each step must be one "
        "specific action (run a command, write a file, edit a file). "
        "No prose between steps. Plan only — do not execute yet.\n\n"
        f"TASK: {task}"
    )
    steps = _loop_parse_steps(plan)
    if not steps:
        print(f"  {Y}planner returned no parseable steps. raw output:{X}")
        print(f"  {D}{plan[:400]}{X}")
        print(f"  {Y}falling back to single-shot handle(){X}")
        reply = handle(task, history)
        return reply
    print(f"  {BW}plan ({len(steps)} steps):{X}")
    for i, s in enumerate(steps, 1):
        print(f"    {i}. {s}")
    print()

    _audit("LOOP-START", f"{len(steps)} steps: {task[:120]}")

    # Phase 2 — execute + critique + refine, bounded
    executed = []
    cycle = 0
    step_idx = 0
    while step_idx < len(steps) and cycle < LOOP_MAX_CYCLES:
        if _t.time() - start > LOOP_MAX_SECONDS:
            print(f"  {Y}loop hit wall-clock ceiling ({LOOP_MAX_SECONDS//60} min) — stopping{X}")
            break
        cycle += 1
        step = steps[step_idx]
        print(f"  {BC}[step {step_idx+1}/{len(steps)} · cycle {cycle}/{LOOP_MAX_CYCLES}]{X} {step}")

        # Execute step through normal handle() — sandbox enforced here
        try:
            step_reply = handle(step, history)
        except KeyboardInterrupt:
            print(f"\n  {Y}loop interrupted mid-step{X}")
            raise
        executed.append({"step": step, "reply": (step_reply or "")[:500]})

        # Critique
        print(f"  {BC}[critique]{X}")
        critique = _loop_ai(
            "You are reviewing the result of ONE step in a larger task.\n"
            f"ORIGINAL TASK: {task}\n"
            f"STEP ATTEMPTED: {step}\n"
            f"REPLY / RESULT:\n{(step_reply or '(no output)')[:1200]}\n\n"
            "Decide ONE of:\n"
            "  DONE     — the whole task is already complete, stop now.\n"
            "  CONTINUE — this step succeeded, move to the next step.\n"
            "  RETRY    — this step failed, retry it (same step).\n"
            "  STOP     — blocked, can't proceed, surface to user.\n\n"
            "Reply with the single verdict word on the first line, then one "
            "short sentence explaining why.",
            max_tokens=200,
        )
        verdict = _loop_critique_verdict(critique)
        # Print the critique one-liner after the verdict
        first = (critique or "").splitlines()
        one = (first[1] if len(first) > 1 else (first[0] if first else "")).strip()
        print(f"    → {verdict}  {D}{one[:120]}{X}")

        if verdict == "DONE" or verdict == "STOP":
            break
        if verdict == "RETRY":
            continue  # cycle++, same step
        # CONTINUE
        step_idx += 1

    elapsed = int(_t.time() - start)
    print()
    print(f"  {BC}[loop end]{X}  {step_idx}/{len(steps)} steps complete · {cycle} cycles · {elapsed}s")
    _audit("LOOP-END", f"{step_idx}/{len(steps)} steps, {cycle} cycles, {elapsed}s")

    # Return a compact summary as the "reply" so session save + TTS get something meaningful
    summary = f"Loop complete: {step_idx}/{len(steps)} steps in {cycle} cycles ({elapsed}s)."
    history.append({"role": "user", "content": f"loop: {task}"})
    history.append({"role": "assistant", "content": summary})
    return summary


def handle(user_text, history, image_path=None):
    # ── Smart orchestrator: short-circuit special routes before model dispatch ─
    decision = orchestrate(history, user_text, image_path=image_path)
    log(f"ORCHESTRATE: {decision.get('route')} | {decision.get('reason','')}")
    # Stash route + model for the Review-mode confirm prompt's `who` line.
    # Any RUN:/EDIT:/CREATE: directive that fires during this handle() call
    # traces back to this orchestrator decision.
    globals()['LAST_ROUTE'] = decision.get('route') or '?'
    globals()['LAST_MODEL'] = decision.get('model') or ''

    if decision["route"] == "save_refresh":
        handle_save_refresh(history)  # execvp — never returns
        return ""

    if decision["route"] == "ask_user":
        q = decision["question"]
        print(f"\n  {BC}[thinking: need clarification]{X}")
        print(f"  {M}Sensei:{X} {q}\n", flush=True)
        # Record so history stays coherent
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": q})
        return q

    if decision["route"] == "cached":
        # Harvest cache hit — a near-duplicate prompt was answered before.
        # Serve that response. No model call. No network. No tokens.
        resp = decision["response"]
        sim = decision.get("similarity", 0.0)
        src = decision.get("source_model", "?")
        print(f"\n  {BC}[thinking: harvest cache hit sim={sim:.2f} "
              f"(from {src}) — served local, no call made]{X}")
        print(f"  {M}Sensei:{X} {resp}\n", flush=True)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": resp})
        return resp

    if decision["route"] == "time_sensitive_warn":
        # Local brain's training data is frozen. Cloud AI (Groq, etc.)
        # ALSO has a training cutoff, so even 'fast:' would guess. The
        # right tool for "what happened last night" is a web search —
        # live facts, no hallucination. Auto-run it, print the results,
        # done. If web search fails (no internet / DDG down), fall back
        # to the menu so the user still has paths.
        q = (decision.get("original_query") or user_text).splitlines()[0].strip()
        print(f"\n  {BC}[thinking: time-sensitive — fetching live web results instead of guessing]{X}")
        try:
            results = web_search(q)
        except Exception as e:
            results = f"Search unavailable: {e}"
        ok = (results
              and not results.lower().startswith("search unavailable")
              and results.lower() != "no results found.")
        if ok:
            header = (
                f"That's time-sensitive, so I pulled live web results instead "
                f"of guessing from my (frozen) training data."
            )
            body = f"🌐 Results for '{q}':\n{results}"
            msg = f"{header}\n\n{body}"
            print(f"\n  {M}Sensei:{X} {header}\n")
            print(f"  {C}{body}{X}\n", flush=True)
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": msg})
            return msg
        # Web search failed — fall back to the manual menu so the user
        # still has routes available. This path fires offline or if DDG
        # has blocked us.
        have_groq = decision.get("have_groq", False)
        have_or   = decision.get("have_or", False)
        lines = [
            "That sounds time-sensitive and my web search just failed",
            f"(reason: {results}).",
            "",
            "My training data is frozen, so I can't answer from memory",
            "either. Paste any of these to route through a different path:",
            "",
            f"  fast: {q}",
            "      → cloud answer via Groq (needs key from menu 11)" if not have_groq
                else "      → quick cloud answer via Groq",
            f"  deep: {q}",
            "      → qwen3.5:cloud (free, no key needed) or DeepSeek-R1",
            f"  search {q}",
            "      → retry web search",
            "",
            "Or 'mode connected' to switch the session to cloud-first.",
        ]
        msg = "\n".join(lines)
        print(f"\n  {M}Sensei:{X} {msg}\n", flush=True)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": msg})
        return msg

    if decision["route"] == "scope_check":
        q = decision["question"]
        print(f"\n  {BC}[thinking: clarify the scope before writing code]{X}")
        print(f"  {M}Sensei:{X} {q}\n", flush=True)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": q})
        # Auto-log the POC to PROJECTS.md so brainstorms aren't lost.
        _append_poc_stub(user_text)
        return q

    if decision["route"] == "recall_memory":
        print(f"  {BC}[thinking: checking memory]{X}")
        user_text = f"[RECALLED MEMORY]\n{decision['payload']}\n\n[USER ASK]\n{user_text}"

    # Strip 'fast:' prefix if orchestrator identified one
    if decision.get("stripped_text"):
        user_text = decision["stripped_text"]

    # ── Fall through to existing route/model pick, with orchestrator overrides ─
    route, model, reason = detect_route(user_text, has_image=bool(image_path))
    if decision["route"] == "cloud_fast":
        route, model, reason = "cloud", "groq", decision["reason"]
        print(f"  {BC}[thinking: cloud-fast → Groq]{X}")
    elif decision["route"] == "cloud_vision":
        route, model, reason = "vision", decision["model"], decision["reason"]
    elif decision["route"] == "cloud_deep":
        # deepseek-r1 is OpenRouter (true cloud) → route='cloud'.
        # qwen3.5:cloud is Ollama-proxied → route='local' streams through Ollama.
        if decision["model"] == "deepseek-r1":
            route, model, reason = "cloud", "deepseek-r1", decision["reason"]
            print(f"  {BC}[thinking: deep → DeepSeek-R1]{X}")
        else:
            route, model, reason = "local", decision["model"], decision["reason"]
            print(f"  {BC}[thinking: deep → qwen3.5:cloud (397B)]{X}")
    elif decision["route"] == "local" and decision.get("model"):
        # Orchestrator picked a specific local model (coder, qwen2.5:14b, or master)
        route, model, reason = "local", decision["model"], decision["reason"]
    log(f"ROUTE: {route} | {reason}")

    # Build system prompt with current memory + context
    memory_content = load_memory()
    behavior_content = load_behavior()
    # cloud_fast = content-routed chat lane (Groq). It runs on every "hi"-class
    # turn and needs to be cheap. howwework.txt (~17KB) + behavior.md (~18KB)
    # together blow past Groq's request size and returned HTTP 413 on every
    # chat turn before this split (2026-04-22 fix). Load the heavy context
    # only for reasoning/build (cloud_deep or explicit `fast:`/`deep:` cloud).
    is_chat_fast = decision.get("route") == "cloud_fast"
    how_we_work = ""
    try:
        hww_path = Path.home() / "scripts" / "howwework.txt"
        full_hww = hww_path.read_text()
        # Cloud gets full context EXCEPT chat-fast lane; local skips howwework
        # to keep TTFT fast on CPU.
        how_we_work = full_hww if (route in ("cloud", "web") and not is_chat_fast) else ""
    except Exception:
        pass
    os_info = subprocess.run(
        "lsb_release -d | cut -f2", shell=True,
        capture_output=True, text=True, timeout=3).stdout.strip() or "Linux/Ubuntu"
    arch = platform.machine()
    git_ctx = git_context()
    project_ctx = f"\n[ACTIVE PROJECT]\n{ACTIVE_PROJECT}" if ACTIVE_PROJECT else ""
    git_block = f"\n\n{git_ctx}" if git_ctx else ""

    # Same payload split for the behavior block — skip for chat-fast lane.
    _behavior_block = (
        f"[BEHAVIOR]\n{behavior_content}\n\n"
        if behavior_content and not is_chat_fast
        else ""
    )
    LOCAL_SYSTEM = (
        f"You are Master AI on Madam-Mary ({os_info}).\n\n"
        # Scratchpad rule goes FIRST and overrides the "no explanations"
        # rule below — otherwise the model obeys the stricter directive
        # and skips the scratchpad line entirely.
        f"{SCRATCHPAD_SYSTEM_ADDITION}\n"
        "[BEHAVIOR RULES — scratchpad above takes precedence when conflicting]\n"
        "Execute tasks using the documented directive keywords (read, run, runterm, create, edit). "
        "Each directive lives on its OWN line at column 0; never describe directives inline using "
        "their colon-suffixed forms — the parser would match them. "
        "Do the task directly without long explanations (but ALWAYS emit the scratchpad line). "
        "NEVER emit: rm -rf / | mkfs | dd if=\n\n"
        "[PLAN MODE RULE] When MODE is 'plan', emit every step as one of those directive "
        "keywords on its own line. Never emit prose instructions telling the user what THEY "
        "should do — the directives ARE what you execute when the user types 'go'.\n\n"
        f"{_behavior_block}"
        f"[MEMORY]\n{memory_content}"
        f"{project_ctx}"
    )
    CLOUD_SYSTEM = (
        f"You are Master AI — a task-executing AI service agent built by Elijah, "
        f"running on Madam-Mary ({os_info}, {arch}).\n\n"
        "IDENTITY: You are a service tool and automation agent — NOT a conversational assistant. "
        "Your job is to perform tasks: run shell commands, read/write files, search the web, "
        "write code, and automate this Linux machine. When given a task, DO it immediately "
        "using directives — do not explain or describe what you plan to do.\n\n"
        "SHELL ENVIRONMENT: bash on Ubuntu Linux. Always write standard bash — no PowerShell, "
        "no Windows paths. Use `sudo` when elevated permissions are needed. "
        "Use full absolute paths where possible. Prefer `apt` for package installs.\n\n"
        "DIRECTIVES — use these to act on the machine:\n\n"
        "RUN: <bash command>        — captured output (ls, git, pytest, apt, curl)\n"
        "RUNTERM: <bash command>    — spawns in a new graphical terminal (visual/TTY scripts)\n"
        "READ: <filepath>\n"
        "CREATE: <filepath>\n<<<CONTENT\n<content>\n>>>CONTENT\n"
        "EDIT: <filepath>\n<<<FIND\n<text>\n>>>FIND\n<<<REPLACE\n<text>\n>>>REPLACE\n\n"
        "REASON BEFORE EMITTING: reason in ONE short sentence, then the directive on its\n"
        "OWN line at column 0. The reasoning sentence must NEVER contain the literal strings\n"
        "'RUN:', 'RUNTERM:', 'CREATE:', 'EDIT:', 'READ:', 'ASK:', or 'DONE:' — the parser\n"
        "matches those verbatim and would fire a bogus directive.\n\n"
        "PREFER CREATE: over 'bash -c \"echo ... > file\"' redirects — CREATE: writes the\n"
        "file via the directive parser (with auto-chmod on shebangs); redirects run inside\n"
        "bash -c where '$0' is 'bash' not the filename, which breaks self-deleting scripts.\n\n"
        "Rules: DO the task. One [PLAN] line for multi-step. [DONE] when complete. "
        "READ before editing. Full working code. No placeholders. "
        "ALWAYS start non-trivial replies with the [scratchpad:] line — see scratchpad rule below.\n\n"
        "[PLAN MODE RULE] When MODE is 'plan', every step in your reply must be a "
        "directive (one of the documented keywords on its own line) — not prose instructions. "
        "The user types 'go' and your directives fire in order.\n\n"
        f"{SCRATCHPAD_SYSTEM_ADDITION}"
        f"{_behavior_block}"
        f"[HOW WE WORK]\n{how_we_work}\n\n"
        f"[MEMORY]\n{memory_content}"
        f"{project_ctx}"
    )
    # Local routes: omit system message — Modelfile's baked-in SYSTEM is KV-cached by Ollama.
    # Sending a dynamic system message (with memory/os_info) changes the prefix every request,
    # invalidating the KV cache and causing 60-120s prefill on every call on CPU.
    if route in ("local", "vision"):
        if history and history[0]["role"] == "system":
            history.pop(0)
    else:
        if history and history[0]["role"] == "system":
            history[0]["content"] = CLOUD_SYSTEM
        else:
            history.insert(0, {"role": "system", "content": CLOUD_SYSTEM})

    # Auto-inject file content if user mentions filenames
    inject_ctx = auto_inject_context(user_text)
    # For local: prepend directive hint so vanilla qwen2.5:7b emits CREATE:/EDIT:/RUN:
    # instead of describing changes in prose. Plus active project context when set.
    # master-ai has the Modelfile-baked SYSTEM that already knows the directive
    # rules — prepending the ~230-token HINT on top is redundant + dirties the
    # KV-cache prefix + eats the num_ctx=4096 budget. On the Skylake CPU this
    # pushed first-token latency past the 300s timeout after ~10 turns, making
    # Groq fallback the default path (2026-04-22 fix). Vanilla qwen2.5:7b
    # callers still need the hint so they keep getting it.
    if route == "local":
        if model == MODELS["master"]:
            local_prefix = ""
        else:
            local_prefix = LOCAL_DIRECTIVE_HINT
        if ACTIVE_PROJECT:
            local_prefix += f"[Active project: {ACTIVE_PROJECT[:80]}] "
    elif route == "vision" and ACTIVE_PROJECT:
        local_prefix = f"[Task: {ACTIVE_PROJECT[:80]}] "
    else:
        local_prefix = ""
    history.append({"role": "user", "content": local_prefix + user_text + (inject_ctx or "")})

    streamed = False

    if route == "web":
        search_results = web_search(user_text)
        augmented = history[:-1] + [{
            "role": "user",
            "content": f"{user_text}\n\n[Web search results]\n{search_results}"
        }]
        _spin = local_thinking_start()
        reply = ask_cloud(augmented, provider="gemini") or ask_cloud(augmented, provider="groq") or ask_local(augmented)
        local_thinking_stop(_spin)

    elif route == "cloud":
        _spin = local_thinking_start()
        reply = ask_cloud(history, provider=model) or ask_local(history)
        local_thinking_stop(_spin)

    elif route == "vision":
        print(f"{D}  [kimi-k2.5:cloud — vision]{X}")
        reply = ask_local_stream(history, model=MODELS["kimi"], image_path=image_path)
        if not reply:
            reply = ask_local_stream(history, model=MODELS["master"], image_path=image_path)
        if not reply:
            _spin = local_thinking_start()
            # Local routes pop the system message for KV-cache — the fallback
            # cloud call must re-inject CLOUD_SYSTEM or Groq/Gemini are blind
            # to directives, identity, machine context (classic "Do you want
            # to create..." punt pattern).
            fallback_hist = ([{"role": "system", "content": CLOUD_SYSTEM}]
                             + [m for m in history if m.get("role") != "system"])
            reply = ask_cloud(fallback_hist, provider="gemini") or ask_cloud(fallback_hist, provider="groq")
            local_thinking_stop(_spin)
            streamed = False
        else:
            streamed = True

    else:
        reply = ask_local_stream(history, model=model)
        if not reply:
            print(f"\n  {R}⚠ [local model timed out — answering via Groq instead]{X}")
            _spin = local_thinking_start()
            # Same fallback-blindness fix as the vision branch above — inject
            # CLOUD_SYSTEM so Groq knows it's Master AI, knows the directives,
            # knows the machine. Without this it replies as default Groq
            # ("Do you want to create a new file, edit...") — the exact punt
            # pattern we're killing.
            fallback_hist = ([{"role": "system", "content": CLOUD_SYSTEM}]
                             + [m for m in history if m.get("role") != "system"])
            reply = ask_cloud(fallback_hist, provider="groq") or ask_cloud(fallback_hist, provider="hermes-405b")
            local_thinking_stop(_spin)
        else:
            streamed = True

    if not reply:
        reply = "No response from AI."

    result = process_reply(reply, history, streamed=streamed)

    # READ: was triggered — re-ask with injected file content
    if result is None:
        if route in ("cloud", "web"):
            _spin2 = local_thinking_start()
            reply2 = ask_cloud(history)
            local_thinking_stop(_spin2)
        else:
            reply2 = ask_local_stream(history, model=model)
            streamed = True
        if reply2:
            process_reply(reply2, history, streamed=streamed)
            reply = reply2

    history.append({"role": "assistant", "content": reply})

    # Inject active tasks into system prompt context
    tasks = load_tasks()
    active = [t for t in tasks if not t.get("done", False)]
    if active and history and history[0]["role"] == "system":
        task_block = "\n\n[ACTIVE TASKS]\n" + "\n".join(f"• {t['text']}" for t in active)
        if "[ACTIVE TASKS]" not in history[0]["content"]:
            history[0]["content"] += task_block
        else:
            history[0]["content"] = re.sub(r'\[ACTIVE TASKS\].*', task_block.strip(), history[0]["content"], flags=re.DOTALL)

    compact_history(history)
    return reply

# ── SESSION SUMMARY ──────────────────────────────────────────
def summarize_session(history):
    msgs = [m for m in history if m.get("role") in ("user", "assistant")]
    if len(msgs) < 4:
        return None
    transcript = "\n".join(
        f"{m['role'].upper()}: {m['content'][:300]}" for m in msgs[-30:]
    )
    prompt = (
        "Summarize this AI session in exactly 4 bullets. Be specific about what was worked on, "
        "what was decided, what is unfinished, and what to do next. "
        "Format: • bullet\n• bullet\n• bullet\n• bullet\n\n" + transcript
    )
    try:
        result = (ask_cloud_groq([{"role": "user", "content": prompt}])
                  or ask_local([{"role": "user", "content": prompt}], model=MODELS["general"]))
        return result.strip() if result else None
    except Exception:
        return None

def save_session(history, silent=False):
    global CHARS_SINCE_SAVE
    with _SAVE_LOCK:
        msgs = [m for m in history if m.get("role") in ("user", "assistant")]
        if len(msgs) < 2:
            return
        CHATS_DIR.mkdir(exist_ok=True)
        ts = SESSION_TS          # always same file — overwrites, never duplicates
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        CHARS_SINCE_SAVE = 0

    # Full chat log
    chat_path = CHATS_DIR / f"{ts}.chat"
    with open(chat_path, "w") as f:
        for m in msgs:
            label = "You" if m["role"] == "user" else "AI"
            f.write(f"[{date_str}] {label}: {m['content'][:2000]}\n")

    if not silent:
        play_anim(_A_BOW, delay=0.14, color=C)
        print(f"\n{C}  📝 Summarizing session...{X}", flush=True)

    summary = summarize_session(history)
    if summary:
        summary_path = CHATS_DIR / f"{ts}.summary"
        summary_path.write_text(f"[Session {date_str}]\n{summary}\n")
        try:
            existing = MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""
            lines = [l for l in existing.splitlines() if not l.startswith("[Session ")]
            session_lines = [l for l in existing.splitlines() if l.startswith("[Session ")][-4:]
            new_memory = "\n".join(lines + session_lines + [f"[Session {date_str}]"] + summary.splitlines())
            MEMORY_FILE.write_text(new_memory + "\n")
        except Exception:
            pass
        if not silent:
            print(f"{G}  ✅ Saved + summarized → {summary_path.name}{X}")
            print(f"{D}  {summary[:200]}{X}")
    elif not silent:
        print(f"{G}  ✅ Session saved → {chat_path.name}{X}")

def _auto_save_background(history):
    """Run save_session silently in a background thread."""
    try:
        save_session(list(history), silent=True)
    except Exception:
        pass

def _query_worker(history_ref):
    """Serial worker: pop queued queries, run handle(), handle reply+cache+tts+autosave.
    Runs forever as a daemon thread. history_ref is the main loop's live history list."""
    while True:
        item = _QUERY_QUEUE.get()
        if item is None:            # sentinel = shutdown
            _QUERY_QUEUE.task_done()
            break
        user_text, image_path = item
        _WORKER_BUSY.set()
        try:
            stop_idle_tips()        # don't overlap with reply output
            reply = handle(user_text, history_ref, image_path=image_path)
            reply = sanitize(reply) if reply else reply
            cache_store(user_text, reply)
            if TTS_ENABLED:
                threading.Thread(target=speak, args=(reply,), daemon=True).start()
            globals()['CHARS_SINCE_SAVE'] = CHARS_SINCE_SAVE + len(user_text) + len(reply or "")
            if CHARS_SINCE_SAVE >= AUTO_SAVE_THRESHOLD:
                threading.Thread(target=_auto_save_background, args=(list(history_ref),), daemon=True).start()
            remaining = _QUERY_QUEUE.qsize()
            if remaining > 0:
                print(f"  {D}— next in queue ({remaining} left) —{X}")
        except Exception as e:
            log(f"WORKER_ERROR: {e}")
            print(f"  {R}worker error: {e}{X}")
        finally:
            _WORKER_BUSY.clear()
            globals()['_LAST_BUSY_CLEARED_TS'] = time.time()
            _QUERY_QUEUE.task_done()

def handle_save_refresh(history):
    """Snapshot session, flag a full-history resume, soft re-exec. Mirrors L2831-2843 refresh."""
    print(f"\n{C}  🥷 Taking notes before turning the page — hold tight.{X}", flush=True)
    try:
        save_session(list(history), silent=True)
    except Exception as e:
        log(f"SAVE_REFRESH_SAVE_ERROR: {e}")
    try:
        chat_path = CHATS_DIR / f"{SESSION_TS}.chat"
        RESUME_FLAG.write_text(str(chat_path))
    except Exception as e:
        log(f"SAVE_REFRESH_FLAG_ERROR: {e}")
    try:
        subprocess.run(["stty", "sane"], check=False)
    except Exception:
        pass
    sys.stdout.write("\033c\033[2J\033[H")
    sys.stdout.flush()
    os.execvp(sys.executable, [sys.executable, str(Path.home() / "scripts/master_ai.py")])

def show_last_summary():
    """Compact 1-line session note. 'load summary' reveals the full bullets."""
    try:
        summaries = sorted(CHATS_DIR.glob("*.summary"), reverse=True)
        if not summaries:
            return
        latest = summaries[0]
        content = latest.read_text().strip()
        lines = content.splitlines()
        date_line = (lines[0] if lines else "").replace("[", "").replace("]", "")
        print(f"  {D}◉ last session: {date_line}  {C}→ 'load summary' to restore{X}")
    except Exception:
        pass

# ── MAIN LOOP ─────────────────────────────────────────────────
def main():
    # In TUI mode prompt_toolkit owns the alternate screen — don't shell out
    # to `clear`, it writes ANSI directly to the real terminal and confuses
    # the full-screen rendering, often causing a 2-second silent exit.
    if _SENSEI_APP is None:
        os.system('clear')
    log("=== MASTER AI STARTED ===")

    # Permissions wizard — first time only (type 'perms' to replay)
    if not PERMS_FILE.exists():
        permissions_wizard()
        PERMS_FILE.touch()

    startup_check()

    # ── Auto-resize tmux pane to match the ACTUAL client terminal dims ──
    # resize-window -A uses the client's bounds, but we also fetch them
    # explicitly so we can log the mismatch if the pane is still small.
    if os.environ.get("TMUX"):
        subprocess.run(["tmux", "set-window-option", "-g", "aggressive-resize", "on"],
                       check=False, capture_output=True)
        try:
            r = subprocess.run(
                ["tmux", "display-message", "-p", "#{client_width}x#{client_height}"],
                capture_output=True, text=True, timeout=2, check=False,
            )
            dims = (r.stdout or "").strip()
            if "x" in dims:
                w, h = dims.split("x", 1)
                subprocess.run(["tmux", "resize-window", "-x", w, "-y", h],
                               check=False, capture_output=True)
                subprocess.run(["tmux", "refresh-client", "-S"],
                               check=False, capture_output=True)
        except Exception as e:
            log(f"RESIZE_ERROR: {e}")

    # ── Collect boot status silently (no heavy output yet) ────────
    # Count loaded cloud KEYS — skip usage counters / metadata (names with '_')
    cloud_keys_loaded = [k for k, v in (KEYS or {}).items()
                         if v and "_" not in k]
    mem_count = 0
    try:
        mem_count = len([l for l in MEMORY_FILE.read_text().splitlines() if l.strip()])
    except Exception:
        pass
    if cloud_keys_loaded:
        n = len(cloud_keys_loaded)
        cloud_status = f"LOCAL + {n} cloud key{'s' if n != 1 else ''}"
    else:
        cloud_status = "LOCAL ONLY"

    # ── Clear screen so banner is always at TOP of the visible pane ─
    # (classic mode only — TUI manages its own scrollback region)
    if _SENSEI_APP is None:
        os.system('clear')

    # ── Use the SAME banner as master.sh main menu (brand.sh banner_master_ai) ─
    # In TUI mode we must CAPTURE the subprocess output and push it through
    # sys.stdout (the shim); otherwise the bash child writes directly to the
    # real terminal FD, bypassing the scrollable output region.
    try:
        if _SENSEI_APP is not None:
            res = subprocess.run(
                "source ~/scripts/brand.sh && banner_master_ai",
                shell=True, executable="/bin/bash",
                capture_output=True, text=True, check=False,
            )
            sys.stdout.write(res.stdout or "")
            sys.stdout.flush()
        else:
            subprocess.run(
                "source ~/scripts/brand.sh && banner_master_ai",
                shell=True, executable="/bin/bash", check=False,
            )
    except Exception:
        # Fallback if brand.sh is missing
        print(f"{BC}  ╔══════════════════════════════════════════╗{X}")
        print(f"{BC}  ║  🥷  MASTER  AI  — ready                  ║{X}")
        print(f"{BC}  ╚══════════════════════════════════════════╝{X}")
    print(f"  {G}● engine ONLINE  │  {cloud_status}  │  {mem_count} facts{X}")
    print()

    show_last_summary()

    if not TUTORIAL_FILE.exists():
        show_hint("First time? Try the tutorial",
                  "Type 'tutorial' to learn all features step-by-step.\nOr just start typing — I'll respond to plain English.")

    history = []
    globals()['GLOBAL_HISTORY'] = history

    # ── Auto-resume from save-refresh flag (compacted, not full) ──
    resumed_from_notes = False
    try:
        if RESUME_FLAG.exists():
            chat_path = Path(RESUME_FLAG.read_text().strip())
            if chat_path.exists():
                for line in chat_path.read_text().splitlines():
                    m = re.match(r'^\[[\d\-]+\s+[\d:]+\]\s+(You|AI):\s+(.*)$', line)
                    if m:
                        role = "user" if m.group(1) == "You" else "assistant"
                        history.append({"role": role, "content": m.group(2)})
                total_loaded = len(history)
                # Compact immediately so we don't re-trigger save_refresh on the next turn
                compact_history(history)
                # If STILL over half the watermark, trim further (keep last 20 turns)
                total_chars = sum(len(m.get("content", "") or "") for m in history)
                if total_chars > CONTEXT_WATERMARK // 2 and len(history) > 20:
                    history[:] = history[-20:]
                    total_chars = sum(len(m.get("content", "") or "") for m in history)
                print(f"  {G}🥷 Resumed from notes — {total_loaded} turns loaded, "
                      f"compacted to {len(history)} ({total_chars} chars).{X}\n")
                resumed_from_notes = True
            try:
                RESUME_FLAG.unlink()
            except Exception:
                pass
    except Exception as e:
        log(f"RESUME_ERROR: {e}")

    # ── Auto-restore last session summary (only if not already resumed) ─
    if not resumed_from_notes:
        try:
            summaries = sorted(CHATS_DIR.glob("*.summary"), reverse=True)
            if summaries:
                last = summaries[0].read_text().strip()
                # Only auto-load if summary is from today or yesterday (recent session)
                import stat as _stat
                age_hours = (time.time() - summaries[0].stat().st_mtime) / 3600
                if age_hours < 48:
                    history.append({"role": "user",
                        "content": f"[Resuming from last session — context loaded automatically]\n{last}"})
                    history.append({"role": "assistant",
                        "content": "Got it — I have your last session loaded. Continue where we left off."})
                    print(f"  {G}✅ Last session restored into context.{X}")
                    print(f"  {D}(type 'clear history' to start fresh){X}\n")
        except Exception:
            pass

    # Save on any exit — force-close, terminal close, Ctrl+C, SIGTERM
    def _exit_save(signum=None, frame=None):
        save_session(GLOBAL_HISTORY, silent=True)
        sys.exit(0)

    atexit.register(lambda: save_session(GLOBAL_HISTORY, silent=True))
    # signal.signal() only works in the MAIN thread. In TUI mode main() runs
    # in a worker thread, so installing handlers here would raise ValueError
    # and silently exit. atexit still covers normal shutdown; the TUI owner
    # installs its own signal handling in the main thread.
    if _SENSEI_APP is None:
        signal.signal(signal.SIGTERM, _exit_save)
        signal.signal(signal.SIGHUP, _exit_save)   # fires when terminal window closes

    # NOTE: v1.7.11 reverted the async query worker — it raced with
    # interactive RUN/CREATE/EDIT confirmation prompts for stdin, causing
    # user input to be misrouted. handle() now runs inline in main loop.

    while True:
        # If a RUN: confirm was redirected to the AI (option 5 or smart-edit
        # catching natural language), replay that as the next user message.
        if PENDING_USER_NOTE:
            cmd = PENDING_USER_NOTE
            globals()['PENDING_USER_NOTE'] = ""
            print(f"{C}  ▶ Redirecting to AI:{X} {cmd}")
        else:
            draw_status_bar()
            maybe_auto_label(history)
            if _SENSEI_APP is None:
                print_thread_box_top()
                print_legend()
                start_idle_tips()
            else:
                _SENSEI_APP.set_label(load_thread_label())
            try:
                _lbl = load_thread_label()
                if _SENSEI_APP is None:
                    _tag = f"{BC}{_lbl}{X} " if _lbl else ""
                    cmd = sanitize(input(f"│ {_tag}🥷  "))
                else:
                    cmd = sanitize(input(""))
            except KeyboardInterrupt:
                if _SENSEI_APP is None:
                    stop_idle_tips()
                    print_thread_box_bottom()
                save_session(history, silent=True)
                break
            except EOFError:
                if _SENSEI_APP is None:
                    stop_idle_tips()
                    print_thread_box_bottom()
                save_session(history, silent=True)
                break
            finally:
                if _SENSEI_APP is None:
                    stop_idle_tips()
            if _SENSEI_APP is None:
                print_thread_box_bottom()

        if not cmd:
            continue

        lo = cmd.lower()

        # ── Exit ──────────────────────────────────────────────
        if lo == "x":
            save_session(history)
            play_anim(_A_VANISH, delay=0.12, color=BC)
            print(f"{G}  Goodbye.\n{X}")
            log("=== MASTER AI STOPPED ===")
            # Exit 99 tells the supervisor this was a deliberate quit.
            # Any other exit code triggers auto-restart.
            sys.exit(99)

        # ── How We Work — print ~/scripts/howwework.txt on demand ─
        # Same content menu option 10 shows from master.sh, accessible
        # without leaving Sensei. Also covered by short aliases — Elijah
        # uses voice-to-text and "how we work" often comes through as
        # variants like "hww" or "howwework" typed by the tab-completer.
        if lo in ("how we work", "how", "hww", "howwework", "how_we_work"):
            hww_path = Path.home() / "scripts" / "howwework.txt"
            try:
                text = hww_path.read_text(errors="replace")
            except FileNotFoundError:
                print(f"  {Y}howwework.txt not found at {hww_path}{X}")
                continue
            except Exception as e:
                print(f"  {R}couldn't read howwework.txt: {e}{X}")
                continue
            print(f"\n{BC}══ How We Work ══{X}\n{text}\n{D}──────────────────{X}")
            continue

        # ── Auto-advancing tips carousel ──────────────────────
        if lo in ("autotips", "auto tips", "slideshow", "carousel", "tour"):
            show_autotips()
            continue

        # ── Projects slide show ───────────────────────────────
        if lo in ("projects", "apps", "my apps", "my projects"):
            maybe_msg = show_projects()
            if maybe_msg:
                cmd = maybe_msg; lo = cmd.lower()
            else:
                continue

        # ── Hub menu (numbered actions) ───────────────────────
        if lo in ("hub", "menu", "main", "home"):
            chosen = show_hub()
            if chosen:
                cmd = chosen
                lo = cmd.lower()
                # fall through to normal dispatch + AI routing
            else:
                continue

        # ── Help slide toggles — hide/show specific sections ────────
        if lo.startswith("help hide ") or lo.startswith("help show "):
            action, _, name = lo[5:].partition(" ")  # strip leading "help "
            name = name.strip().upper()
            if not name:
                print(f"  {Y}Usage: help hide <SECTION> | help show <SECTION>{X}")
                continue
            hidden = _load_hidden_help_sections()
            if action == "hide":
                hidden.add(name)
                _save_hidden_help_sections(hidden)
                print(f"  {G}✓ hidden '{name}' — type `help reset` to restore all{X}")
            elif action == "show":
                hidden.discard(name)
                _save_hidden_help_sections(hidden)
                print(f"  {G}✓ '{name}' will show again on next `help`{X}")
            continue
        if lo == "help reset":
            _save_hidden_help_sections(set())
            print(f"  {G}✓ all help slides restored{X}")
            continue

        # ── Help (slide show — may return a typed message) ────
        if lo == "help":
            maybe_msg = show_help()
            if maybe_msg:
                cmd = maybe_msg
                lo = cmd.lower()
                # fall through to normal dispatch + AI routing
            else:
                continue

        # ── Tips screen ───────────────────────────────────────
        if lo in ("tips", "tip"):
            show_tips()
            os.system("clear")
            continue

        # ── Model picker ──────────────────────────────────────
        if lo in ("model", "models") or lo == "model auto":
            if lo == "model auto":
                globals()['PINNED_MODEL'] = None
                print(f"  {G}✅ Smart routing restored.{X}")
            else:
                show_model_menu()
            continue

        # ── Tutorial ──────────────────────────────────────────
        if lo == "tutorial":
            run_tutorial()
            os.system("clear")
            continue

        # ── No mouse / accessibility ──────────────────────────
        SETTINGS_FILE = Path.home() / ".master_ai_settings"
        if lo in ("no mouse", "no-mouse", "keyboard mode"):
            settings = SETTINGS_FILE.read_text() if SETTINGS_FILE.exists() else ""
            if "NO_MOUSE" not in settings:
                SETTINGS_FILE.write_text(settings + "\nNO_MOUSE=1\n")
            print(f"  {G}✅ No-mouse mode ON — arrow keys navigate menus, Tab/Enter to confirm.{X}")
            continue
        if lo in ("mouse on", "mouse mode"):
            if SETTINGS_FILE.exists():
                lines = [l for l in SETTINGS_FILE.read_text().splitlines() if "NO_MOUSE" not in l]
                SETTINGS_FILE.write_text('\n'.join(lines) + '\n')
            print(f"  {G}✅ Mouse mode restored.{X}")
            continue
        if lo == "accessibility":
            settings = SETTINGS_FILE.read_text() if SETTINGS_FILE.exists() else ""
            nm = "ON" if "NO_MOUSE" in settings else "OFF"
            pm = "ON" if "PHONE_MODE" in settings else "OFF"
            print(f"  {C}No-mouse: {G if nm=='ON' else Y}{nm}{X}   Phone mode: {G if pm=='ON' else Y}{pm}{X}")
            continue

        # ── TTS toggle ────────────────────────────────────────
        if lo in ("tts on", "tts off", "tts"):
            s = _SETTINGS.read_text() if _SETTINGS.exists() else ""
            if lo == "tts off":
                if "TTS_OFF" not in s:
                    _SETTINGS.write_text(s + "\nTTS_OFF=1\n")
                globals()['TTS_ENABLED'] = False
                print(f"  {Y}🔇 Voice off. Type 'tts on' to re-enable.{X}")
            elif lo == "tts on":
                _SETTINGS.write_text('\n'.join(l for l in s.splitlines() if "TTS_OFF" not in l) + '\n')
                globals()['TTS_ENABLED'] = True
                print(f"  {G}🔊 Voice on — replies will be spoken.{X}")
            else:
                state = "ON" if TTS_ENABLED else "OFF"
                print(f"  {C}Voice (TTS) is {state}.{X}")
            continue

        # ── Hints ─────────────────────────────────────────────
        if lo == "hints off":
            HINTS_FILE.touch()
            globals()['HINTS'] = 0
            print(f"  {Y}✅ Hints off. Type 'hints on' to bring them back.{X}")
            continue
        if lo in ("hints on", "hints"):
            if lo == "hints on":
                HINTS_FILE.unlink(missing_ok=True)
                globals()['HINTS'] = 1
                print(f"  {G}✅ Hints on.{X}")
            else:
                state = "ON" if HINTS else "OFF"
                print(f"  {C}Hints are {state}.{X}")
            continue

        # ── Run-mode (routing preference — apocalypse/local vs peacetime/cloud) ──
        # Independent of execution mode (safe/plan/auto). This one decides
        # whether the orchestrator prefers the LOCAL engine or routes to
        # cloud when keys exist.
        if lo in ("mode local", "mode offline", "mode in-house", "mode apocalypse"):
            try:
                (Path.home() / ".master_ai_run_mode").write_text("apocalypse")
            except Exception:
                pass
            print()
            print(f"  {BC}🏠  Local Mode{X}  {D}(your AI, your hardware, no internet needed){X}")
            print(f"  {W}What this gives you:{X}")
            print(f"    · A tool, not a subscription. Like a book or a cassette — it works because")
            print(f"      you own it, not because a company kept the lights on.")
            print(f"    · The same Sensei will start up in 10 years. No key to renew, no service to")
            print(f"      cancel on you, no cloud that might turn you off.")
            print(f"    · Everything stays on your machine. Nothing leaves.")
            print(f"    · Built to outlive the company that sold it.")
            print(f"  {W}The trade:{X}")
            print(f"    · Answers come at human pace, not instant. That's fine — good work isn't")
            print(f"      measured in tokens per second.")
            print(f"    · You won't chase the newest cloud model. You don't need to.")
            print(f"    · If you're online and want cloud speed, borrow it per-message:")
            print(f"        {BC}fast:{X} <your message>  → one reply through Groq (fastest free cloud)")
            print(f"        {BC}deep:{X} <your message>  → one reply through DeepSeek-R1 (reasoning)")
            print()
            continue
        if lo in ("mode connected", "mode online", "mode cloud", "mode peacetime"):
            try:
                (Path.home() / ".master_ai_run_mode").write_text("peacetime")
            except Exception:
                pass
            print()
            print(f"  {BC}☁  Connected Mode{X}  {D}(uses free cloud for speed while you're online){X}")
            print(f"  {W}What this gives you:{X}")
            print(f"    · Groq Llama 3.3 70B for default asks — ~0.3 second replies.")
            print(f"    · DeepSeek-R1 for reasoning — closest free path to top-tier quality.")
            print(f"    · Gemini 2.0 Flash for vision + web-aware questions.")
            print(f"  {W}The trade:{X}")
            print(f"    · Needs internet. If it drops, Sensei falls back to your local models.")
            print(f"    · Cloud prompts leave your box. Providers may log them.")
            print(f"    · Cloud keys can hit daily free-tier quotas — rare, but it happens.")
            print(f"  {W}Force local anytime:{X}")
            print(f"    · {BC}local:{X} <message>   → this one goes to your machine, not the cloud.")
            print(f"    · {BC}private:{X} <message> → same, logged as privacy-intended.")
            print()
            continue

        # ── Mode (execution safety: safe / plan / auto) ──────────────
        # All banner text lives in MODE_CONTRACTS (one source of truth).
        # show_mode_status() prints the full contract, so every mode
        # switch — including safe — leaves a matching banner in scrollback.
        # Also re-tints the TUI header + frame + status line via
        # SenseiApp.set_mode() so the color signals the mode at a glance.
        if lo in ("mode plan", "mode review", "mode auto"):
            new_mode = lo.split()[1]
            globals()['MODE'] = new_mode
            save_mode(new_mode)  # persist so next launch opens in this mode
            show_mode_status()
            if _SENSEI_APP is not None:
                try: _SENSEI_APP.set_mode(new_mode)
                except Exception: pass
            continue
        if lo == "mode":
            show_mode_status()
            continue

        # ── Plan demo ─────────────────────────────────────────
        if lo in ("plan demo", "demo plan", "how plan", "plan help"):
            show_plan_demo()
            continue

        # ── Plan mode: single-key 1/2/3/4 dispatch ─────────────
        # Typing 1/2/3/4 after a plan is shown fires the matching button.
        # Empty line (just Enter) = accept, same as "1" — Elijah 2026-04-20:
        # "I'll see the text pop up and I'll press enter." `go`/`yes` are
        # kept as legacy aliases so existing muscle memory still works.
        # Guarded on PENDING_PLAN_TEXT so a stray Enter on an empty line
        # doesn't eat anything else.
        if PENDING_PLAN_TEXT and lo in (
            "", "1", "go", "yes", "y", "proceed", "execute", "go ahead"
        ):
            # Handoff from Plan to Review — VISIBLY. Switch the internal
            # mode AND repaint the TUI (set_mode) so Elijah sees amber →
            # red the moment execution starts. We STAY in review after
            # the plan runs instead of auto-reverting; user goes back to
            # plan manually. Elijah 2026-04-20: "if it hands it off then
            # the mode in color should automatically change."
            globals()['MODE'] = "review"
            save_mode("review")  # persist handoff state — reopen lands in review
            if _SENSEI_APP is not None:
                try: _SENSEI_APP.set_mode("review")
                except Exception: pass
            print(f"\n{C}  ▶ handoff: Plan → Review — executing plan...{X}")
            reply = handle(PENDING_PLAN_REQUEST, history)
            globals()['PENDING_PLAN_TEXT'] = ""
            globals()['PENDING_PLAN_REQUEST'] = ""
            if TTS_ENABLED and reply:
                threading.Thread(target=speak, args=(reply,), daemon=True).start()
            print(f"\n  {D}(still in Review mode — type 'mode plan' to go back){X}")
            continue

        # "go"/"yes"/"proceed" with no pending plan → explain
        if lo in ("go", "yes", "y", "proceed", "execute", "go ahead") and not PENDING_PLAN_TEXT:
            print(f"  {Y}No pending plan. Use 'mode plan' then describe your task.{X}")
            continue

        if lo == "2" and PENDING_PLAN_TEXT:
            # Edit the stored plan text. User pastes new text (or hits
            # Enter to keep). The plan stays pending; 1/3/4 still work.
            print(f"\n{Y}  ▶ current plan:{X}\n  {W}{PENDING_PLAN_TEXT}{X}")
            try:
                edited = input(f"  {C}Paste edited plan (Enter = keep as-is): {X}").strip()
            except Exception:
                edited = ""
            if edited:
                globals()['PENDING_PLAN_TEXT'] = edited
                print(f"  {G}✅ plan updated. Press 1 to run, 3 to cancel.{X}")
            else:
                print(f"  {C}plan unchanged. Press 1 to run, 3 to cancel.{X}")
            continue

        if lo in ("3", "no", "n") and PENDING_PLAN_TEXT:
            globals()['PENDING_PLAN_TEXT'] = ""
            globals()['PENDING_PLAN_REQUEST'] = ""
            print(f"  {Y}✅ plan discarded.{X}")
            continue

        if lo == "4" and PENDING_PLAN_TEXT:
            # Drop the plan, but treat nothing else — the NEXT user
            # message flows as a normal Sensei query. Slot for freeform
            # conversation about the plan without executing it.
            globals()['PENDING_PLAN_TEXT'] = ""
            globals()['PENDING_PLAN_REQUEST'] = ""
            print(f"  {C}plan set aside — next message goes to Sensei as a normal chat.{X}")
            continue

        if lo == "cancel":
            if PENDING_PLAN_TEXT:
                globals()['PENDING_PLAN_TEXT'] = ""
                globals()['PENDING_PLAN_REQUEST'] = ""
                print(f"  {Y}✅ Plan cleared.{X}")
            else:
                print(f"  {W}Nothing to cancel.{X}")
            continue

        # ── Task tracker ──────────────────────────────────────
        if lo.startswith("task") or lo == "tasks":
            handle_task_cmd(cmd)
            continue

        # ── Git shortcuts ─────────────────────────────────────
        if lo in ("git", "git status"):
            run_command("git status && git log --oneline -5 2>/dev/null || echo 'Not a git repo'")
            continue
        if lo.startswith("git commit "):
            msg = cmd[11:].strip()
            if msg:
                confirm_run(f'git add -A && git commit -m "{msg}"')
            else:
                print(f"  {Y}Usage: git commit <message>{X}")
            continue
        if lo == "git diff":
            run_command("git diff --stat HEAD 2>/dev/null || echo 'Not a git repo'")
            continue
        if lo == "git log":
            run_command("git log --oneline -10 2>/dev/null || echo 'Not a git repo'")
            continue
        if lo.startswith("git "):
            confirm_run(cmd)
            continue

        # ── Save / Load session ───────────────────────────────
        if lo == "save session":
            save_session(history)
            continue

        # ── Save the whole chat to a local file + optional clipboard ──
        # Elijah 2026-04-20: "sync it internally, don't rely on RustDesk
        # clipboard passthrough." Primary write is to CHATS_DIR — durable,
        # viewable in file manager or Pupil, accessible via Tailscale. A
        # clipboard copy is the SECONDARY path, best-effort, silent on
        # failure so the internal file is the source of truth.
        if lo in ("copy chat", "copy session", "copy", "export chat"):
            try:
                turns = []
                for entry in history:
                    role = entry.get("role", "?").upper()
                    content = (entry.get("content", "") or "").strip()
                    if role == "SYSTEM":
                        continue
                    turns.append(f"## {role}\n\n{content}\n")
                transcript = "\n".join(turns) or "(empty chat)"
                # Primary: write to a timestamped markdown file under CHATS_DIR.
                CHATS_DIR.mkdir(exist_ok=True)
                ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                out_path = CHATS_DIR / f"copy-{ts}.md"
                header = f"# Sensei chat — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                out_path.write_text(header + transcript)
                print(f"  {G}✅ chat saved → {out_path}{X}")
                print(f"  {D}   {len(turns)} turns · {len(transcript)} chars{X}")
                # Secondary: best-effort clipboard copy via xclip. Silent if
                # xclip is missing or X11 CLIPBOARD isn't reachable.
                try:
                    p = subprocess.Popen(
                        ["xclip", "-selection", "clipboard"],
                        stdin=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                    )
                    p.communicate(transcript.encode("utf-8"), timeout=5)
                    if p.returncode == 0:
                        print(f"  {D}   (also copied to clipboard){X}")
                except Exception:
                    pass
            except Exception as e:
                print(f"  {R}copy chat error: {e}{X}")
            continue

        if lo == "load summary":
            try:
                summaries = sorted(CHATS_DIR.glob("*.summary"), reverse=True)
                if not summaries:
                    print(f"  {Y}No summaries found yet.{X}")
                else:
                    content = summaries[0].read_text().strip()
                    history.append({"role": "user", "content": f"[Resuming from last session]\n{content}"})
                    history.append({"role": "assistant", "content": "Got it — I have your last session context loaded. What would you like to continue?"})
                    print(f"  {G}✅ Last session summary loaded into context.{X}")
                    print(f"  {D}{content[:300]}{X}")
            except Exception as e:
                print(f"  {R}❌ {e}{X}")
            continue

        if lo == "load session":
            try:
                chats = sorted(CHATS_DIR.glob("*.chat"), reverse=True)
                if not chats:
                    print(f"  {Y}No saved sessions found.{X}")
                else:
                    content = chats[0].read_text()[-6000:]
                    history.append({"role": "user", "content": f"[Full last session transcript]\n{content}"})
                    history.append({"role": "assistant", "content": "Full session loaded. I have the complete context from last time."})
                    print(f"  {G}✅ Last full session loaded.{X}")
            except Exception as e:
                print(f"  {R}❌ {e}{X}")
            continue

        # ── Scroll commands (word-based — the ONE way to scroll in TUI mode) ─
        if lo == "up" or lo.startswith("up "):
            parts = lo.split()
            n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            if _SENSEI_APP is not None:
                _SENSEI_APP.scroll("up", n=10 * n)
            elif os.environ.get("TMUX"):
                subprocess.run(["tmux", "copy-mode"], check=False)
                for _ in range(n):
                    subprocess.run(["tmux", "send-keys", "-X", "halfpage-up"], check=False)
            else:
                print(f"  {Y}Not in tmux — scroll commands need the tmux session.{X}")
            continue
        if lo == "down" or lo.startswith("down "):
            parts = lo.split()
            n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            if _SENSEI_APP is not None:
                _SENSEI_APP.scroll("down", n=10 * n)
            elif os.environ.get("TMUX"):
                for _ in range(n):
                    subprocess.run(["tmux", "send-keys", "-X", "halfpage-down"], check=False)
            else:
                print(f"  {Y}Not in tmux.{X}")
            continue
        if lo == "top":
            if _SENSEI_APP is not None:
                _SENSEI_APP.scroll("top")
            elif os.environ.get("TMUX"):
                subprocess.run(["tmux", "copy-mode"], check=False)
                subprocess.run(["tmux", "send-keys", "-X", "history-top"], check=False)
            continue
        if lo == "bottom":
            if _SENSEI_APP is not None:
                _SENSEI_APP.scroll("bottom")
            elif os.environ.get("TMUX"):
                subprocess.run(["tmux", "send-keys", "-X", "cancel"], check=False)
            continue
        if lo == "last":
            msgs = [h for h in history if h.get("role") == "assistant"]
            if msgs:
                print(f"\n{G}  ── last reply ──{X}\n{msgs[-1]['content']}\n")
            else:
                print(f"  {Y}No prior reply to show.{X}")
            continue

        # ── Copy last AI reply to X11 clipboard ──────────────────────
        if lo in ("copy", "copy last", "clip"):
            msgs = [h for h in history if h.get("role") == "assistant"]
            if not msgs:
                print(f"  {Y}No reply to copy yet.{X}")
                continue
            content = msgs[-1]["content"]
            for tool in (["xclip", "-selection", "clipboard"],
                         ["wl-copy"],
                         ["xsel", "-b", "-i"]):
                try:
                    p = subprocess.run(tool, input=content, text=True,
                                       capture_output=True, timeout=3)
                    if p.returncode == 0:
                        print(f"  {G}✅ Copied last reply ({len(content)} chars) via {tool[0]}.{X}")
                        break
                except FileNotFoundError:
                    continue
                except Exception as _e:
                    continue
            else:
                print(f"  {Y}No clipboard tool found (tried xclip, wl-copy, xsel).{X}")
                print(f"  {D}Install with: sudo apt install xclip{X}")
            continue

        # ── Kick: force crash so supervisor loop restarts us ─────────
        if lo in ("kick", "force restart", "hard restart"):
            try: save_session(list(history), silent=True)
            except Exception: pass
            print(f"  {R}💥 Kicking engine — supervisor will restart in 3 sec...{X}", flush=True)
            sys.exit(42)

        # ── Resize: snap tmux pane to attached-client dims (full-screen fix) ──
        if lo in ("resize", "maximize", "fit"):
            if os.environ.get("TMUX"):
                try:
                    r = subprocess.run(
                        ["tmux", "display-message", "-p", "#{client_width}x#{client_height}"],
                        capture_output=True, text=True, timeout=2, check=False,
                    )
                    dims = (r.stdout or "").strip()
                    if "x" in dims:
                        w, h = dims.split("x", 1)
                        subprocess.run(["tmux", "resize-window", "-x", w, "-y", h],
                                       check=False, capture_output=True)
                        subprocess.run(["tmux", "refresh-client", "-S"],
                                       check=False, capture_output=True)
                        print(f"  {G}✅ pane snapped to client dims: {dims}{X}")
                    else:
                        subprocess.run(["tmux", "resize-window", "-A"], check=False)
                        print(f"  {G}✅ pane resized (fallback to -A).{X}")
                except Exception as e:
                    print(f"  {R}resize failed: {e}{X}")
                subprocess.run(["tmux", "set-window-option", "-g", "aggressive-resize", "on"],
                               check=False, capture_output=True)
            else:
                print(f"  {Y}not in tmux — resize is automatic in plain terminals.{X}")
            continue

        # ── Only: kill every other tmux pane so Sensei owns the whole window ──
        # Dots (·····) on the side = another pane is splitting your screen.
        if lo in ("only", "full", "fullpane", "alone"):
            if os.environ.get("TMUX"):
                before = subprocess.run(["tmux", "list-panes"], capture_output=True, text=True)
                n = len([l for l in (before.stdout or "").splitlines() if l.strip()])
                if n > 1:
                    subprocess.run(["tmux", "kill-pane", "-a"], check=False)
                    subprocess.run(["tmux", "resize-window", "-A"], check=False)
                    print(f"  {G}✅ killed {n-1} other pane(s) — Sensei is alone now.{X}")
                else:
                    print(f"  {D}already the only pane.{X}")
            else:
                print(f"  {Y}not in tmux.{X}")
            continue

        # ── Refresh: restart engine in-place (for screen glitches) ────
        if lo in ("refresh", "reload", "restart"):
            try:
                save_session(list(history), silent=True)
            except Exception:
                pass
            print(f"  {C}🔄 Refreshing Master AI — screen reset + engine restart...{X}", flush=True)
            try:
                subprocess.run(["stty", "sane"], check=False)
            except Exception:
                pass
            sys.stdout.write("\033c\033[2J\033[H")
            sys.stdout.flush()
            os.execvp(sys.executable, [sys.executable, str(Path.home() / "scripts/master_ai.py")])
            continue  # unreachable

        # ── Clear variants ─────────────────────────────────────
        if lo in ("clear", "clear history"):
            history = [h for h in history if h.get("role") == "system"]
            print(f"  {G}✅ Conversation cleared.{X}")
            continue

        # ── Quick label edit: 'e', 'edit', or the pencil glyph ───────
        if lo in ("e", "edit", "✏", "✎"):
            current = load_thread_label()
            try:
                suffix = f" (current: {current})" if current else ""
                new_name = sanitize(input(f"  {D}✏{X}  label{suffix}: "))
            except (EOFError, KeyboardInterrupt):
                print()
                continue
            new_name = new_name.strip()
            if not new_name:
                continue
            if new_name.lower() == "clear":
                save_thread_label("")
                print(f"  {G}✅ label cleared.{X}")
                continue
            if new_name.lower() == "suggest":
                msgs = [m for m in history if m.get("role") in ("user", "assistant")][-8:]
                if not msgs:
                    print(f"  {Y}not enough context yet — chat a bit first.{X}")
                    continue
                transcript = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in msgs)
                prompt = (f"Give a 2-4 word kebab-case label for this conversation "
                          f"(lowercase, hyphens, no punctuation). Output ONLY the label.\n\n{transcript}")
                suggested = ask_cloud_groq([{"role": "user", "content": prompt}]) or ""
                suggested = re.sub(r'[^a-z0-9\-]+', '-', suggested.strip().split("\n")[0].strip().lower()).strip('-')[:40]
                if suggested:
                    save_thread_label(suggested)
                    print(f"  {G}✅ label:{X} {BC}{suggested}{X}")
                else:
                    print(f"  {Y}couldn't generate a label — try again later.{X}")
                continue
            save_thread_label(new_name)
            print(f"  {G}✅ label:{X} {BC}{new_name}{X}")
            continue

        # ── Thread label: show / set / suggest ───────────────────
        if lo == "label":
            current = load_thread_label()
            if current:
                print(f"  {C}current label:{X} {BC}{current}{X}")
            else:
                print(f"  {D}no label set.{X}")
            try:
                new_name = sanitize(input(f"  {C}new label (Enter to keep, 'clear' to remove, 'suggest' for AI suggestion):{X} "))
            except (EOFError, KeyboardInterrupt):
                print()
                continue
            new_name = new_name.strip()
            if not new_name:
                continue
            if new_name.lower() == "clear":
                save_thread_label("")
                print(f"  {G}✅ label cleared.{X}")
                continue
            if new_name.lower() == "suggest":
                msgs = [m for m in history if m.get("role") in ("user", "assistant")][-8:]
                if not msgs:
                    print(f"  {Y}not enough context yet — type a few messages first.{X}")
                    continue
                transcript = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in msgs)
                prompt = (f"Give a 2-4 word kebab-case label for this conversation "
                          f"(lowercase, hyphens, no punctuation). Output ONLY the label.\n\n{transcript}")
                suggested = ask_cloud_groq([{"role": "user", "content": prompt}]) or ""
                suggested = suggested.strip().split("\n")[0].strip().lower()
                suggested = re.sub(r'[^a-z0-9\-]+', '-', suggested).strip('-')[:40]
                if suggested:
                    save_thread_label(suggested)
                    print(f"  {G}✅ label set to:{X} {BC}{suggested}{X}")
                else:
                    print(f"  {Y}suggestion failed.{X}")
                continue
            save_thread_label(new_name)
            print(f"  {G}✅ label set to:{X} {BC}{new_name}{X}")
            continue

        if lo.startswith("label:") or lo.startswith("label "):
            new_name = cmd.split(":", 1)[1].strip() if ":" in cmd else cmd.split(None, 1)[1].strip() if len(cmd.split()) > 1 else ""
            if new_name:
                save_thread_label(new_name)
                print(f"  {G}✅ label set to:{X} {BC}{new_name}{X}")
            continue

        # ── Natural-language label setters ──────────────────────────
        # "save this as X" / "save as X" / "save with X" / "save it as X"
        # "name this X" / "call this X" / "label this X"
        _m_label = re.match(
            r'^(?:save\s+(?:this\s+|it\s+)?(?:as|with)|'
            r'name\s+this|call\s+this|label\s+this|'
            r'set\s+label\s+(?:to|as))\s+(.+)$',
            lo
        )
        if _m_label:
            new_name = _m_label.group(1).strip().strip(".,!?\"'").strip()
            if new_name:
                save_thread_label(new_name)
                print(f"  {G}✅ label set to:{X} {BC}{new_name}{X}")
            continue
        if lo == "clear approved":
            APPROVED_FILE.write_text("")
            print(f"  {G}✅ Approved list cleared.{X}")
            continue
        if lo == "clear cache":
            CACHE_FILE.unlink(missing_ok=True)
            print(f"  {G}✅ Cache cleared.{X}")
            continue

        # ── Chats list / delete ────────────────────────────────
        if lo in ("chats", "clear chats") or lo.startswith("clear chats "):
            files = sorted(CHATS_DIR.glob("*"), key=lambda f: f.stat().st_mtime, reverse=True) if CHATS_DIR.exists() else []
            if lo == "chats":
                if not files:
                    print(f"  {Y}No saved chats found.{X}")
                else:
                    print(f"\n  {C}Saved chats ({len(files)} files):{X}")
                    for idx, f in enumerate(files, 1):
                        sz = f.stat().st_size
                        sz_str = f"{sz//1024}KB" if sz >= 1024 else f"{sz}B"
                        dt = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                        print(f"  {W}{idx:>3}.{X} {dt}  {f.name:<40} {D}({sz_str}){X}")
                    print(f"\n  {D}Type 'clear chats' to delete all, or 'clear chats 2' to delete #2{X}\n")
            elif lo == "clear chats":
                if not files:
                    print(f"  {Y}No saved chats to delete.{X}")
                else:
                    conf = input(f"  {Y}Delete all {len(files)} chat files? (yes/no): {X}").strip().lower()
                    if conf in ("y", "yes"):
                        for f in files:
                            f.unlink(missing_ok=True)
                        print(f"  {G}✅ All {len(files)} chat files deleted.{X}")
                    else:
                        print(f"  {D}Cancelled.{X}")
            else:
                try:
                    n = int(lo.split()[-1]) - 1
                    if 0 <= n < len(files):
                        target = files[n]
                        target.unlink(missing_ok=True)
                        print(f"  {G}✅ Deleted: {target.name}{X}")
                    else:
                        print(f"  {R}No file #{n+1}. Type 'chats' to see the list.{X}")
                except ValueError:
                    print(f"  {R}Usage: clear chats <number>  e.g. 'clear chats 2'{X}")
            continue

        # ── Permissions ───────────────────────────────────────
        if lo == "perms":
            permissions_wizard()
            continue

        # ── Memory ────────────────────────────────────────────
        if lo == "memory":
            lines = [l for l in (MEMORY_FILE.read_text().splitlines()
                                  if MEMORY_FILE.exists() else []) if l.strip()]
            if lines:
                print(f"\n{C}  📧 Memory ({len(lines)} facts):{X}")
                for l in lines:
                    print(f"  {Y}•{X} {l}")
            else:
                print(f"  {C}  Memory is empty.{X}")
            print()
            continue

        if lo.startswith("remember:"):
            fact = cmd[9:].strip()
            if fact:
                with open(MEMORY_FILE, "a") as f:
                    f.write(fact + "\n")
                print(f"  {G}✅ Remembered: {fact}{X}")
                show_hint("Memory tip",
                    "Facts you teach me are injected into every message.\n"
                    "Type 'memory' to see all facts.\n"
                    "Type 'forget: <word>' to remove one.")
            continue

        if lo.startswith("forget:"):
            keyword = cmd[7:].strip()
            if keyword and MEMORY_FILE.exists():
                lines = MEMORY_FILE.read_text().splitlines()
                kept = [l for l in lines if keyword.lower() not in l.lower()]
                MEMORY_FILE.write_text('\n'.join(kept) + '\n')
                print(f"  {G}✅ Removed {len(lines)-len(kept)} line(s) matching: {keyword}{X}")
            continue

        # ── Keys ──────────────────────────────────────────────
        if lo == "keys":
            known = [('groq','Groq'),('openai','OpenAI'),('openrouter','OpenRouter'),
                     ('anthropic','Anthropic'),('gumroad','Gumroad')]
            print(f"\n{C}  API Keys:{X}")
            for field, label in known:
                val = KEYS.get(field, '')
                if val:
                    masked = val[:6] + '...' + val[-4:] if len(val) > 10 else '(set)'
                    print(f"  {G}✅ {label:<14}{C}{masked}{X}")
                else:
                    print(f"  {R}○  {label:<14}{Y}not saved{X}")
            print()
            continue

        # ── Approved list ─────────────────────────────────────
        if lo == "approved":
            approved = load_approved()
            if approved:
                print(f"\n{C}  ⚡ Auto-approved ({len(approved)}):{X}")
                for a in sorted(approved):
                    print(f"  {G}✅ {a}{X}")
            else:
                print(f"  {W}  (none){X}")
            print()
            continue

        # ── Cache stats ───────────────────────────────────────
        if lo == "cache":
            try:
                cache = json.loads(CACHE_FILE.read_text())
                hits = sum(e.get('hits', 0) for e in cache.values())
                fresh = sum(1 for e in cache.values() if time.time() - e.get('ts', 0) < 86400)
                print(f"\n  {C}Cache: {len(cache)} entries  |  fresh(24h): {fresh}  |  hits: {hits}{X}\n")
            except Exception:
                print(f"  {W}  Cache is empty.{X}\n")
            continue

        if lo == "harvest":
            # Harvest layer stats — how much of YOU has Master AI seen
            if harvest is None:
                print(f"  {W}Harvest module not loaded.{X}\n")
            else:
                try:
                    print(f"\n  {C}{harvest.format_stats()}{X}\n")
                except Exception as e:
                    print(f"  {W}Harvest stats error: {e}{X}\n")
            continue

        # ── Project ───────────────────────────────────────────
        if lo == "project":
            if ACTIVE_PROJECT:
                print(f"  {C}Active project: {W}{ACTIVE_PROJECT}{X}")
            else:
                print(f"  {W}No active project. Use: project <path>{X}")
            continue

        if lo.startswith("project "):
            proj = os.path.expanduser(cmd[8:].strip())
            if os.path.isdir(proj):
                globals()['ACTIVE_PROJECT'] = proj
                print(f"  {G}✅ Active project: {W}{proj}{X}")
                show_hint("Project context active",
                    "File structure is now injected into AI context.\n"
                    "AI will write paths relative to this project.\n"
                    "Git branch + recent commits also auto-injected.")
                struct = subprocess.run(
                    f"find {proj} -type f | grep -v -E '(node_modules|\\.git|__pycache__)' | head -50",
                    shell=True, capture_output=True, text=True).stdout.strip()
                print(f"  {C}Files:{X}")
                for f in struct.splitlines():
                    print(f"    {W}{f}{X}")
            else:
                print(f"  {R}❌ Directory not found: {proj}{X}")
            continue

        # ── Chunked mode — ARCHIVED 2026-04-19 ───────────────
        # Elijah: "archive chunked — I shouldn't be able to type it in."
        # Handler removed. Scripts still on disk (~/scripts/chunker.sh,
        # chunker-test.sh) for un-archival later. Memory files retain the
        # design concept. Do NOT re-wire without explicit permission.

        # ── MASTER AI SELF-KNOWLEDGE — factual canned responses ───
        # When user types a Master AI term, intercept BEFORE the model
        # can drift into generic textbook explanations. Answers below
        # are hardcoded truth about THIS system, not general knowledge.
        # Matches the "70% hardcoded, 30% AI illusion" principle.
        _self_knowledge = {
            "chunker": f"{BY}🥷 The chunker is ARCHIVED as of 2026-04-19.{X}\n"
                       f"  Files still on disk at ~/scripts/chunker.sh and chunker-test.sh,\n"
                       f"  but no Sensei command, no shell shortcut, no Pupil lesson.\n"
                       f"  UX wasn't settled — shelved until a home is decided.\n"
                       f"  (Memory: project_chunked_workflow.md retains the concept.)",
            "chunk":   f"{BY}Same as 'chunker' — archived. Type 'chunker' for details.{X}",
            "pupil":   f"{C}🥷 Pupil is Master AI's browser UI (menu 5).{X}\n"
                       f"  Lives at http://localhost:8080/pupil.html when stt_server is up.\n"
                       f"  Features: Projects ▾ dropdown, lesson engine (Bash 1-6 + Python 1-6),\n"
                       f"  idle thoughts, RAM bar, belt themes, any-key finder.\n"
                       f"  Role: apprentice/workshop — intake for ideas before they hit Sensei.",
            "dojo":    f"{C}🥷 The dojo = Sensei (this terminal agent).{X}\n"
                       f"  Gated by dojo_gate.sh at menu 4: pick a project + task before entering.\n"
                       f"  Commands: 'dojo tasks' (open list), 'done' (mark + pin next),\n"
                       f"  'project <path>' (scope a directory), 'refresh' (soft reload).",
            "sensei":  f"{C}🥷 Sensei IS this thing — the tmux terminal AI you're talking to.{X}\n"
                       f"  Runs master_ai.py, routes between local models + cloud.\n"
                       f"  Current primary: qwen2.5:7b · fast tier: qwen2.5:3b · vision: llava.",
            "apocalypse mode": f"{C}🥷 Apocalypse Mode:{X} the local-only state of Master AI.\n"
                       f"  When cloud is dead, you rely on the trifecta (3b/7b/llava).\n"
                       f"  Was linked to the chunker (now archived); mechanism being rethought.\n"
                       f"  See memory: project_apocalypse_mode.md",
            "trifecta": f"{C}🥷 The trifecta:{X} qwen2.5:3b (spark) + qwen2.5:7b (brain) + llava (eyes).\n"
                       f"  Total ~11.3 GB disk, fits Elijah's budget ceiling.\n"
                       f"  OLLAMA_MAX_LOADED_MODELS=1 recommended to prevent RAM pressure.",
            "master ai": f"{C}🥷 Master AI{X} is the umbrella brand — NOT a single app.\n"
                       f"  Includes: menu (master.sh), Sensei (master_ai.py), Pupil (pupil.html),\n"
                       f"  Remote (menu 6), TTS (:5050), Ollama runtime (:11434).",
        }
        if lo in _self_knowledge:
            print()
            print(_self_knowledge[lo])
            print()
            continue

        # ── Dojo status / task controls ───────────────────────
        if lo in ("dojo", "status"):
            print()
            if ACTIVE_PROJECT:
                print(f"  {C}🥷 Project:{X} {W}{ACTIVE_PROJECT}{X}")
            else:
                print(f"  {W}🥷 No project pinned (gate was skipped).{X}")
            if ACTIVE_TASK:
                print(f"  {C}🥷 Task:{X}    {W}{ACTIVE_TASK}{X}")
            else:
                print(f"  {W}🥷 No task pinned.{X}")
            print()
            continue

        if lo == "dojo tasks" or lo == "tasks open":
            _tasks = _dojo_unchecked(ACTIVE_PROJECT) if ACTIVE_PROJECT else []
            print()
            if not _tasks:
                print(f"  {W}  no open tasks for {ACTIVE_PROJECT or '(no project)'}{X}")
            else:
                print(f"  {C}Open tasks for {ACTIVE_PROJECT}:{X}")
                for i, t in enumerate(_tasks, 1):
                    mark = "★" if t == ACTIVE_TASK else " "
                    print(f"    {mark} {i}) {t}")
            print()
            continue

        if lo == "done":
            if not ACTIVE_PROJECT or not ACTIVE_TASK:
                print(f"  {W}🥷 nothing pinned to mark done. try `dojo` to see state.{X}")
                continue
            if _dojo_mark_done(ACTIVE_PROJECT, ACTIVE_TASK):
                print(f"  {G}✅ done:{X} {ACTIVE_TASK}")
                # Pick next unchecked task
                nxt = _dojo_next_task(ACTIVE_PROJECT)
                if nxt:
                    globals()['ACTIVE_TASK'] = nxt
                    try: ACTIVE_TASK_FILE.write_text(nxt)
                    except Exception: pass
                    print(f"  {C}🥷 next task:{X} {W}{nxt}{X}")
                else:
                    globals()['ACTIVE_TASK'] = ""
                    try: ACTIVE_TASK_FILE.write_text("")
                    except Exception: pass
                    print(f"  {G}🥷 project complete — no unchecked tasks left.{X}")
            else:
                print(f"  {R}❌ couldn't find that task in PROJECTS.md{X}")
            continue

        # ── Mesh (node-to-node federated routing) ─────────────
        # `mesh`                    → show peer list (same as `mesh ls`)
        # `mesh ls`                 → show peer list
        # `mesh ping`               → ping every peer's /node_info
        # `mesh add`                → shell out to mesh.sh for interactive add
        # `mesh ask <peer> <q...>`  → POST /ask to a peer, get its Ollama's reply
        # Use `self` as the peer name to loopback-test your own /ask pipe.
        if lo == "mesh" or lo.startswith("mesh "):
            rest = cmd[5:].strip() if lo.startswith("mesh ") else ""
            mesh_sh = str(Path.home() / "scripts/mesh.sh")
            try:
                if rest == "" or rest in ("ls", "list"):
                    subprocess.run(["bash", mesh_sh, "ls"], check=False)
                elif rest == "ping":
                    subprocess.run(["bash", mesh_sh, "ping"], check=False)
                elif rest == "add":
                    subprocess.run(["bash", mesh_sh, "add"], check=False)
                elif rest.startswith("ask "):
                    # Split into: peer, prompt-remainder
                    parts = rest[4:].strip().split(None, 1)
                    if len(parts) < 2:
                        print(f"  {W}usage: mesh ask <peer> <prompt...>{X}")
                    else:
                        peer, prompt = parts[0], parts[1]
                        subprocess.run(["bash", mesh_sh, "ask", peer, prompt], check=False)
                else:
                    print(f"  {W}🕸  mesh commands:{X} ls | ping | add | ask <peer> <prompt>")
                    print(f"  {W}   full menu:{X} bash ~/scripts/mesh.sh")
            except Exception as e:
                print(f"  {R}❌ mesh error: {e}{X}")
            continue

        # ── gdrive ────────────────────────────────────────────
        if lo.startswith("gdrive "):
            query = cmd[7:].strip()
            if shutil.which("claude"):
                subprocess.run(["claude", query], check=False)
            else:
                print(f"  {R}❌ Claude CLI not found. Is Claude Code installed?{X}")
            continue

        image_path = None
        user_text = ""

        # ── Download ──────────────────────────────────────────
        if lo.startswith("dl "):
            url = cmd[3:].strip()
            path = download_file(url)
            if path:
                print(f"\n{G}  ✅ Downloaded: {path}{X}\n")
            continue

        # ── Web search ────────────────────────────────────────
        elif lo.startswith("search "):
            q = cmd[7:].strip()
            results = web_search(q)
            print(f"\n{C}  🌐 Results:\n{results}{X}\n")
            threading.Thread(target=speak, args=(f"Here are the search results for {q}",), daemon=True).start()
            continue

        # ── Read URL — pull a page's full markdown via Firecrawl ────
        # Different from `search`: search returns snippets from many pages,
        # `read:` fetches ONE page's full clean content. Prints the markdown
        # inline and saves to history so follow-up questions ("summarize
        # it", "what did it say about X") have real content to work with.
        elif lo.startswith("read ") or lo.startswith("read:"):
            raw = cmd[5:].strip() if lo.startswith("read ") else cmd[5:].strip()
            # Allow `read: http...` too
            if raw.startswith(':'): raw = raw[1:].strip()
            url = raw
            if not url:
                print(f"  {Y}usage: read: <url>{X}")
                continue
            print(f"\n  {C}🔗 Fetching page via Firecrawl...{X}")
            content = firecrawl_fetch(url)
            if content:
                print(f"\n{content}\n")
                history.append({"role": "user", "content": f"read: {url}"})
                history.append({"role": "assistant", "content": content})
            else:
                print(f"  {R}Firecrawl returned nothing.{X}")
            continue

        # ── Image ─────────────────────────────────────────────
        elif lo.startswith("i "):
            candidate = cmd[2:].strip()
            # Only treat as image command if the arg actually looks like a path
            # (contains / or ~ or has an image extension). Otherwise pass through.
            if (os.path.sep in candidate or candidate.startswith("~") or
                candidate.lower().endswith((".png",".jpg",".jpeg",".gif",".webp",".bmp",".svg"))):
                image_path = os.path.expanduser(candidate)
                user_text = input(f"{C}  What about this image? {X}").strip()
                if not user_text:
                    user_text = "Describe this image in detail."
            else:
                # Not an image path — let the message flow to the AI as normal
                user_text = cmd

        # ── Voice: explicit ───────────────────────────────────
        elif lo in ("v", "r"):
            audio = record_audio(5)
            raw = transcribe(audio)
            if not raw:
                print(f"  {Y}🎤 Didn't catch that.{X}")
                continue
            print(f"\n{C}  📝 Heard: {W}{raw}{X}")
            fix = input(f"{Y}  Send? Enter=yes  |  type correction  |  n=cancel: {X}").strip()
            if fix.lower() == 'n':
                continue
            user_text = fix if fix else raw

        # ── Voice: custom duration ────────────────────────────
        elif lo.startswith("r "):
            try:
                secs = int(cmd[2:].strip())
            except Exception:
                secs = 5
            audio = record_audio(secs)
            raw = transcribe(audio)
            if not raw:
                print(f"  {Y}🎤 Didn't catch that.{X}")
                continue
            print(f"\n{C}  📝 Heard: {W}{raw}{X}")
            fix = input(f"{Y}  Send? Enter=yes  |  type correction  |  n=cancel: {X}").strip()
            if fix.lower() == 'n':
                continue
            user_text = fix if fix else raw

        # ── Default: anything else is a direct message ────────
        else:
            user_text = cmd

        if not user_text:
            continue

        # ── Loop mode (loop: prefix) — plan / execute / critique / refine ──
        # Explicit opt-in: `loop: <task>`. Breaks the task into steps, runs
        # each through normal handle() (sandbox stays enforced), asks the AI
        # to critique the result, then decides: continue / retry / done.
        # Capped at 5 cycles and 10 min wall-clock. Ctrl+C aborts cleanly.
        if user_text.lower().startswith("loop:"):
            task = user_text[5:].strip()
            if not task:
                print(f"  {Y}usage: loop: <task in plain language>{X}")
                continue
            try:
                handle_loop_task(task, history)
            except KeyboardInterrupt:
                print(f"\n  {Y}loop interrupted by user{X}")
            continue

        # ── term: prefix — spawn in a NEW graphical terminal window.
        # Short-circuit to confirm_runterm; no model call, no capture, no
        # timeout. For visual/interactive scripts (matrix-rain, htop, vim,
        # anything that needs a real TTY). Companion to RUNTERM: which the
        # model can emit on its own.
        # Tolerate voice-to-text variants: "term:" (canonical), "term "
        # (colon dropped — common phone voice-to-text), "term;" (semicolon
        # mis-transcribed). Not "turn:" — too many English false positives.
        _ut_stripped = user_text.strip()
        _ut_lower = _ut_stripped.lower()
        if (_ut_lower.startswith("term:")
                or _ut_lower.startswith("term;")
                or (_ut_lower.startswith("term ") and len(_ut_stripped.split()) >= 2)):
            cmd = _ut_stripped[5:].lstrip(":; ").strip()
            if not cmd:
                print(f"  {Y}usage: term: <bash command>{X}")
                continue
            confirm_runterm(cmd)
            continue

        # ── Reasoning loop (think: prefix) — Planner/Solver/Critic/Finalizer
        # Pure-text 4-stage pipeline for hard QUESTIONS (not shell tasks).
        # Distinct from loop: — this one doesn't execute commands, just
        # forces the model through structured cognition. See
        # ~/scripts/SENSEI_REASONING_LOOP.md for the design spec.
        #   think: <hard question>            → standard (4 stages)
        #   think fast: <hard question>       → skip critic (3 stages)
        #   think deep: <hard question>       → +refine pass (6 stages)
        if user_text.lower().startswith(("think:", "think fast:", "think deep:")):
            lo_trim = user_text.lower()
            if lo_trim.startswith("think fast:"):
                rl_mode, query = "fast", user_text[11:].strip()
            elif lo_trim.startswith("think deep:"):
                rl_mode, query = "deep", user_text[11:].strip()
            else:
                rl_mode, query = "standard", user_text[6:].strip()
            if not query:
                print(f"  {Y}usage: think: <hard question>   (or think fast: / think deep:){X}")
                continue
            try:
                import sys as _sys, os as _os
                if str(Path.home() / "scripts") not in _sys.path:
                    _sys.path.insert(0, str(Path.home() / "scripts"))
                from sensei_reasoning_loop import run_reasoning_loop
                out = run_reasoning_loop(query, mode=rl_mode, progress=True)
                answer = out.get("answer", "").strip()
                if answer:
                    # Reasoning-loop output is pure text — it MUST NOT feed
                    # the RUN:/CREATE:/EDIT: executor. We deliberately call
                    # render_reply (display only) instead of process_reply
                    # (which parses + executes directives). As belt-and-
                    # suspenders, if the finalizer slipped and emitted a
                    # directive-looking line, neutralize it so a future
                    # refactor can't accidentally auto-run it either.
                    safe_answer = re.sub(
                        r'(?im)^(\s*)(RUN|READ|CREATE|EDIT|THINK|DONE):',
                        r'\1# \2:',
                        answer,
                    )
                    render_reply(safe_answer, prefix=f"\n{M}  🥋{X} ", suffix="")
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": safe_answer})
                    if TTS_ENABLED:
                        threading.Thread(target=speak, args=(safe_answer,), daemon=True).start()
                else:
                    print(f"  {R}reasoning loop produced no answer.{X}")
            except KeyboardInterrupt:
                print(f"\n  {Y}reasoning loop interrupted{X}")
            except Exception as e:
                print(f"  {R}reasoning loop error: {e}{X}")
            continue

        # ── Plan mode — reason first, then draft a plan ───────────────
        # Plan mode is a reasoning assistant, not a command prompter.
        # The model may:
        #   1) Ask clarifying questions → just print the reply (no 1/2/3/4).
        #   2) Discuss trade-offs, think out loud → same.
        #   3) Commit to a numbered plan → end with "<PLAN READY>" marker,
        #      we detect it, store PENDING_PLAN_TEXT, and show 1/2/3/4.
        # Any leaked RUN:/CREATE:/EDIT: directives get softened to prose
        # so Plan mode never pre-commits to specific shell commands. On
        # approval (1 / Enter), the ORIGINAL user_text re-runs in Review
        # mode for per-command execution.
        if MODE == "plan":
            print(f"{C}  thinking (plan mode)...{X}")
            _hist_len_before = len(history)
            # Small local models (3B/7B) follow SHORT prompts better than
            # long ones. Kept to 7 lines of hard rules + one-line input.
            _plan_prompt = (
                "PLAN MODE. Produce a numbered prose plan. NO code blocks, NO bash, "
                "NO directive keywords (the colon-suffixed ones).\n"
                "You MAY ask up to 4 clarifying questions across turns. Assume "
                "Linux Mint + /home/elijah paths unless told otherwise.\n"
                "Read past voice-to-text flips (Lennox→Linux Mint, except→accept, "
                "sensi→Sensei, pants→hints).\n"
                "When the plan is ready, YOU emit the literal line '<PLAN READY>' "
                "on its own line as the final line. Never tell the user to type it.\n"
                "If questions remain, do NOT emit <PLAN READY> — just ask.\n"
                "\n"
                f"User: {user_text}"
            )
            plan_reply = handle(_plan_prompt, history)
            # Drop the planning turn from history so the real execution
            # turn starts with clean context.
            while len(history) > _hist_len_before:
                history.pop()
            # Soften any directives that leaked through into inert prose.
            plan_text = re.sub(
                r'(?im)^(\s*)(RUN|READ|CREATE|EDIT):',
                r'\1(step would) ',
                plan_reply,
            )
            # Detect <PLAN READY> marker — only THEN queue the 1/2/3/4 prompt.
            if re.search(r'<\s*PLAN\s*READY\s*>', plan_text, re.IGNORECASE):
                plan_text_clean = re.sub(
                    r'<\s*PLAN\s*READY\s*>\s*', '', plan_text, flags=re.IGNORECASE
                ).strip()
                globals()['PENDING_PLAN_TEXT'] = plan_text_clean[:1600]
                globals()['PENDING_PLAN_REQUEST'] = user_text
                print(f"\n  {BTN_G} 1){X} accept & execute  ·  {BTN_Y} 2){X} edit  ·  "
                      f"{BTN_R} 3){X} no  ·  {BTN_C} 4){X} keep talking")
                threading.Thread(target=speak, args=("Plan ready.",), daemon=True).start()
            else:
                # Conversational turn — model is still reasoning or asking.
                # Keep history so context carries across turns.
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": plan_text})
            continue

        # ── Check cache ───────────────────────────────────────
        cached = cache_lookup(user_text)
        if cached:
            render_reply(cached, prefix=f"\n{M}  🥋{X} ", suffix=f"  {BTN_C} cached {X}\n")
            threading.Thread(target=speak, args=(cached,), daemon=True).start()
            continue

        # ── Run the query synchronously in the main thread ──
        # (Queue-in-worker-thread approach was reverted in v1.7.11 — it raced
        # with interactive RUN/CREATE/EDIT confirmation prompts for stdin.
        # Type-ahead is worth less than reliable directive confirmations.)
        try:
            reply = handle(user_text, history, image_path=image_path)
            reply = sanitize(reply) if reply else reply
            cache_store(user_text, reply)
            if TTS_ENABLED:
                threading.Thread(target=speak, args=(reply,), daemon=True).start()
            globals()['CHARS_SINCE_SAVE'] = CHARS_SINCE_SAVE + len(user_text) + len(reply or "")
            if CHARS_SINCE_SAVE >= AUTO_SAVE_THRESHOLD:
                threading.Thread(target=_auto_save_background, args=(list(history),), daemon=True).start()
            # ── Drift reminder: keyword-based. After ~3000 chars of activity,
            #    only fire if the recent user messages DO NOT touch the
            #    project keywords (thread label tokens + active task words).
            #    Saves money: no reminder if we're still on topic.
            globals()['CHARS_SINCE_REMIND'] = CHARS_SINCE_REMIND + len(user_text) + len(reply or "")
            if CHARS_SINCE_REMIND >= DRIFT_REMINDER_CHARS:
                try:
                    _maybe_drift_reminder(history)
                except Exception as _e:
                    log(f"DRIFT_REMINDER_ERROR: {_e}")
                globals()['CHARS_SINCE_REMIND'] = 0
        except Exception as e:
            log(f"HANDLE_ERROR: {e}")
            print(f"  {R}error: {e}{X}")

def _run_with_tui():
    """Wrap main() in the full-screen SenseiApp.
    - Stdout/stderr routed to the app's scrollable output buffer.
    - builtins.input() pulls from a submit queue filled by the TUI's Enter key.
    - main() runs in a daemon worker thread; the app owns the main thread.
    """
    import builtins, queue
    from sensei_tui import TUIStdout

    _iq: queue.Queue[str] = queue.Queue()
    _orig_input = builtins.input
    _orig_stdout, _orig_stderr = sys.stdout, sys.stderr

    def _tui_input(prompt=""):
        # Print the prompt into the scrollback so user sees what's being asked.
        if prompt:
            try: sys.stdout.write(prompt); sys.stdout.flush()
            except Exception: pass
        # Two-channel stdin (2026-04-21): if a confirm prompt is active, pull
        # from the confirm queue. Otherwise pull from the normal typing queue.
        # Keeps type-ahead of the next question from being stolen as a
        # 1/2/3/4 answer to the current confirm.
        q = _CONFIRM_IQ if _AWAITING_CONFIRM.is_set() else _iq
        return q.get()

    builtins.input = _tui_input
    sys.stdout = TUIStdout(_SENSEI_APP, _orig_stdout)
    sys.stderr = TUIStdout(_SENSEI_APP, _orig_stderr)

    def _on_submit(text: str):
        # Route to the confirm queue only while a confirm is actively waiting.
        # Otherwise this is a normal user question — goes in the type-ahead queue.
        if _AWAITING_CONFIRM.is_set():
            _CONFIRM_IQ.put(text)
        else:
            _iq.put(text)

    # Single-keystroke confirms (2026-04-21) — when a confirm prompt is open
    # AND the input field is empty, pressing 1-5 fires that option immediately
    # without needing Enter. Outside of confirms, numbers type normally.
    try:
        _SENSEI_APP.enable_number_confirm(
            check_fn=lambda: _AWAITING_CONFIRM.is_set(),
            submit_fn=lambda d: _CONFIRM_IQ.put(d),
        )
    except Exception:
        # Older sensei_tui.py without enable_number_confirm — silently skip.
        pass

    worker_err = []

    def _worker():
        try:
            main()
        except SystemExit as e:
            worker_err.append(e)
        except BaseException as e:
            worker_err.append(e)
            # Log the traceback to the crash log so we can diagnose silent exits.
            try:
                import traceback
                with open(Path.home() / "scripts" / "master.crash.log", "a") as _cl:
                    _cl.write(f"\n[{datetime.now().isoformat()}] TUI worker crashed:\n")
                    traceback.print_exc(file=_cl)
            except Exception:
                pass
        finally:
            try: _SENSEI_APP.exit()
            except Exception: pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    try:
        _SENSEI_APP.run(on_submit=_on_submit)
    finally:
        sys.stdout = _orig_stdout
        sys.stderr = _orig_stderr
        builtins.input = _orig_input

    if worker_err and isinstance(worker_err[0], SystemExit):
        sys.exit(worker_err[0].code)


if __name__ == "__main__":
    if _SENSEI_ENABLED and _SENSEI_APP is not None:
        _run_with_tui()
    else:
        main()
