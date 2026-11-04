"""Capture a disposable CI fixture run; never use this recorder for client traffic.

Only POST /api/chat on loopback is forwarded to the local Ollama process.
No request headers, credentials, API keys, or customer database rows are exported.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
import urllib.request

LOCK = threading.Lock()
MAX_BODY = 2 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def serve(trace_path):
    class Recorder(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def do_POST(self):
            if self.path != "/api/chat":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                self.send_error(413)
                return
            request_bytes = self.rfile.read(length)
            started = datetime.now(timezone.utc).isoformat()
            clock = time.monotonic()
            upstream = urllib.request.Request(
                "http://127.0.0.1:11434/api/chat",
                data=request_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(upstream, timeout=120) as response:
                    response_bytes = response.read(MAX_BODY + 1)
                    status = response.status
                if len(response_bytes) > MAX_BODY:
                    raise ValueError("provider response exceeds recorder limit")
                event = {
                    "schema": "ola.ci-provider-capture.v1",
                    "started_utc": started,
                    "duration_seconds": time.monotonic() - clock,
                    "method": "POST",
                    "path": "/api/chat",
                    "upstream": "loopback-ollama",
                    "http_status": status,
                    "request": json.loads(request_bytes),
                    "response": json.loads(response_bytes),
                    "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
                    "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
                }
                with LOCK:
                    with Path(trace_path).open("a", encoding="utf-8") as stream:
                        stream.write(canonical(event) + "\n")
                        stream.flush()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_bytes)))
                self.end_headers()
                self.wfile.write(response_bytes)
            except (OSError, ValueError, urllib.error.URLError):
                self.send_error(502, "local provider capture failed")

    ThreadingHTTPServer(("127.0.0.1", 11435), Recorder).serve_forever()


def export(context_path):
    context = json.loads(Path(context_path).read_text(encoding="utf-8"))
    db = sqlite3.connect("file:/data/ola.db?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    rows = [
        dict(row) for row in db.execute(
            "SELECT id,tenant_id,seq,record_type,payload_json,prev_hash,record_hash "
            "FROM evidence_records WHERE tenant_id=? ORDER BY seq",
            (context["tenant_id"],),
        ).fetchall()
    ]
    db.close()
    sources = {}
    for path in sorted(Path("app").glob("*.py")) + [
        Path("scripts/verify_agent_runtime.py"),
        Path("scripts/capture_runtime_sample.py"),
    ]:
        data = path.read_bytes()
        sources[str(path)] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob_sha1": hashlib.sha1(
                b"blob " + str(len(data)).encode("ascii") + b"\0" + data
            ).hexdigest(),
        }
    import os
    result = {
        "schema": "ola.portable-ci-evidence.v1",
        "fixture_only": True,
        "context": context,
        "records": rows,
        "runtime_response": json.loads(
            Path("/data/runtime-response.json").read_text(encoding="utf-8")
        ),
        "runtime_sources": sources,
        "observed_environment": {
            name: os.getenv(name)
            for name in [
                "OLA_RUNTIME_COMMIT", "OLA_LLM_PROVIDER", "OLA_LLM_MODE",
                "OLA_LLM_MODEL", "OLLAMA_MODEL", "OLA_OLLAMA_NUM_PREDICT",
            ]
        },
    }
    print(canonical(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    server = sub.add_parser("serve")
    server.add_argument("--trace", required=True)
    exporter = sub.add_parser("export")
    exporter.add_argument("--context", required=True)
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.trace)
    else:
        export(args.context)


if __name__ == "__main__":
    main()
