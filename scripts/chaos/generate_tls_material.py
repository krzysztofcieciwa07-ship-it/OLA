#!/usr/bin/env python3
"""Generate a per-run CA and an expired or valid TLS leaf using OpenSSL."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import secrets
import subprocess
import time


def run(command):
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def openssl_date(value):
    return value.strftime("%Y%m%d%H%M%SZ")


def ensure_ca(cert_dir, run_id):
    cert_dir.mkdir(parents=True, exist_ok=True)
    (cert_dir / "newcerts").mkdir(exist_ok=True)
    ca_key, ca_cert = cert_dir / "ca.key", cert_dir / "ca.crt"
    if not ca_key.exists() or not ca_cert.exists():
        run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes",
            "-days", "365", "-keyout", str(ca_key), "-out", str(ca_cert),
            "-subj", "/CN=OLA Chaos Root " + run_id,
            "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-addext", "subjectKeyIdentifier=hash"
        ])
        os.chmod(ca_key, 0o600)
        os.chmod(ca_cert, 0o644)
        (cert_dir / "index.txt").write_text("", encoding="utf-8")
        (cert_dir / "serial").write_text("1000\n", encoding="utf-8")
    config = cert_dir / "openssl-ca.cnf"
    if not config.exists():
        config.write_text(
            "[ ca ]\n"
            "default_ca = local_ca\n"
            "[ local_ca ]\n"
            f"dir = {cert_dir}\n"
            "database = $dir/index.txt\n"
            "new_certs_dir = $dir/newcerts\n"
            "certificate = $dir/ca.crt\n"
            "private_key = $dir/ca.key\n"
            "serial = $dir/serial\n"
            "default_md = sha256\n"
            "default_days = 30\n"
            "policy = policy_any\n"
            "unique_subject = no\n"
            "copy_extensions = copy\n"
            "[ policy_any ]\n"
            "commonName = supplied\n"
            "organizationalUnitName = optional\n"
            "[ server_cert ]\n"
            "basicConstraints = critical,CA:FALSE\n"
            "keyUsage = critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage = serverAuth\n"
            "subjectKeyIdentifier = hash\n"
            "authorityKeyIdentifier = keyid,issuer\n",
            encoding="utf-8"
        )
    if not (cert_dir / "index.txt").exists():
        (cert_dir / "index.txt").write_text("", encoding="utf-8")
    if not (cert_dir / "serial").exists():
        (cert_dir / "serial").write_text("1000\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("good", "bad"))
    parser.add_argument("--runtime", type=Path, default=Path("scenarios/certificate-apocalypse/runtime"))
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    context = json.loads((runtime / "run_context.json").read_text(encoding="utf-8"))
    cert_dir = runtime / "certs"
    ensure_ca(cert_dir, context["run_id"])
    release_id = args.mode + "-" + secrets.token_hex(6)
    release = cert_dir / "releases" / release_id
    release.mkdir(parents=True, exist_ok=False)
    key_file, csr_file, cert_file = release / "server.key", release / "server.csr", release / "server.crt"
    run([
        "openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key_file), "-out", str(csr_file),
        "-subj", "/CN=localhost/OU=" + context["run_id"],
        "-addext", "subjectAltName=DNS:localhost,DNS:tls-under-test,DNS:tls-target,IP:127.0.0.1"
    ])
    now = datetime.now(timezone.utc)
    if args.mode == "bad":
        not_before, not_after = now - timedelta(days=10), now - timedelta(days=1)
    else:
        not_before, not_after = now - timedelta(minutes=5), now + timedelta(days=30)
    run([
        "openssl", "ca", "-batch", "-notext", "-md", "sha256",
        "-config", str(cert_dir / "openssl-ca.cnf"),
        "-in", str(csr_file), "-out", str(cert_file),
        "-extensions", "server_cert",
        "-startdate", openssl_date(not_before),
        "-enddate", openssl_date(not_after)
    ])
    csr_file.unlink(missing_ok=True)
    os.chmod(key_file, 0o600)
    os.chmod(cert_file, 0o644)
    current = cert_dir / "current"
    current_tmp = cert_dir / (".current-" + release_id)
    current_tmp.symlink_to(Path("releases") / release_id)
    os.replace(current_tmp, current)
    cert_der = subprocess.run(
        ["openssl", "x509", "-in", str(cert_file), "-outform", "DER"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ).stdout
    serial = subprocess.run(
        ["openssl", "x509", "-in", str(cert_file), "-noout", "-serial"],
        check=True, stdout=subprocess.PIPE, text=True
    ).stdout.strip()
    event = {
        "mode": args.mode,
        "release_id": release_id,
        "generated_at_epoch": time.time(),
        "not_before_epoch": not_before.timestamp(),
        "not_after_epoch": not_after.timestamp(),
        "not_before_utc": not_before.isoformat(),
        "not_after_utc": not_after.isoformat(),
        "serial": serial,
        "certificate_sha256": hashlib.sha256(cert_der).hexdigest(),
        "run_id": context["run_id"],
        "challenge_sha256": context["challenge_sha256"]
    }
    with (runtime / "certificate-events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
    print(json.dumps(event, sort_keys=True))


if __name__ == "__main__":
    main()
