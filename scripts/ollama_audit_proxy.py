"""Loopback HTTP server for the independent Ollama audit proxy."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.providers.ollama_audit_proxy import OllamaAuditProxy


def build_handler(proxy):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OLA-Ollama-Audit-Proxy/1"

        def do_GET(self):
            if self.path != "/api/tags":
                self.send_error(404)
                return
            try:
                response = proxy.handle_tags()
                self.send_response(response.status_code)
                for key, value in response.headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(response.content)))
                self.end_headers()
                self.wfile.write(response.content)
            except Exception:
                self.send_error(502, "upstream model service unavailable")

        def do_POST(self):
            if self.path != "/api/chat":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400)
                return
            if length <= 0 or length > 65536:
                self.send_error(413)
                return
            try:
                response = proxy.handle_chat(self.rfile.read(length))
                self.send_response(response.status_code)
                for key, value in response.headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(response.content)))
                self.end_headers()
                self.wfile.write(response.content)
            except ValueError:
                self.send_error(403, "model lock or structured request validation failed")
            except Exception:
                self.send_error(502, "upstream model service unavailable")

        def log_message(self, fmt, *args):
            return

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--audit-log", required=True)
    parser.add_argument("--lock-file")
    parser.add_argument("--upstream-url", default="http://127.0.0.1:11434")
    parser.add_argument("--port", type=int, default=11435)
    args = parser.parse_args()
    proxy = OllamaAuditProxy(
        private_key_path=args.private_key,
        audit_log_path=args.audit_log,
        upstream_url=args.upstream_url,
        lock_path=args.lock_file,
    )
    server = ThreadingHTTPServer(("127.0.0.1", args.port), build_handler(proxy))
    try:
        server.serve_forever()
    finally:
        server.server_close()
        proxy.close()


if __name__ == "__main__":
    main()
