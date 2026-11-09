#!/usr/bin/env python3
"""Strict TLS and independent control-sentinel probe with append-only JSONL output."""
import argparse
import hashlib
import http.client
import json
import os
import socket
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path


def fingerprint_unverified(host, port, timeout):
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as secured:
                cert = secured.getpeercert(binary_form=True)
                return hashlib.sha256(cert).hexdigest() if cert else None
    except Exception:
        return None


def tls_probe(host, port, ca_file, run_id, challenge, timeout):
    started = time.perf_counter()
    cert_sha256 = None
    error_type = error = None
    status = None
    try:
        context = ssl.create_default_context(cafile=ca_file)
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as secured:
                cert = secured.getpeercert(binary_form=True)
                cert_sha256 = hashlib.sha256(cert).hexdigest() if cert else None
                request = (
                    "GET /health HTTP/1.1\r\n"
                    f"Host: {host}\r\n"
                    f"X-OLA-Scenario-Run: {run_id}\r\n"
                    f"X-OLA-Scenario-Challenge: {challenge}\r\n"
                    "Connection: close\r\n\r\n"
                )
                secured.sendall(request.encode("ascii"))
                first_line = secured.makefile("rb").readline(4096).decode("ascii", errors="replace")
                parts = first_line.split()
                status = int(parts[1]) if len(parts) >= 2 else None
                if status != 200:
                    raise RuntimeError("TLS endpoint returned HTTP " + str(status))
    except Exception as exc:
        error_type, error = exc.__class__.__name__, str(exc)[:240]
        if cert_sha256 is None:
            cert_sha256 = fingerprint_unverified(host, port, timeout)
    return {
        "target_ok": status == 200 and error_type is None,
        "target_status": status,
        "target_error_type": error_type,
        "target_error": error,
        "target_cert_sha256": cert_sha256,
        "target_latency_ms": round((time.perf_counter() - started) * 1000, 3)
    }


def control_probe(host, port, run_id, challenge, timeout):
    started = time.perf_counter()
    status = None
    error_type = error = None
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request("GET", "/health", headers={
            "X-OLA-Scenario-Run": run_id,
            "X-OLA-Scenario-Challenge": challenge,
            "Connection": "close"
        })
        response = connection.getresponse()
        status = response.status
        response.read()
    except Exception as exc:
        error_type, error = exc.__class__.__name__, str(exc)[:240]
    finally:
        connection.close()
    return {
        "control_ok": status == 200 and error_type is None,
        "control_status": status,
        "control_error_type": error_type,
        "control_error": error,
        "control_latency_ms": round((time.perf_counter() - started) * 1000, 3)
    }


def one_sample(args, run_id, challenge, challenge_hash):
    item = {
        "timestamp_epoch": time.time(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "challenge_sha256": challenge_hash
    }
    item.update(tls_probe(args.host, args.port, args.ca, run_id, challenge, args.timeout))
    item.update(control_probe(args.control_host, args.control_port, run_id, challenge, args.timeout))
    return item


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("OLA_TLS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("TLS_PORT", "8443")))
    parser.add_argument("--control-host", default=os.environ.get("OLA_CONTROL_HOST", "127.0.0.1"))
    parser.add_argument("--control-port", type=int, default=int(os.environ.get("CONTROL_PORT", "8080")))
    parser.add_argument("--ca", default=str(Path(os.environ.get("OLA_CERT_DIR", "scenarios/certificate-apocalypse/runtime/certs")) / "ca.crt"))
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--duration", type=float, default=0)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expect", choices=("success", "failure", "any"), default="any")
    args = parser.parse_args()
    run_id = os.environ.get("OLA_SCENARIO_RUN_ID", "")
    challenge = os.environ.get("OLA_SCENARIO_CHALLENGE", "")
    if not run_id or not challenge:
        parser.error("OLA_SCENARIO_RUN_ID and OLA_SCENARIO_CHALLENGE must be set")
    challenge_hash = hashlib.sha256(challenge.encode()).hexdigest()
    if not Path(args.ca).is_file():
        parser.error("CA file not found: " + args.ca)
    samples = []
    end_at = time.monotonic() + args.duration if args.watch else None
    sink_context = args.output.open("a", encoding="utf-8") if args.output else open(os.devnull, "w")
    with sink_context as sink:
        while True:
            started = time.monotonic()
            item = one_sample(args, run_id, challenge, challenge_hash)
            samples.append(item)
            sink.write(json.dumps(item, sort_keys=True) + "\n")
            sink.flush()
            if not args.watch or time.monotonic() >= end_at:
                break
            time.sleep(max(0, args.interval - (time.monotonic() - started)))
    result = samples[-1]
    if args.expect == "success" and (not result["target_ok"] or not result["control_ok"]):
        raise SystemExit(1)
    if args.expect == "failure" and (result["target_ok"] or not result["control_ok"]):
        raise SystemExit(1)
    print(json.dumps({
        "samples": len(samples),
        "target_ok": result["target_ok"],
        "control_ok": result["control_ok"],
        "target_error_type": result["target_error_type"],
        "run_id": run_id,
        "challenge_sha256": challenge_hash
    }, sort_keys=True))


if __name__ == "__main__":
    main()
