#!/usr/bin/env python3
# ============================================================
# MASTER AI — AI Agent · Vision · Voice · Web · PC Control
# Machine: Madam-Mary | User: Elijah
# Run: python3 ~/scripts/master_ai.py
# ============================================================

import os, sys, json, subprocess, tempfile, urllib.request, urllib.error
import base64, re, time, shutil, hashlib, platform, atexit, signal, threading
from datetime import datetime
from pathlib import Path

try:
    import readline
    _HIST = str(Path.home() / '.master_ai_history')
    try: readline.read_history_file(_HIST)
    except FileNotFoundError: pass
    readline.set_history_length(500)
    atexit.register(readline.write_history_file, _HIST)

    _COMPLETIONS = [
        "hub", "menu", "home", "help", "tips", "model", "model auto", "mode safe", "mode plan", "mode auto",
        "mode", "memory", "remember:", "forget:", "task", "task add ", "task list",
        "task done ", "task clear", "tasks", "save session", "load summary",
        "load session", "clear", "clear history", "clear cache", "clear approved", "clear chats",
        "chats", "refresh", "reload", "restart", "kick",
        "up", "down", "top", "bottom", "last",
        "projects", "apps", "autotips", "slideshow", "tour",
        "keys", "approved", "cache", "perms", "tutorial", "hints on", "hints off",
        "tts on", "tts off", "tts",
        "hints", "project", "search ", "dl ", "gdrive ", "git", "git status",
        "git diff", "git log", "git commit ", "go", "cancel", "accessibility", "x",
    ]
    def _completer(text, state):
        matches = [c for c in _COMPLETIONS if c.startswith(text)]
        return matches[state] if state < len(matches) else None
    readline.set_completer(_completer)
    readline.parse_and_bind("tab: complete")
except ImportError:
    pass

# ── CONFIG ───────────────────────────────────────────────────
KEYS_FILE     = Path.home() / ".master_ai_keys"
CHATS_DIR     = Path.home() / ".master_ai_chats"
MEMORY_FILE   = Path.home() / ".master_ai_memory"
TASKS_FILE    = Path.home() / ".master_ai_tasks"
APPROVED_FILE = Path.home() / ".master_ai_approved"
PERMS_FILE    = Path.home() / ".master_ai_permissions_done"
CACHE_FILE    = Path.home() / ".master_ai_cache.json"
HINTS_FILE    = Path.home() / ".master_ai_hints_off"
TUTORIAL_FILE = Path.home() / ".master_ai_tutorial_done"
OLLAMA_URL    = "http://localhost:11434"
PIPER_MODEL   = Path.home() / "scripts/voices/en_US-lessac-medium.onnx"
LOG_FILE      = Path.home() / "scripts/master.log"
WHISPER_MODEL = "base"

# ── MODE / PLAN STATE ────────────────────────────────────────
MODE                 = "safe"
PENDING_PLAN_TEXT    = ""
PENDING_PLAN_REQUEST = ""
HINTS                = 0 if Path.home().joinpath(".master_ai_hints_off").exists() else 1
ACTIVE_PROJECT       = ""
_SETTINGS            = Path.home() / ".master_ai_settings"
TTS_ENABLED          = "TTS_OFF" not in (_SETTINGS.read_text() if _SETTINGS.exists() else "")

MODELS = {
    "master":  "master-ai",        # qwen2.5:14b base — general, agent loop
    "vision":  "llava",            # pure vision / image analysis
    "coder":   "qwen2.5-coder:7b", # dedicated code model (faster, specialized)
    "general": "master-ai",        # 14b for general queries
    "qwen3":   "qwen3.5:cloud",    # 397B cloud — complex analysis
    "kimi":    "kimi-k2.5:cloud",  # 1T cloud — vision + deep reasoning
}

# All models with labels for the picker menu
MODEL_MENU = [
    # ── LOCAL (your machine — private, free, no token limit) ──
    ("master-ai",          "LOCAL  · 14B · general AI · code · voice · agent loop"),
    ("llava",              "LOCAL  · vision · image analysis"),
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
AUTO_SAVE_THRESHOLD = 3000        # update session file every ~3000 chars
SESSION_TS          = int(time.time())  # fixed for entire session — overwrites same file
_SAVE_LOCK          = threading.Lock()

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
BC   = '\033[1;34m'  # bold blue  — banner
BG   = '\033[1;32m'  # bold green — banner accent
BW   = '\033[97m'    # bright white — banner labels
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
VISION_WORDS  = {"image","photo","picture","see","show","look","describe","what is this",
                 "analyze this","read this","whats in"}
WEB_WORDS     = {"latest","today","current","news","search","find","download","who is",
                 "what is happening","price","weather","2024","2025","2026","recently"}
COMPLEX_WORDS = {"explain","analyze","compare","difference","pros","cons","plan","strategy",
                 "why","how does","what causes","in depth","detailed","thorough","research",
                 "summarize","write a report","essay","deep dive"}
REASONING_WORDS = {"think","reason","logic","proof","math","calculate","step by step",
                   "walk me through","figure out","solve","puzzle","hypothesis"}

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
        return "vision", MODELS["kimi"], "vision → kimi-k2.5 (1T)"
    if words & CODE_WORDS:
        return "local", MODELS["coder"], "code → qwen2.5-coder"
    if words & WEB_WORDS:
        return "web", None, "web → Gemini + search"
    if any(w in t for w in REASONING_WORDS):
        return "cloud", "deepseek-r1", "reasoning → DeepSeek R1"
    if words & COMPLEX_WORDS:
        return "local", MODELS["qwen3"], "complex → qwen3.5:cloud (397B)"
    return "local", MODELS["master"], "general → master-ai"

# ── WEB SEARCH ───────────────────────────────────────────────
def web_search(query, max_results=4):
    log(f"WEB_SEARCH: {query}")
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "No results found."
        return "\n".join(f"• {r.get('title','')}: {r.get('body','')[:200]}"
                         for r in results)
    except Exception as e:
        log(f"SEARCH_ERROR: {e}")
        return f"Search unavailable: {e}"

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
    payload = {"model": model, "messages": messages, "stream": False}
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
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read())
            return result["message"]["content"]
    except Exception as e:
        log(f"OLLAMA_ERROR: {e}")
        return None

# ── LOCAL AI STREAMING ───────────────────────────────────────
def ask_local_stream(messages, model=None, image_path=None):
    """Stream tokens from Ollama directly to terminal. Returns full text."""
    model = model or MODELS["master"]
    log(f"LOCAL_STREAM [{model}]")
    payload = {"model": model, "messages": messages, "stream": True}
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
        print(f"\n{M}  AI:{X} ", end="", flush=True)
        full_text = []
        with urllib.request.urlopen(req, timeout=90) as resp:
            for line in resp:
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line.decode())
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        print(token, end="", flush=True)
                        full_text.append(token)
                    if chunk.get("done"):
                        break
                except Exception:
                    pass
        print(f"\n", flush=True)
        result = "".join(full_text)
        return result if result else None
    except Exception as e:
        print(flush=True)
        log(f"STREAM_ERROR: {e}")
        return None

# ── CLOUD PROGRESS INDICATOR ─────────────────────────────────
def cloud_thinking_start():
    """Start animated dots on same line. Returns (stop_event, thread)."""
    stop = threading.Event()
    def _spin():
        dots = 0
        while not stop.is_set():
            d = '.' * (dots % 3 + 1)
            print(f"\r{C}  ⏳ thinking {d:<3}{X}", end="", flush=True)
            dots += 1
            stop.wait(0.4)  # interruptible sleep — exits within 0.4s of stop
        print(f"\r{' '*28}\r", end="", flush=True)
    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    return stop, t

def cloud_thinking_stop(state):
    if not state:
        return
    stop_event, thread = state if isinstance(state, tuple) else (state, None)
    stop_event.set()
    if thread:
        thread.join(timeout=1.0)  # wait for spinner to fully clear before returning

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
    r = fn_map.get(provider, ask_cloud_groq)(messages)
    if r:
        return r
    # Full fallback chain — biggest/best first, fastest last
    for fn in [ask_cloud_openrouter_405b, ask_cloud_openrouter_r1,
               ask_cloud_groq, ask_cloud_openrouter_nemotron,
               ask_cloud_openrouter_gptoss, ask_cloud_gemini, ask_cloud_openrouter]:
        r = fn(messages)
        if r:
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
    text = re.sub(r'(RUN:|READ:|CREATE:|EDIT:|THINK:|DONE:)\s*\S+.*', '', text).strip()
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
    """Render AI reply as markdown (tables, code blocks, lists, bold) via rich
    when available. Falls back to plain colored print."""
    if prefix:
        print(prefix, end="", flush=True)
    if _RICH_OK:
        try:
            _RICH_CONSOLE.print(_RichMarkdown(text or "", code_theme="monokai"))
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
    print(f"  {W}type {Y}hints off{W} to disable tips{X}\n")

# ── MODE HELPERS ──────────────────────────────────────────────
def mode_label():
    global MODE
    labels = {"safe": f"{G}SAFE{X}", "plan": f"{Y}PLAN{X}", "auto": f"{R}AUTO{X}"}
    return labels.get(MODE, MODE.upper())

def show_plan_demo():
    os.system("clear")
    steps = [
        (f"{Y}STEP 1{X} — Switch to plan mode",
         f"  {C}🥷{X}  {W}mode plan{X}",
         f"  {G}✅ Mode: PLAN — AI shows plan first, 'go' to run{X}"),
        (f"{Y}STEP 2{X} — Ask AI to do something",
         f"  {C}🥷{X}  {W}check my disk space and show free memory{X}",
         f"  {M}  AI:{X} {C}Here is my plan:\n"
         f"         1. Run: df -h\n"
         f"         2. Run: free -h\n"
         f"  {Y}  Type 'go' to execute or 'cancel' to clear.{X}"),
        (f"{Y}STEP 3{X} — Type 'go' to run it",
         f"  {C}🥷{X}  {W}go{X}",
         f"  {W}  Pending plan: check my disk space and show free memory{X}\n"
         f"  {C}  Execute plan? (y/N):{X}  {W}y{X}"),
        (f"{Y}STEP 4{X} — AI runs the commands",
         f"  {M}  AI:{X} {C}RUN: df -h{X}",
         f"  {G}  Filesystem  Size  Used  Avail\n"
         f"  /dev/sda1   232G  121G   99G   56%{X}\n"
         f"  {M}  AI:{X} {C}RUN: free -h{X}\n"
         f"  {G}  Mem: 32G used: 12G free: 18G{X}"),
        (f"{Y}OTHER OPTIONS{X}",
         f"  {W}cancel{X}        — discard the plan, start over",
         f"  {W}mode safe{X}     — go back to default (asks per command)\n"
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
    print(f"  {C}Switch back to safe mode anytime:{X}  {W}mode safe{X}\n")

def show_mode_status():
    global MODE
    descs = {
        "safe": "asks before every command (default)",
        "plan": "AI plans first — type 'go' to execute",
        "auto": "commands run without asking",
    }
    anims = {"safe": (_A_SAFE, G), "plan": (_A_PLAN, Y), "auto": (_A_AUTO, R)}
    frames, color = anims.get(MODE, (_A_SAFE, G))
    play_anim(frames, delay=0.12, color=color)
    print(f"  {C}Mode: {mode_label()}  —  {descs.get(MODE,'')}{X}\n")

# ── TUTORIAL ─────────────────────────────────────────────────
def run_tutorial():
    STEPS = [
        ("Welcome to Master AI",
         "I'm an AI agent that runs directly on this PC.\nI can execute commands, write files, search the web, and more.\nJust type what you need — in plain English."),
        ("How to talk to me",
         "Type any request and press Enter.\nExamples:\n  List files in my home folder\n  Install ffmpeg\n  Write a Python script that renames files\n  What is my IP address?"),
        ("Modes: safe / plan / auto",
         "mode safe  → I ask before every command (default)\nmode plan  → I show you a plan first, you type 'go' to run it\nmode auto  → I run commands without asking (use with care)"),
        ("Memory",
         "remember: I prefer dark mode\n  → teaches me a fact to keep across sessions\nforget: dark mode\n  → removes matching facts\nmemory\n  → shows all stored facts"),
        ("Voice Input",
         "Type 'v' and press Enter to record your voice.\nI'll transcribe and send it.\nType 'r 10' to record for 10 seconds."),
        ("Projects",
         "project ~/myapp\n  → sets the active project; I'll scan the file structure\n  → all my commands will run relative to that directory"),
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
# Pulled from how-we-work memory: RustDesk constraints, mobile-first,
# multi-layer recovery, adaptive input, persistence. Shown as help-row
# format (yellow cmd, cyan desc) matching show_help().
_IDLE_TIPS = [
    # Core navigation
    ("hub",              "18-action control panel"),
    ("help",             "8-slide command reference"),
    ("projects",         "your apps + Tailscale URLs"),
    # Memory + context
    ("remember: <fact>", "persists across sessions"),
    ("memory",           "view all stored facts"),
    ("forget: <word>",   "remove matching facts"),
    # Models + modes
    ("model",            "pick 1 of 11 AIs (local + cloud)"),
    ("mode plan",        "AI plans first, 'go' to run"),
    ("last",             "re-print last AI reply inline"),
    # Recovery (multi-layer, from how-we-work)
    ("refresh",          "soft-restart if screen glitches"),
    ("kick",             "supervisor respawn if stuck"),
    ("master_ai_kick.sh","external full tmux rebuild"),
    # Mobile / RustDesk constraints
    ("n / b / q",        "use letter keys, not arrows"),
    ("avoid Esc",        "closes RustDesk — use q"),
    ("drag-select",      "copies to phone clipboard"),
    # Persistence (mobile-critical)
    ("auto-save",        "every ~3000 chars typed"),
    ("tmux persistent",  "session survives SSH drop"),
    # Tasks
    ("task add <text>",  "add a new task to your list"),
    ("tasks",            "show tasks + status"),
    # Git shortcuts
    ("git",              "status + last 5 commits"),
    ("git diff",         "diff stat vs HEAD"),
    ("git commit <msg>", "stage all + commit now"),
    # AI file actions (directives the AI emits inside replies)
    ("RUN: <cmd>",       "AI runs a shell command"),
    ("READ: <path>",     "AI reads a file into context"),
    ("CREATE: / EDIT:",  "AI creates or edits files"),
    # Sessions + comfort
    ("save session",     "archive now + summary"),
    ("tts on",           "replies spoken aloud"),
]
_IDLE_STOP = threading.Event()
_IDLE_THREAD = None
_IDLE_IDX = 0

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
    GRACE_SEC = 15.0
    ROTATE_SEC = 5.0
    last_rotate = 0.0

    def _buffer_has_text():
        try:
            import readline as _rl
            return bool(_rl.get_line_buffer().strip())
        except Exception:
            return False

    while not _IDLE_STOP.is_set():
        if _buffer_has_text():
            # User is composing — wipe tip, reset the idle counter
            if tip_on_screen:
                try:
                    sys.stdout.write("\x1b[s\x1b[1A\r\x1b[2K\x1b[u")
                    sys.stdout.flush()
                except Exception: pass
                tip_on_screen = False
            idle_since = time.time()   # whenever they clear the line, 15s starts fresh
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
                desc_trim = desc[: max(0, cols - 6 - 14 - 1)]
                sys.stdout.write("\x1b[s\x1b[1A\r\x1b[2K")
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
            "'mode safe' → ask before every command (default)",
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
            "tailscale": "http://100.101.249.96:8080/master_ai.html  (phone/remote)",
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
def show_help():
    """Paginated help. Returns None if user quit, or a string if user
    typed a question mid-help (caller should treat it as a new message)."""
    sections = [
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
            ("mode safe",            "ask before every command (default)"),
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
            ("x",                    "exit Master AI"),
        ]),
    ]

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
    row("mode safe",       "default — AI asks before running commands")
    row("mode plan",       "AI shows a plan first, you type 'go' to run")
    row("mode auto",       "commands run instantly, no prompts (careful!)")
    row("go / cancel",     "execute or discard a pending plan")
    blank()

    section("MODEL ROUTING  (what runs what)")
    blank()
    row("General talk",    "→ master-ai (14B local, fast)")
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

# ── RUN COMMAND ───────────────────────────────────────────────
def run_command(cmd):
    print(f"\n🥷  {BOLD}Running:{X} {Y}{cmd}{X}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        output = (result.stdout + result.stderr).strip()
        if output:
            print(f"{G}{output}{X}")
        if result.returncode == 0:
            print(f"{G}  ✅ Done.{X}")
        else:
            print(f"{R}  ❌ Exit code: {result.returncode}{X}")
        log(f"PC_CMD: {cmd}")
        return output
    except subprocess.TimeoutExpired:
        print(f"{R}  ❌ Command timed out.{X}")
        return "timeout"
    except Exception as e:
        print(f"{R}  ❌ Error: {e}{X}")
        return str(e)

# ── 4-OPTION CONFIRM ─────────────────────────────────────────
def confirm_run(cmd):
    if is_blocked(cmd):
        print(f"{R}  🚫 BLOCKED — dangerous command refused.{X}")
        log(f"BLOCKED: {cmd}")
        return None

    if cmd in load_approved():
        print(f"{C}  ⚡ Auto-approved: {Y}{cmd}{X}")
        return run_command(cmd)

    print(f"\n{D}╔══════════════════════════════════════════════════════╗{X}")
    print(f"{D}║  🥷 {BOLD}AI wants to run:{X}")
    print(f"{D}║  {Y}  {cmd}{X}")
    print(f"{D}╠══════════════════════════════════════════════════════╣{X}")
    print(f"{D}║  {BTN_G} 1) Yes     — run once          {X}")
    print(f"{D}║  {BTN_C} 2) Always  — never ask again  {X}")
    print(f"{D}║  {BTN_R} 3) No      — skip              {X}")
    print(f"{D}║  {BTN_Y} 4) Edit    — modify before run {X}")
    print(f"{D}╚══════════════════════════════════════════════════════╝{X}")
    choice = input(f"  {BOLD}Choose (1/2/3/4): {X}").strip()

    if choice == '1':
        return run_command(cmd)
    elif choice == '2':
        save_approved(cmd)
        print(f"{G}  ✅ Added to approved list.{X}")
        return run_command(cmd)
    elif choice == '4':
        try:
            edited = input(f"{C}  Edit command: {X}").strip() or cmd
        except Exception:
            edited = cmd
        if is_blocked(edited):
            print(f"{R}  🚫 BLOCKED.{X}")
            return None
        return run_command(edited)
    else:
        print(f"{Y}  ⏭  Skipped.{X}")
        return None

# ── FILE CREATE CONFIRM ───────────────────────────────────────
def confirm_create(filepath, content):
    filepath = os.path.expanduser(filepath)
    line_count = content.count('\n') + 1
    print(f"\n{D}╔══════════════════════════════════════════════════════╗{X}")
    print(f"{D}║  🥷 {BOLD}AI wants to create:{X}")
    print(f"{D}║  {Y}  {filepath}{X}")
    print(f"{D}║  {C}  {line_count} lines{X}")
    print(f"{D}╠══════════════════════════════════════════════════════╣{X}")
    print(f"{D}║  {BTN_G} 1) Create   — write file         {X}")
    print(f"{D}║  {BTN_C} 2) Review   — view content first {X}")
    print(f"{D}║  {BTN_R} 3) No       — skip               {X}")
    print(f"{D}╚══════════════════════════════════════════════════════╝{X}")
    choice = input(f"  {BOLD}Choose (1/2/3): {X}").strip()

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
            print(f"{G}  ✅ Created: {W}{filepath}{X}")
            log(f"PC_CREATE: {filepath}")
        except Exception as e:
            print(f"{R}  ❌ Create failed: {e}{X}")
    else:
        print(f"{Y}  ⏭  Skipped.{X}")

# ── FILE EDIT CONFIRM ────────────────────────────────────────
def confirm_edit(filepath, find_text, replace_text):
    filepath = os.path.expanduser(filepath)
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

    preview_old = find_text.strip()[:120]
    preview_new = replace_text.strip()[:120]
    print(f"\n{D}╔══════════════════════════════════════════════════════╗{X}")
    print(f"{D}║  🥷 {BOLD}AI wants to edit:{X} {Y}{os.path.basename(filepath)}{X}")
    print(f"{D}╠══════════════════════════════════════════════════════╣{X}")
    print(f"{D}║  {R}— {preview_old}{X}")
    print(f"{D}║  {G}+ {preview_new}{X}")
    print(f"{D}╠══════════════════════════════════════════════════════╣{X}")
    print(f"{D}║  {BTN_G} 1) Apply     — make the edit          {X}")
    print(f"{D}║  {BTN_R} 2) No        — skip                   {X}")
    print(f"{D}╚══════════════════════════════════════════════════════╝{X}")
    choice = input(f"  {BOLD}Choose (1/2): {X}").strip()
    if choice == '1':
        new_content = content.replace(find_text, replace_text, 1)
        try:
            Path(filepath).write_text(new_content)
            print(f"{G}  ✅ Edited: {W}{filepath}{X}")
            log(f"PC_EDIT: {filepath}")
        except Exception as e:
            print(f"{R}  ❌ Edit failed: {e}{X}")
    else:
        print(f"{Y}  ⏭  Skipped.{X}")

# ── REPLY PROCESSOR ──────────────────────────────────────────
def process_reply(reply, history, streamed=False):
    """Parse RUN: / READ: / CREATE: directives from AI reply and execute."""
    lines = reply.splitlines()

    read_paths = [l.split('READ:', 1)[1].strip()
                  for l in lines if re.match(r'^\s*READ:', l, re.IGNORECASE)]
    run_cmds   = [l.split('RUN:', 1)[1].strip()
                  for l in lines if re.match(r'^\s*RUN:', l, re.IGNORECASE)]

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

    has_directives = bool(read_paths or run_cmds or create_files or edit_ops)

    # Print non-directive narrative text
    skip_prefixes = ('run:', 'read:', 'create:', 'edit:', '<<<content', '>>>content',
                     '<<<find', '>>>find', '<<<replace', '>>>replace')
    narrative = '\n'.join(
        l for l in lines
        if not any(l.strip().lower().startswith(p) for p in skip_prefixes)
    ).strip()

    if narrative and not streamed:
        render_reply(narrative, prefix=f"\n{M}  AI:{X} ", suffix="")
    elif not has_directives and not streamed:
        render_reply(reply, prefix=f"\n{M}  AI:{X} ", suffix="")

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

    # RUN: — execute with permission
    for cmd in run_cmds:
        confirm_run(cmd)

    # CREATE: — write files with permission
    for filepath, content in create_files:
        confirm_create(filepath, content)

    # EDIT: — targeted find-and-replace in existing files
    for filepath, find_text, replace_text in edit_ops:
        confirm_edit(filepath, find_text, replace_text)

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

    # Ollama
    try:
        with urllib.request.urlopen(
                urllib.request.Request(f"{OLLAMA_URL}/api/tags"), timeout=3):
            pass
        print(f"  {G}✅ Ollama       {C}running at {OLLAMA_URL}{X}")
    except (Exception, KeyboardInterrupt):
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
    def _count(f):
        try:
            return len([l for l in f.read_text().splitlines() if l.strip()])
        except Exception:
            return 0
    mem = _count(MEMORY_FILE)
    tasks = active_task_count()
    has_cloud = any(KEYS.get(k) for k in ['anthropic', 'deepseek', 'gemini', 'groq', 'openai', 'openrouter'])
    model_label = PINNED_MODEL if PINNED_MODEL else ("AUTO+CLOUD" if has_cloud else "AUTO")
    cols = shutil.get_terminal_size().columns
    task_part = f"  │  TASKS:{tasks}" if tasks else ""
    content = f" 🥷 MASTER AI  │  MEM:{mem}{task_part}  │  MODEL:{model_label}  │  MODE:{MODE.upper()}  │  x=exit "
    display_len = len(content) + 1  # 🥷 emoji is 2 display cols, len() counts 1
    pad = max(0, cols - display_len)
    # Truncate if still too wide (narrow terminals)
    if display_len > cols:
        content = content[:cols - 2] + " "
        pad = 0
    print(f"\n\033[42m\033[30m{content}{' ' * pad}\033[0m\n")

# ── MAIN HANDLER ─────────────────────────────────────────────
def handle(user_text, history, image_path=None):
    route, model, reason = detect_route(user_text, has_image=bool(image_path))
    log(f"ROUTE: {route} | {reason}")

    # Build system prompt with current memory + context
    memory_content = load_memory()
    how_we_work = ""
    try:
        hww_path = Path.home() / "scripts" / "howwework.txt"
        full_hww = hww_path.read_text()
        # Cloud gets full context; local skips howwework to keep TTFT fast on 14B CPU model
        how_we_work = full_hww if route in ("cloud", "web") else ""
    except Exception:
        pass
    os_info = subprocess.run(
        "lsb_release -d | cut -f2", shell=True,
        capture_output=True, text=True, timeout=3).stdout.strip() or "Linux/Ubuntu"
    arch = platform.machine()
    git_ctx = git_context()
    project_ctx = f"\n[ACTIVE PROJECT]\n{ACTIVE_PROJECT}" if ACTIVE_PROJECT else ""
    git_block = f"\n\n{git_ctx}" if git_ctx else ""

    LOCAL_SYSTEM = (
        f"You are Master AI on Madam-Mary ({os_info}). "
        "Execute tasks using RUN:/READ:/CREATE:/EDIT: directives. "
        "Do the task immediately — no explanations. "
        "NEVER emit: rm -rf / | mkfs | dd if=\n\n"
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
        "RUN: <bash command>\n"
        "READ: <filepath>\n"
        "CREATE: <filepath>\n<<<CONTENT\n<content>\n>>>CONTENT\n"
        "EDIT: <filepath>\n<<<FIND\n<text>\n>>>FIND\n<<<REPLACE\n<text>\n>>>REPLACE\n\n"
        "Rules: DO the task. One [PLAN] line for multi-step. [DONE] when complete. "
        "READ before editing. Full working code. No placeholders.\n\n"
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
    # For local: prepend active task context to user message (tiny — keeps Modelfile prefix stable)
    local_prefix = f"[Task: {ACTIVE_PROJECT[:80]}] " if (route in ("local", "vision") and ACTIVE_PROJECT) else ""
    history.append({"role": "user", "content": local_prefix + user_text + (inject_ctx or "")})

    streamed = False

    if route == "web":
        search_results = web_search(user_text)
        augmented = history[:-1] + [{
            "role": "user",
            "content": f"{user_text}\n\n[Web search results]\n{search_results}"
        }]
        _spin = cloud_thinking_start()
        reply = ask_cloud(augmented, provider="gemini") or ask_cloud(augmented, provider="groq") or ask_local(augmented)
        cloud_thinking_stop(_spin)

    elif route == "cloud":
        _spin = cloud_thinking_start()
        reply = ask_cloud(history, provider=model) or ask_local(history)
        cloud_thinking_stop(_spin)

    elif route == "vision":
        print(f"{D}  [kimi-k2.5:cloud — vision]{X}")
        reply = ask_local_stream(history, model=MODELS["kimi"], image_path=image_path)
        if not reply:
            reply = ask_local_stream(history, model=MODELS["master"], image_path=image_path)
        if not reply:
            _spin = cloud_thinking_start()
            reply = ask_cloud(history, provider="gemini") or ask_cloud(history, provider="groq")
            cloud_thinking_stop(_spin)
            streamed = False
        else:
            streamed = True

    else:
        reply = ask_local_stream(history, model=model)
        if not reply:
            print(f"{D}  [local timeout — falling back to cloud]{X}")
            _spin = cloud_thinking_start()
            reply = ask_cloud(history, provider="groq") or ask_cloud(history, provider="hermes-405b")
            cloud_thinking_stop(_spin)
        else:
            streamed = True

    if not reply:
        reply = "No response from AI."

    result = process_reply(reply, history, streamed=streamed)

    # READ: was triggered — re-ask with injected file content
    if result is None:
        if route in ("cloud", "web"):
            _spin2 = cloud_thinking_start()
            reply2 = ask_cloud(history)
            cloud_thinking_stop(_spin2)
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
    os.system('clear')
    log("=== MASTER AI STARTED ===")

    # Permissions wizard — first time only (type 'perms' to replay)
    if not PERMS_FILE.exists():
        permissions_wizard()
        PERMS_FILE.touch()

    startup_check()

    # ── Collect boot status silently (no heavy output yet) ────────
    has_cloud = any(KEYS.get(k) for k in ['anthropic', 'deepseek', 'gemini', 'groq', 'openai', 'openrouter'])
    mem_count = 0
    try:
        mem_count = len([l for l in MEMORY_FILE.read_text().splitlines() if l.strip()])
    except Exception:
        pass
    cloud_status = f"ACTIVE ({sum(1 for k in ['groq','gemini','openrouter'] if KEYS.get(k))} cloud providers)" if has_cloud else "LOCAL ONLY"

    # ── Clear screen so banner is always at TOP of the visible pane ─
    # This runs on EVERY startup: first launch, refresh, kick, supervisor auto-respawn
    os.system('clear')

    # ── Use the SAME banner as master.sh main menu (brand.sh banner_master_ai) ─
    try:
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

    # ── Auto-restore last session into context ─────────────────
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
    signal.signal(signal.SIGTERM, _exit_save)
    signal.signal(signal.SIGHUP, _exit_save)   # fires when terminal window closes

    while True:
        draw_status_bar()
        # Persistent legend — always visible right above the prompt
        print(f"{BC}  hub{X} · {BC}help{X} · {BC}tips{X} · {BC}model{X} · {BC}mode plan{X} · {BC}chats{X} · {BC}tts{X} · {BC}x{X}=exit")
        # Idle thought-cloud DISABLED — its cursor save/restore raced with
        # readline and caused typed text to disappear/truncate.
        # start_idle_tips()
        try:
            cmd = sanitize(input(f"🥷  "))
        except KeyboardInterrupt:
            # stop_idle_tips()
            save_session(history, silent=True)
            break
        # finally:
        #     stop_idle_tips()

        if not cmd:
            continue

        lo = cmd.lower()

        # ── Exit ──────────────────────────────────────────────
        if lo == "x":
            save_session(history)
            play_anim(_A_VANISH, delay=0.12, color=BC)
            print(f"{G}  Goodbye.\n{X}")
            log("=== MASTER AI STOPPED ===")
            break

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

        # ── Mode ──────────────────────────────────────────────
        if lo in ("mode safe", "mode plan", "mode auto"):
            globals()['MODE'] = lo.split()[1]
            show_mode_status()
            if lo == "mode plan":
                show_hint("Plan Mode",
                    "Describe your task — I'll show a plan.\n"
                    "Type 'go' to execute it, or 'cancel' to clear.")
            elif lo == "mode auto":
                show_hint("Auto Mode — commands run without asking",
                    "All RUN: directives execute immediately.\n"
                    "Type 'mode safe' to go back to confirmed execution.")
            continue
        if lo == "mode":
            show_mode_status()
            continue

        # ── Plan demo ─────────────────────────────────────────
        if lo in ("plan demo", "demo plan", "how plan", "plan help"):
            show_plan_demo()
            continue

        # ── Plan mode: go / cancel ─────────────────────────────
        if lo in ("go", "proceed", "execute", "go ahead"):
            if not PENDING_PLAN_TEXT:
                print(f"  {Y}No pending plan. Use 'mode plan' then describe your task.{X}")
            else:
                print(f"\n{Y}  ▶ Plan:{X}  {W}{PENDING_PLAN_TEXT}{X}")
                print(f"  {D}Type 'yes' to run it, or 'no' / 'cancel' to keep/clear it.{X}")
                conf = input(f"  {C}Run plan? (yes/no): {X}").strip().lower()
                if conf in ('y', 'yes'):
                    saved_mode = globals()['MODE']
                    globals()['MODE'] = "safe"
                    reply = handle(PENDING_PLAN_REQUEST, history)
                    globals()['MODE'] = saved_mode
                    globals()['PENDING_PLAN_TEXT'] = ""
                    globals()['PENDING_PLAN_REQUEST'] = ""
                    if TTS_ENABLED:
                        threading.Thread(target=speak, args=(reply,), daemon=True).start()
                else:
                    print(f"  {Y}Plan kept. Type 'go' when ready, or 'cancel' to clear it.{X}")
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

        # ── Scroll commands (word-based, mobile-friendly) ─────────────
        if lo == "up" or lo.startswith("up "):
            if os.environ.get("TMUX"):
                parts = lo.split()
                n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                subprocess.run(["tmux", "copy-mode"], check=False)
                for _ in range(n):
                    subprocess.run(["tmux", "send-keys", "-X", "halfpage-up"], check=False)
            else:
                print(f"  {Y}Not in tmux — scroll commands need the tmux session.{X}")
            continue
        if lo == "down" or lo.startswith("down "):
            if os.environ.get("TMUX"):
                parts = lo.split()
                n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                for _ in range(n):
                    subprocess.run(["tmux", "send-keys", "-X", "halfpage-down"], check=False)
            else:
                print(f"  {Y}Not in tmux.{X}")
            continue
        if lo == "top":
            if os.environ.get("TMUX"):
                subprocess.run(["tmux", "copy-mode"], check=False)
                subprocess.run(["tmux", "send-keys", "-X", "history-top"], check=False)
            continue
        if lo == "bottom":
            if os.environ.get("TMUX"):
                subprocess.run(["tmux", "send-keys", "-X", "cancel"], check=False)
            continue
        if lo == "last":
            msgs = [h for h in history if h.get("role") == "assistant"]
            if msgs:
                print(f"\n{G}  ── last reply ──{X}\n{msgs[-1]['content']}\n")
            else:
                print(f"  {Y}No prior reply to show.{X}")
            continue

        # ── Kick: force crash so supervisor loop restarts us ─────────
        if lo in ("kick", "force restart", "hard restart"):
            try: save_session(list(history), silent=True)
            except Exception: pass
            print(f"  {R}💥 Kicking engine — supervisor will restart in 3 sec...{X}", flush=True)
            sys.exit(42)

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

        # ── Plan mode — hold plan, wait for 'go' ──────────────
        if MODE == "plan":
            print(f"{C}  thinking (plan mode)...{X}")
            plan_reply = handle(f"PLAN ONLY (do not execute yet): {user_text}", history)
            globals()['PENDING_PLAN_TEXT'] = plan_reply[:500]
            globals()['PENDING_PLAN_REQUEST'] = user_text
            threading.Thread(target=speak, args=("Plan ready. Type go to execute.",), daemon=True).start()
            continue

        # ── Check cache ───────────────────────────────────────
        cached = cache_lookup(user_text)
        if cached:
            render_reply(cached, prefix=f"\n{M}  AI:{X} ", suffix=f"  {BTN_C} cached {X}\n")
            threading.Thread(target=speak, args=(cached,), daemon=True).start()
            continue

        # Only print "thinking..." for cloud routes (local streams immediately)
        _route, _, _ = detect_route(user_text, has_image=bool(image_path))
        if _route not in ("local", "vision"):
            print(f"{C}  thinking...{X}")
            start_thinking_tips()
        try:
            reply = handle(user_text, history, image_path=image_path)
        finally:
            stop_thinking_tips()
        reply = sanitize(reply) if reply else reply
        cache_store(user_text, reply)
        if TTS_ENABLED:
            threading.Thread(target=speak, args=(reply,), daemon=True).start()

        # Auto-save every ~3000 chars accumulated since last save
        globals()['CHARS_SINCE_SAVE'] = CHARS_SINCE_SAVE + len(user_text) + len(reply or "")
        if CHARS_SINCE_SAVE >= AUTO_SAVE_THRESHOLD:
            threading.Thread(target=_auto_save_background, args=(list(history),), daemon=True).start()

if __name__ == "__main__":
    main()
