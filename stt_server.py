#!/usr/bin/env python3
import sys, os, json, tempfile, re, gzip
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime

SCRIPTS    = os.path.expanduser("~/scripts")
CHATS_DIR  = os.path.expanduser("~/.master_ai_chats")
os.makedirs(CHATS_DIR, exist_ok=True)

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
        if self.path == '/sessions':
            try:
                all_files = os.listdir(CHATS_DIR)
                gz_files  = [f for f in all_files if f.endswith('.json.gz')]
                json_files = [f for f in all_files if f.endswith('.json') and not f.endswith('.gz')]
                files = sorted(
                    gz_files + json_files,
                    key=lambda f: os.path.getmtime(os.path.join(CHATS_DIR, f)),
                    reverse=True
                )
                sessions = []
                for f in files:
                    try:
                        path = os.path.join(CHATS_DIR, f)
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
            super().do_GET()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        data   = self.rfile.read(length)

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
                session = json.loads(data)
                name    = session.get('name', 'chat')
                ts      = session.get('ts', int(datetime.now().timestamp() * 1000))
                fname   = f"{ts}_{safe_filename(name)}.json.gz"
                with gzip.open(os.path.join(CHATS_DIR, fname), 'wt', encoding='utf-8') as f:
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
                        summary_path = os.path.join(CHATS_DIR, summary_fname)
                        with open(summary_path, 'w') as sf:
                            sf.write(f"[Session {date_str}]\n{summary}\n")
                        # Append to memory
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

        elif self.path == '/sessions/delete':
            try:
                payload = json.loads(data)
                fname   = os.path.basename(payload.get('file', ''))
                # support both .json and .json.gz
                path    = os.path.join(CHATS_DIR, fname)
                if not (fname and os.path.exists(path)):
                    alt = fname + '.gz' if not fname.endswith('.gz') else fname[:-3]
                    path = os.path.join(CHATS_DIR, alt)
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
        self.send_response(status)
        self._cors()
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

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
    print(f"🚀 Master AI server on :{port}  |  STT: Whisper  |  Sessions: {CHATS_DIR}")
    HTTPServer(('0.0.0.0', port), Handler).serve_forever()
