#!/usr/bin/env python3
"""Minimal lab server. It is not an OLA production service."""
import hashlib
import hmac
import http.server
import json
import os
import socketserver
import ssl
import sys
from datetime import datetime, timezone


RUN_ID = os.environ.get("OLA_SCENARIO_RUN_ID", "")
CHALLENGE = os.environ.get("OLA_SCENARIO_CHALLENGE", "")
CHALLENGE_HASH = hashlib.sha256(CHALLENGE.encode()).hexdigest() if CHALLENGE else ""


def emit(event):
    print(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "http_request",
        "run_id": RUN_ID,
        "challenge_sha256": CHALLENGE_HASH,
        **event,
    }, sort_keys=True), flush=True)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        supplied_run = self.headers.get("X-OLA-Scenario-Run", "")
        supplied_challenge = self.headers.get("X-OLA-Scenario-Challenge", "")
        challenge_ok = (
            bool(RUN_ID) and bool(CHALLENGE)
            and hmac.compare_digest(supplied_run, RUN_ID)
            and hmac.compare_digest(supplied_challenge, CHALLENGE)
        )
        status = 200 if self.path == "/health" and challenge_ok else (
            403 if not challenge_ok else 404
        )
        body = json.dumps({
            "status": "ok" if status == 200 else "rejected",
            "run_id": RUN_ID,
            "challenge_sha256": CHALLENGE_HASH,
        }).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        emit({
            "path": self.path,
            "status": status,
            "challenge_ok": challenge_ok,
            "client": self.client_address[0],
        })

    def log_message(self, fmt, *args):
        emit({"server_message": fmt % args})


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class ReloadingTLSServer(ThreadingHTTPServer):
    def __init__(self, address, handler, context, cert_file, key_file):
        self.tls_context = context
        self.cert_file = cert_file
        self.key_file = key_file
        super().__init__(address, handler)

    def get_request(self):
        raw_socket, address = super().get_request()
        try:
            # Reload on each accepted connection; rotation needs no restart.
            self.tls_context.load_cert_chain(self.cert_file, self.key_file)
            return self.tls_context.wrap_socket(raw_socket, server_side=True), address
        except Exception:
            raw_socket.close()
            raise


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OLA_SERVER_MODE", "tls")
    if not RUN_ID or not CHALLENGE:
        raise SystemExit("scenario run id and challenge are required")
    if mode == "control":
        server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    elif mode == "tls":
        cert_file = os.environ.get("TLS_CERT_FILE", "/run/certs/current/server.crt")
        key_file = os.environ.get("TLS_KEY_FILE", "/run/certs/current/server.key")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        server = ReloadingTLSServer(("0.0.0.0", 8443), Handler, context, cert_file, key_file)
    else:
        raise SystemExit("mode must be tls or control")
    print(json.dumps({
        "event": "server_started",
        "mode": mode,
        "run_id": RUN_ID,
        "challenge_sha256": CHALLENGE_HASH,
        "port": 8443 if mode == "tls" else 8080,
    }), flush=True)
    server.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    main()
