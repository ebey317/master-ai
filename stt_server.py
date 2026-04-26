#!/usr/bin/env python3
import sys, os, json, tempfile, re, gzip, urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from datetime import datetime

_CLIENT_DISCONNECTS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)

SCRIPTS    = os.path.expanduser("~/scripts")
_DEFAULT_CHATS_DIR  = os.path.expanduser("~/.master_ai_chats")
os.makedirs(_DEFAULT_CHATS_DIR, exist_ok=True)

def _active_profile():
    """Return active profile name, or '' for default/legacy."""
    try:
        p = os.path.expanduser('~/.master_ai_active_profile')
        if os.path.exists(p):
            name = open(p).read().strip()
            if name and os.path.isdir(os.path.expanduser(f'~/.master_ai_profiles/{name}')):
                return name
    except Exception:
        pass
    return ''

def _chats_dir():
    """Profile-aware chats dir. Falls back to legacy global dir."""
    prof = _active_profile()
    if prof:
        d = os.path.expanduser(f'~/.master_ai_profiles/{prof}/chats')
        os.makedirs(d, exist_ok=True)
        return d
    return _DEFAULT_CHATS_DIR

# Module-level alias for backwards-compat; per-request handlers should call _chats_dir()
CHATS_DIR = _DEFAULT_CHATS_DIR

def safe_filename(name):
    name = re.sub(r'[^\w\s-]', '', name).strip()
    return re.sub(r'\s+', '_', name)[:60]

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SCRIPTS, **kwargs)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        # /project_summary?name=X[&refresh=1] — precomputed project briefing.
        # Reads the project's PROJECTS.md block + recent sessions, asks local
        # Ollama for a 5-bullet summary, caches under
        # ~/.master_ai_briefings/<slug>.json (or per-profile equivalent).
        # Returned immediately from cache when fresh (<6h); regenerated when
        # stale or when ?refresh=1. This is the "AI pre-reads your stuff so
        # you don't wait at the door" mechanism.
        if self.path == '/pupil.webmanifest':
            try:
                body = json.dumps({
                    'name': 'Pupil - Master AI',
                    'short_name': 'Pupil',
                    'description': 'Master AI browser UI for iOS, Android, and desktop.',
                    'start_url': '/pupil.html',
                    'scope': '/',
                    'display': 'standalone',
                    'orientation': 'portrait',
                    'background_color': '#F0F6FF',
                    'theme_color': '#2266CC',
                    'icons': [
                        {'src': '/pupil-icon.svg', 'sizes': 'any', 'type': 'image/svg+xml', 'purpose': 'any maskable'}
                    ],
                }).encode()
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'application/manifest+json')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            except _CLIENT_DISCONNECTS:
                return
            return

        if self.path == '/pupil-icon.svg':
            try:
                svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="112" fill="#2266CC"/>
<circle cx="256" cy="206" r="98" fill="#F0F6FF"/>
<path d="M138 374c20-70 69-108 118-108s98 38 118 108" fill="none" stroke="#F0F6FF" stroke-width="54" stroke-linecap="round"/>
<path d="M174 190h164" stroke="#042C53" stroke-width="34" stroke-linecap="round"/>
<circle cx="222" cy="218" r="15" fill="#042C53"/>
<circle cx="290" cy="218" r="15" fill="#042C53"/>
</svg>'''.encode()
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'image/svg+xml')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.send_header('Content-Length', len(svg))
                self.end_headers()
                self.wfile.write(svg)
            except _CLIENT_DISCONNECTS:
                return
            return

        if self.path == '/pupil-sw.js':
            try:
                body = b"""const CACHE = 'pupil-shell-v1';
const ASSETS = ['/pupil.html', '/pupil.webmanifest', '/pupil-icon.svg'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== location.origin) return;
  event.respondWith(fetch(event.request).then(response => {
    const copy = response.clone();
    caches.open(CACHE).then(cache => cache.put(event.request, copy));
    return response;
  }).catch(() => caches.match(event.request).then(hit => hit || caches.match('/pupil.html'))));
});
"""
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'application/javascript')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            except _CLIENT_DISCONNECTS:
                return
            return

        if self.path.startswith('/project_summary'):
            try:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                name = (qs.get('name', [''])[0] or '').strip()
                force = qs.get('refresh', ['0'])[0] == '1'
                if not name:
                    self._json({'error': 'missing name param'}, 400); return

                # Profile-aware cache dir
                active_profile = ''
                try: active_profile = open(os.path.expanduser('~/.master_ai_active_profile')).read().strip()
                except Exception: pass
                if active_profile and os.path.isdir(os.path.expanduser(f'~/.master_ai_profiles/{active_profile}')):
                    cache_dir = os.path.expanduser(f'~/.master_ai_profiles/{active_profile}/briefings')
                else:
                    cache_dir = os.path.expanduser('~/.master_ai_briefings')
                os.makedirs(cache_dir, exist_ok=True)

                slug = re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_').lower()
                cache_path = os.path.join(cache_dir, slug + '.json')

                # Return cached if fresh and not forced
                import time as _time
                if (not force) and os.path.exists(cache_path):
                    try:
                        cached = json.load(open(cache_path))
                        if _time.time() - cached.get('cached_at', 0) < 6 * 3600:
                            cached['source'] = 'cache'
                            self._json(cached); return
                    except Exception:
                        pass

                # Build context: PROJECTS.md block + last 3 session tails
                pfile = os.path.expanduser('~/scripts/PROJECTS.md')
                block = ''
                try:
                    in_p = False
                    for ln in open(pfile).read().splitlines():
                        if ln.strip() == f'### {name}':
                            in_p = True; continue
                        if in_p and (ln.startswith('### ') or ln.startswith('## ')):
                            break
                        if in_p: block += ln + '\n'
                except Exception:
                    block = '(no PROJECTS.md entry)'

                sessions_tail = ''
                sessions_dir = os.path.expanduser('~/scripts/sessions')
                if os.path.isdir(sessions_dir):
                    logs = sorted(
                        [f for f in os.listdir(sessions_dir) if f.endswith('.log')],
                        key=lambda f: os.path.getmtime(os.path.join(sessions_dir, f)),
                        reverse=True
                    )[:3]
                    for f in logs:
                        try:
                            tail = open(os.path.join(sessions_dir, f)).read()[-2500:]
                            sessions_tail += f'\n=== {f} ===\n{tail}\n'
                        except Exception:
                            pass

                # Ask local Ollama for a bulletin
                # Trim inputs — shorter prompt = faster cold start.
                # The 7B coder model loads quicker than the 14B master model
                # and is fine for a 5-bullet summarization.
                block_trim = block[:1500]
                tail_trim = sessions_tail[-2500:] if sessions_tail else ''
                prompt = f"""Project briefing for someone returning after a break.
Project: {name}
Board:
{block_trim}

Recent snippet:
{tail_trim}

Output EXACTLY 5 short bullets, each starting with "- ". No preamble. No closing.
- state in one line
- what's blocking in one line
- last thing done in one line
- next move in one line
- anything easy to forget in one line"""
                summary_text = ''
                try:
                    req = urllib.request.Request(
                        'http://localhost:11434/api/generate',
                        data=json.dumps({
                            'model': 'qwen2.5:3b',
                            'prompt': prompt,
                            'stream': False,
                            'keep_alive': 0,
                            'options': {'num_predict': 140, 'temperature': 0.3},
                        }).encode(),
                        headers={'Content-Type': 'application/json'},
                    )
                    with urllib.request.urlopen(req, timeout=45) as resp:
                        data = json.loads(resp.read().decode())
                        summary_text = data.get('response', '').strip()
                except Exception as _e:
                    summary_text = f'(briefing generation failed: {_e}) — fallback to project board below.'

                payload = {
                    'name': name,
                    'summary': summary_text,
                    'project_block': block,
                    'cached_at': int(_time.time()),
                    'source': 'fresh',
                }
                # Only cache SUCCESSFUL briefings so a cold-Ollama timeout on
                # first try doesn't stick. Next request retries.
                if not summary_text.startswith('(briefing generation failed'):
                    with open(cache_path, 'w') as f:
                        json.dump(payload, f, indent=2)
                self._json(payload); return
            except Exception as e:
                self._error(str(e)); return

        # /sys — quick RAM + swap + loaded-model snapshot for the Pupil
        # sidebar. Cheap to compute; cheap to poll every 5s. Lets the user
        # see pressure before they open a third tab.
        if self.path == '/sys':
            try:
                mem = {'total_mb': 0, 'used_mb': 0, 'available_mb': 0, 'swap_used_mb': 0}
                try:
                    with open('/proc/meminfo') as f:
                        m = {}
                        for line in f:
                            k, _, v = line.partition(':')
                            v = v.strip().split()[0]
                            m[k] = int(v) // 1024   # KB → MB
                    mem['total_mb']     = m.get('MemTotal', 0)
                    mem['available_mb'] = m.get('MemAvailable', 0)
                    mem['used_mb']      = mem['total_mb'] - mem['available_mb']
                    mem['swap_used_mb'] = m.get('SwapTotal', 0) - m.get('SwapFree', 0)
                except Exception:
                    pass
                # Ask Ollama what's currently loaded (returns fast even cold)
                loaded = []
                try:
                    req = urllib.request.Request('http://localhost:11434/api/ps')
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        d = json.loads(resp.read().decode())
                        for m in d.get('models', []):
                            loaded.append({
                                'name': m.get('name'),
                                'size_mb': int(m.get('size_vram', m.get('size', 0))) // (1024*1024),
                            })
                except Exception:
                    pass
                self._json({'mem': mem, 'loaded_models': loaded})
            except Exception as e:
                self._error(str(e))
            return

        # /thoughts — canonical Master AI voice (trademark quotes + tips +
        # thinking phrases). Shared by Sensei and Pupil so both UIs speak in
        # one accord. Source of truth: ~/scripts/master_ai_voice.json.
        if self.path == '/thoughts':
            try:
                vpath = os.path.expanduser('~/scripts/master_ai_voice.json')
                if os.path.exists(vpath):
                    data = json.load(open(vpath))
                else:
                    data = {}
                self._json(data); return
            except Exception as e:
                self._error(str(e)); return

        # /node_info — public info this node announces to mesh peers.
        # Returned from any /node_info GET (localhost or Tailscale).
        # Scaffolding only: no auth yet, no routing yet. Enough for a
        # peer to confirm "yes there's a Master AI at this IP".
        if self.path == '/node_info':
            try:
                import socket as _sk, platform as _pl
                mesh_path = os.path.expanduser('~/.master_ai_mesh.json')
                mesh_cfg = {}
                try:
                    if os.path.exists(mesh_path):
                        mesh_cfg = json.load(open(mesh_path))
                except Exception:
                    mesh_cfg = {}
                active_model = ''
                try:
                    am = os.path.expanduser('~/.master_ai_active_model')
                    if os.path.exists(am):
                        active_model = open(am).read().strip()
                except Exception:
                    pass
                info = {
                    'node_name': mesh_cfg.get('node_name') or _sk.gethostname(),
                    'version': 'master-ai v1.8-testing',
                    'platform': _pl.system().lower(),
                    'active_model': active_model or 'auto',
                    'profile': _active_profile(),
                    'ports': {'stt': 8080, 'ollama': 11434, 'tts': 5050},
                }
                self._json(info); return
            except Exception as e:
                self._error(str(e)); return

        # /peers — list of peer nodes this node knows about, read from
        # ~/.master_ai_mesh.json. No live ping here — that's a separate
        # client-side job. This just exposes the address book.
        if self.path == '/peers':
            try:
                mesh_path = os.path.expanduser('~/.master_ai_mesh.json')
                peers = []
                if os.path.exists(mesh_path):
                    cfg = json.load(open(mesh_path))
                    peers = cfg.get('peers', []) or []
                self._json({'peers': peers}); return
            except Exception as e:
                self._error(str(e)); return

        # /profile — return the active Master AI profile name (empty string if
        # none). Pupil uses this to namespace its localStorage so each user
        # gets their own settings/sessions in the browser.
        if self.path == '/profile':
            try:
                p = os.path.expanduser('~/.master_ai_active_profile')
                name = open(p).read().strip() if os.path.exists(p) else ''
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'profile': name}).encode())
            except Exception as e:
                self._error(str(e))
            return

        # /keys — bridge between menu 11's ~/.master_ai_keys and Pupil's
        # localStorage-based wizard. Only exposed on localhost; the underlying
        # file is already chmod 600 owned by the user. Returns the JSON as-is.
        # Pupil uses this so you don't have to paste the same key twice.
        if self.path == '/keys':
            try:
                keys_file = os.path.expanduser('~/.master_ai_keys')
                if os.path.exists(keys_file):
                    with open(keys_file) as f:
                        data = json.load(f)
                else:
                    data = {}
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self._error(str(e))
            return

        if self.path == '/sessions':
            try:
                chats = _chats_dir()
                all_files = os.listdir(chats)
                gz_files  = [f for f in all_files if f.endswith('.json.gz')]
                json_files = [f for f in all_files if f.endswith('.json') and not f.endswith('.gz')]
                files = sorted(
                    gz_files + json_files,
                    key=lambda f: os.path.getmtime(os.path.join(chats, f)),
                    reverse=True
                )
                sessions = []
                for f in files:
                    try:
                        path = os.path.join(chats, f)
                        if f.endswith('.json.gz'):
                            with gzip.open(path, 'rt', encoding='utf-8') as fh:
                                data = json.load(fh)
                        else:
                            with open(path) as fh:
                                data = json.load(fh)
                        sessions.append({
                            'file': f,
                            'name': data.get('name', f),
                            'date': data.get('date', ''),
                            'ts':   data.get('ts', 0),
                            'source': data.get('source', 'Web UI'),
                            'messages': data.get('messages', [])
                        })
                    except Exception:
                        pass
                # Also load PC Control .log sessions from ~/scripts/sessions/
                pc_sessions_dir = os.path.join(SCRIPTS, 'sessions')
                if os.path.isdir(pc_sessions_dir):
                    for f in sorted(os.listdir(pc_sessions_dir), reverse=True):
                        if not f.endswith('.log'): continue
                        try:
                            path = os.path.join(pc_sessions_dir, f)
                            with open(path) as fh:
                                lines = fh.readlines()
                            msgs = []
                            for line in lines:
                                line = line.strip()
                                if line.startswith('[') and '] You: ' in line:
                                    msgs.append({'role':'user','content': line.split('] You: ',1)[1]})
                                elif line.startswith('[') and '] AI: ' in line:
                                    msgs.append({'role':'assistant','content': line.split('] AI: ',1)[1]})
                            if msgs:
                                ts = int(os.path.getmtime(path) * 1000)
                                sessions.append({
                                    'file': f,
                                    'name': f.replace('.log','').replace('_',' '),
                                    'date': datetime.fromtimestamp(ts/1000).strftime('%-m/%-d/%Y'),
                                    'ts': ts,
                                    'source': 'PC Control',
                                    'messages': msgs
                                })
                        except Exception:
                            pass
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(sessions).encode())
            except Exception as e:
                self._error(str(e))
        else:
            try:
                super().do_GET()
            except _CLIENT_DISCONNECTS:
                return

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        data   = self.rfile.read(length)

        # /ask — federated routing endpoint. Accepts {prompt, model?} and runs
        # it through the LOCAL Ollama on this node, returning the response.
        # Auth: X-Mesh-Token header must match the token in ~/.master_ai_mesh.json.
        # No token configured → endpoint refuses all requests (fail-closed).
        # This is the mesh's "question on node A → answer from node B" pipe.
        if self.path == '/ask':
            try:
                mesh_path = os.path.expanduser('~/.master_ai_mesh.json')
                expected_token = ''
                if os.path.exists(mesh_path):
                    try:
                        expected_token = (json.load(open(mesh_path)).get('mesh_token') or '').strip()
                    except Exception:
                        expected_token = ''
                if not expected_token:
                    self._json({'error': 'mesh not configured (no mesh_token set in ~/.master_ai_mesh.json)'}, 503); return
                supplied = (self.headers.get('X-Mesh-Token') or '').strip()
                if supplied != expected_token:
                    self._json({'error': 'unauthorized (bad or missing X-Mesh-Token)'}, 401); return

                payload = json.loads(data or b'{}')
                prompt  = (payload.get('prompt') or '').strip()
                model   = (payload.get('model')  or 'qwen2.5:3b').strip()
                if not prompt:
                    self._json({'error': 'missing prompt'}, 400); return

                import urllib.request, time as _time
                t0 = _time.time()
                body = json.dumps({
                    'model': model,
                    'prompt': prompt,
                    'stream': False,
                    'options': {'num_predict': 512, 'temperature': 0.7}
                }).encode()
                req = urllib.request.Request('http://localhost:11434/api/generate',
                    data=body, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=120) as r:
                    d = json.loads(r.read())
                self._json({
                    'response': d.get('response', ''),
                    'model': model,
                    'elapsed_s': round(_time.time() - t0, 2),
                    'node': os.uname().nodename if hasattr(os, 'uname') else 'unknown',
                }); return
            except Exception as e:
                self._json({'error': str(e)}, 500); return

        # /fetch_url — Pupil's read-a-URL endpoint. Accepts {url} and
        # returns {url, markdown} by calling master_ai.firecrawl_fetch().
        # Needs a Firecrawl API key configured (see /keys). Different from
        # /web_search: that one returns snippets from many pages; this one
        # returns ONE page's full clean markdown content.
        if self.path == '/fetch_url':
            try:
                payload = json.loads(data or b'{}')
                url = (payload.get('url') or '').strip()
                if not url:
                    self._json({'error': 'missing url'}, 400); return
                import sys as _sys
                _here = os.path.dirname(os.path.abspath(__file__))
                if _here not in _sys.path:
                    _sys.path.insert(0, _here)
                import master_ai as _m
                markdown = _m.firecrawl_fetch(url)
                self._json({'url': url, 'markdown': markdown}); return
            except Exception as e:
                self._json({'error': str(e)}, 500); return

        # /web_search — live web search for Pupil (the browser UI). Pupil
        # detects time-sensitive questions client-side and POSTs here so
        # the same Gemini-grounded-then-DDG blend Sensei uses is available
        # in the browser. Returns {query, results, have_gemini} so Pupil
        # can display results and show the user which engine answered.
        # No auth — localhost / Tailscale only. No secrets returned.
        if self.path == '/web_search':
            try:
                payload = json.loads(data or b'{}')
                query = (payload.get('query') or '').strip()
                # engine: optional. "all" or omitted → full blender.
                # Anything else → single engine, header-wrapped so the
                # downstream detection dict still reports which answered.
                engine = (payload.get('engine') or '').strip().lower()
                # stream: when true AND running the blend, emit NDJSON
                # lines live — one per engine as it completes — so the
                # client can show results progressively instead of
                # waiting for the slowest engine (Gemini, ~20s).
                stream = bool(payload.get('stream'))
                if not query:
                    self._json({'error': 'missing query'}, 400); return
                # Import master_ai lazily — avoids a heavy import at server
                # startup and keeps stt_server functional even if master_ai
                # has a runtime issue.
                import sys as _sys
                _here = os.path.dirname(os.path.abspath(__file__))
                if _here not in _sys.path:
                    _sys.path.insert(0, _here)
                import master_ai as _m
                _engine_map = {
                    'gemini_grounded':    (_m.gemini_grounded_search, '[Google (via Gemini grounding)]'),
                    'brave':              (_m.brave_search,            '[Brave Search]'),
                    'serper':             (_m.serper_search,           '[Google (via Serper)]'),
                    'wikipedia':          (_m.wikipedia_search,        '[Wikipedia]'),
                    'duckduckgo':         (_m.duckduckgo_search,       '[DuckDuckGo]'),
                    'duckduckgo_instant': (_m.ddg_instant_answer,      '[DuckDuckGo Instant Answer]'),
                    'wikihow':            (_m.wikihow_via_gemini,      '[WikiHow (via Google site:)]'),
                }

                # ── Live-stream path ──
                # NDJSON over a Connection: close response. Each engine
                # emits start / done / empty / error. Client parses
                # line-by-line and renders as it reads. Fast engines
                # (Wikipedia ~1s) show up long before slow ones (Gemini).
                if stream and (not engine or engine == 'all'):
                    self.send_response(200)
                    self._cors()
                    self.send_header('Content-Type', 'application/x-ndjson')
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('X-Accel-Buffering', 'no')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    def _emit(obj):
                        try:
                            self.wfile.write((json.dumps(obj) + '\n').encode())
                            self.wfile.flush()
                        except Exception:
                            pass
                    _emit({'type': 'start', 'query': query,
                           'engines': list(_engine_map.keys())})
                    for key, (fn, header) in _engine_map.items():
                        _emit({'type': 'engine_start', 'engine': key})
                        try:
                            out = fn(query)
                        except Exception as e:
                            _emit({'type': 'engine_error', 'engine': key,
                                   'error': str(e)})
                            continue
                        if out:
                            _emit({'type': 'engine_done', 'engine': key,
                                   'header': header, 'result': out})
                        else:
                            _emit({'type': 'engine_empty', 'engine': key})
                    _emit({'type': 'done'})
                    return

                if engine and engine != 'all' and engine in _engine_map:
                    fn, header = _engine_map[engine]
                    out = fn(query)
                    results = f"{header}\n{out}" if out else f"Search unavailable: {engine} returned nothing."
                else:
                    results = _m.web_search(query)
                # Report which engines contributed so Pupil can show a
                # badge listing exactly what answered. Detection is by
                # the section headers master_ai.web_search() emits.
                r = results or ''
                engines = {
                    'gemini_grounded':     '[Google (via Gemini grounding)]' in r,
                    'brave':               '[Brave Search]' in r,
                    'serper':              '[Google (via Serper)]' in r,
                    'wikipedia':           '[Wikipedia]' in r,
                    'duckduckgo':          '[DuckDuckGo]' in r,
                    'duckduckgo_instant':  '[DuckDuckGo Instant Answer]' in r,
                    'wikihow':             '[WikiHow (via Google site:)]' in r,
                }
                self._json({
                    'query': query,
                    'results': results,
                    'engines': engines,
                }); return
            except Exception as e:
                self._json({'error': str(e)}, 500); return

        if self.path == '/stt':
            tmp = tempfile.NamedTemporaryFile(suffix='.webm', delete=False)
            tmp.write(data)
            tmp.close()
            try:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    import whisper
                    model = whisper.load_model('base')
                    result = model.transcribe(tmp.name)
                text = result['text'].strip()
                self._json({'text': text})
            except Exception as e:
                self._json({'error': str(e)}, 500)
            finally:
                try: os.unlink(tmp.name)
                except Exception: pass

        elif self.path == '/sessions':
            try:
                chats = _chats_dir()
                session = json.loads(data)
                name    = session.get('name', 'chat')
                ts      = session.get('ts', int(datetime.now().timestamp() * 1000))
                fname   = f"{ts}_{safe_filename(name)}.json.gz"
                with gzip.open(os.path.join(chats, fname), 'wt', encoding='utf-8') as f:
                    json.dump(session, f, separators=(',', ':'))
                # Auto-generate summary via local AI
                try:
                    import urllib.request
                    msgs = session.get('messages', [])
                    if len(msgs) >= 4:
                        transcript = "\n".join(
                            f"{m['role'].upper()}: {str(m.get('content',''))[:300]}"
                            for m in msgs[-30:] if m.get('role') in ('user','assistant')
                        )
                        prompt = ("Summarize this AI session in exactly 4 bullets. "
                                  "What was worked on, decided, unfinished, next steps. "
                                  "Format: • bullet\n\n" + transcript)
                        payload = json.dumps({'model':'qwen2.5:7b',
                                              'messages':[{'role':'user','content':prompt}],
                                              'stream':False}).encode()
                        req = urllib.request.Request('http://localhost:11434/api/chat',
                            data=payload, headers={'Content-Type':'application/json'})
                        with urllib.request.urlopen(req, timeout=30) as r:
                            summary = json.loads(r.read())['message']['content'].strip()
                        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                        summary_fname = fname.replace('.json.gz', '.summary')
                        summary_path = os.path.join(chats, summary_fname)
                        with open(summary_path, 'w') as sf:
                            sf.write(f"[Session {date_str}]\n{summary}\n")
                        # Append to memory (profile-aware)
                        prof = _active_profile()
                        if prof:
                            mem_file = os.path.expanduser(f"~/.master_ai_profiles/{prof}/memory")
                        else:
                            mem_file = os.path.expanduser("~/.master_ai_memory")
                        try:
                            existing = open(mem_file).read() if os.path.exists(mem_file) else ""
                            lines = [l for l in existing.splitlines() if not l.startswith("[Session ")]
                            session_lines = [l for l in existing.splitlines() if l.startswith("[Session ")][-4:]
                            with open(mem_file, 'w') as mf:
                                mf.write("\n".join(lines + session_lines +
                                    [f"[Session {date_str}]"] + summary.splitlines()) + "\n")
                        except Exception:
                            pass
                except Exception:
                    pass
                self._json({'saved': fname})
            except Exception as e:
                self._json({'error': str(e)}, 500)

        elif self.path == '/keys':
            # Merge incoming key(s) into ~/.master_ai_keys. Body shape:
            #   {"field": "groq", "value": "gsk_..."} — sets one
            #   OR {"merge": {"groq": "...", "openai": "..."}} — merges many
            # Duplicate protection: if a value for "field" exists and differs,
            # it becomes "{field}_2" instead of overwriting.
            try:
                payload   = json.loads(data)
                keys_file = os.path.expanduser('~/.master_ai_keys')
                try:
                    existing = json.load(open(keys_file)) if os.path.exists(keys_file) else {}
                except Exception:
                    existing = {}
                incoming = {}
                if isinstance(payload.get('merge'), dict):
                    incoming.update(payload['merge'])
                if payload.get('field') and payload.get('value') is not None:
                    incoming[payload['field']] = payload['value']
                for field, value in incoming.items():
                    if field in existing and existing[field] and existing[field] != value:
                        existing[field + '_2'] = value   # backup slot
                    else:
                        existing[field] = value
                with open(keys_file, 'w') as f:
                    json.dump(existing, f, indent=2)
                os.chmod(keys_file, 0o600)
                self._json({'saved': list(incoming.keys()), 'count': len(existing)})
            except Exception as e:
                self._json({'error': str(e)}, 500)

        elif self.path == '/sessions/delete':
            try:
                payload = json.loads(data)
                fname   = os.path.basename(payload.get('file', ''))
                chats   = _chats_dir()
                # support both .json and .json.gz
                path    = os.path.join(chats, fname)
                if not (fname and os.path.exists(path)):
                    alt = fname + '.gz' if not fname.endswith('.gz') else fname[:-3]
                    path = os.path.join(chats, alt)
                    fname = alt
                if fname and os.path.exists(path):
                    os.unlink(path)
                    self._json({'deleted': fname})
                else:
                    self._json({'error': 'not found'}, 404)
            except Exception as e:
                self._json({'error': str(e)}, 500)

        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        try:
            self.send_response(status)
            self._cors()
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        except _CLIENT_DISCONNECTS:
            return

    def _error(self, msg):
        self._json({'error': msg}, 500)

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def log_message(self, fmt, *args):
        pass

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    _prof = _active_profile()
    _prof_tag = f"  |  Profile: {_prof}" if _prof else ""
    print(f"🚀 Master AI server on :{port}  |  STT: Whisper  |  Sessions: {_chats_dir()}{_prof_tag}")
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
