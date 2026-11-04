"""Recorder transport checks only. The upstream here is a test double, not an LLM."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

class CaptureTests(unittest.TestCase):
    def test_records_response_bytes_and_rejects_other_routes(self):
        response_bytes = b'{"model":"fixture-only","message":{"content":"fixture"}}'
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(response_bytes)
        upstream = ThreadingHTTPServer(("127.0.0.1", 11434), Upstream)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory() as folder:
            trace = Path(folder) / "capture.jsonl"
            script = Path(__file__).resolve().parents[1] / "scripts/capture_runtime_sample.py"
            process = subprocess.Popen([sys.executable, str(script), "serve", "--trace", str(trace)])
            try:
                for _ in range(50):
                    try:
                        with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=1):
                            break
                    except OSError:
                        time.sleep(.05)
                connection = http.client.HTTPConnection("127.0.0.1", 11435, timeout=2)
                request_bytes = b'{"model":"fixture-only","messages":[]}'
                connection.request("POST", "/api/chat", request_bytes, {"Content-Type":"application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), response_bytes)
                event = json.loads(trace.read_text())
                self.assertEqual(event["request"], json.loads(request_bytes))
                self.assertEqual(event["response"], json.loads(response_bytes))
                import hashlib
                self.assertEqual(event["response_sha256"], hashlib.sha256(response_bytes).hexdigest())
                connection.close()
                for method, path, body, expected in [
                    ("GET", "/forbidden", None, 404),
                    ("POST", "/forbidden", b"{}", 404),
                    ("POST", "/api/chat", b"", 413),
                ]:
                    connection = http.client.HTTPConnection("127.0.0.1", 11435, timeout=2)
                    connection.request(method, path, body)
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected)
                    response.read()
                    connection.close()
                self.assertEqual(len(trace.read_text().splitlines()), 1)
            finally:
                process.terminate()
                process.wait(timeout=5)
                upstream.shutdown()
                upstream.server_close()

if __name__ == "__main__":
    unittest.main()
