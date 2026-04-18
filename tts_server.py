#!/usr/bin/env python3
import subprocess, tempfile, os, json
from http.server import HTTPServer, BaseHTTPRequestHandler

PIPER_MODEL = os.path.expanduser("~/scripts/voices/en_US-lessac-medium.onnx")

class TTSHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/speak':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                text = json.loads(body).get('text', '').strip()
                if text:
                    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                    tmp.close()
                    subprocess.run(['piper','--model',PIPER_MODEL,'--output_file',tmp.name],input=text.encode(),capture_output=True)
                    subprocess.Popen(['aplay', tmp.name])
                    print(f"[TTS] {text[:60]}...")
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin','*')
                self.end_headers()
                self.wfile.write(b'ok')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type')
        self.end_headers()
    def log_message(self,*a): pass

HTTPServer(('0.0.0.0',5050),TTSHandler).serve_forever()
