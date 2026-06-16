#!/usr/bin/env python3
import subprocess, tempfile, os, json, shutil, requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# Configuration
PIPER_MODEL = os.path.expanduser("~/scripts/voices/en_US-amy-medium.onnx")
PIPER_BIN = shutil.which("piper") or os.path.expanduser("~/.local/bin/piper")
APLAY_BIN = shutil.which("aplay")

# ElevenLabs Configuration
# These should ideally be in an env file, but we define them here as constants 
# for the bridge to function.
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "YOUR_API_KEY_HERE")
ELEVENLABS_VOICE_ID = "Madam Mary" # This should be the actual ID (e.g. 'pNXYZ...')
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/"

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

                # --- ELEVENLABS ROUTING ---
                # If a valid API key is present and not the placeholder, use ElevenLabs.
                if ELEVENLABS_API_KEY != "YOUR_API_KEY_HERE":
                    try:
                        audio_content = self.fetch_elevenlabs_audio(text)
                        if audio_content:
                            # Use mpv to play the audio bytes directly from stdin
                            process = subprocess.Popen(
                                ['/home/elijah/.local/bin/mpv', '--no-video', '--volume=100'],
                                stdin=subprocess.PIPE
                            )
                            process.communicate(input=audio_content)
                            print(f"[TTS-ElevenLabs] {text[:60]}...")
                            
                            self.send_response(200)
                            self.send_header('Access-Control-Allow-Origin','*')
                            self.send_header('Content-Type','audio/mpeg')
                            self.send_header('Content-Length', str(len(audio_content)))
                            self.end_headers()
                            self.wfile.write(audio_content)
                            return
                    except Exception as e:
                        print(f"[TTS-Error] ElevenLabs failed: {e}")
                        # Fallback to Piper

                # --- PIPER FALLBACK ---
                if not os.path.exists(PIPER_BIN) or not os.path.exists(PIPER_MODEL):
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(b'piper unavailable')
                    return
                
                tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                tmp.close()
                cleanup_tmp = True
                try:
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
                        subprocess.Popen(['aplay', tmp.name])
                        cleanup_tmp = False 
                        subprocess.Popen(['bash', '-c', f'sleep 5; rm -f {tmp.name}'])
                    
                    print(f"[TTS-Piper] {text[:60]}...")
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

    def fetch_elevenlabs_audio(self, text):
        url = f"{ELEVENLABS_URL}{ELEVENLABS_VOICE_ID}"
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True
            }
        }
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        }
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            return response.content
        else:
            raise Exception(f"ElevenLabs API error: {response.status_code} - {response.text}")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type')
        self.end_headers()

    def log_message(self,*a): pass

HTTPServer(('0.0.0.0',5050), TTSHandler).serve_forever()
