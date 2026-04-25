#!/usr/bin/env python3
import subprocess, tempfile, os, json, shutil
from http.server import HTTPServer, BaseHTTPRequestHandler

PIPER_MODEL = os.path.expanduser("~/scripts/voices/en_US-lessac-medium.onnx")
PIPER_BIN = shutil.which("piper") or os.path.expanduser("~/.local/bin/piper")
APLAY_BIN = shutil.which("aplay")

class TTSHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/', '/health'):
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin','*')
            self.send_header('Content-Type','text/plain')
            self.end_headers()
            self.wfile.write(b'ok')
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == '/speak':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                text = json.loads(body).get('text', '').strip()
                if not text:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'missing text')
                    return
                if not os.path.exists(PIPER_BIN) or not os.path.exists(PIPER_MODEL):
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(b'piper unavailable')
                    return
                tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                tmp.close()
                cleanup_tmp = True
                try:
                    # Piper CLI flag is `-f` (was `--output_file` in older builds).
                    proc = subprocess.run(
                        [PIPER_BIN, '-m', PIPER_MODEL, '-f', tmp.name],
                        input=text.encode(), capture_output=True, timeout=30
                    )
                    if proc.returncode != 0 or not os.path.getsize(tmp.name):
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write((proc.stderr or b'piper failed')[:500])
                        return
                    audio = open(tmp.name, 'rb').read()
                    if APLAY_BIN:
                        cleanup_tmp = False
                        subprocess.Popen([
                            'bash', '-c',
                            '"$1" "$2" >/dev/null 2>&1; rm -f "$2"',
                            'tts-play', APLAY_BIN, tmp.name
                        ])
                    print(f"[TTS] {text[:60]}...")
                finally:
                    if cleanup_tmp:
                        try:
                            os.unlink(tmp.name)
                        except Exception:
                            pass
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin','*')
                self.send_header('Content-Type','audio/wav')
                self.send_header('Content-Length', str(len(audio)))
                self.end_headers()
                self.wfile.write(audio)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode()[:500])
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type')
        self.end_headers()
    def log_message(self,*a): pass

HTTPServer(('0.0.0.0',5050),TTSHandler).serve_forever()
