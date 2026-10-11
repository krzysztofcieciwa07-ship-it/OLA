"""Real browser -> loopback FastAPI -> isolated DB, with no external model calls."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    output = Path(os.environ["OLA_BROWSER_OUTPUT"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    with tempfile.TemporaryDirectory(prefix="ola-browser-db-") as directory:
        os.environ.update(OLA_EG_DB_PATH=str(Path(directory) / "proof.db"),
                          OLA_SOURCE_COMMIT=source, OLA_RUNTIME_COMMIT=source,
                          OLA_LLM_PROVIDER="local", OLA_LLM_MODE="deterministic")
        os.environ.pop("OPENAI_API_KEY", None)
        from app.main import app  # noqa: F401; creates isolated schema and triggers
        from app.database import SessionLocal
        from app.models import ApiKey, Tenant
        tenant, key = str(uuid.uuid4()), secrets.token_urlsafe(32)
        with SessionLocal() as db:
            db.add(Tenant(id=tenant, name="browser-proof"))
            db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant,
                          key_hash=hashlib.sha256(key.encode()).hexdigest()))
            db.commit()
        # Parent owns the socket throughout startup, avoiding a free-port race.
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            with (output / "server.log").open("w") as log:
                server = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "app.main:app", "--fd", str(listener.fileno()),
                     "--no-access-log"], cwd=ROOT, pass_fds=(listener.fileno(),), stdout=log, stderr=log)
                try:
                    for _ in range(100):
                        if server.poll() is not None:
                            raise RuntimeError("Isolated API failed to start; see server.log")
                        try:
                            with urlopen(base + "/health", timeout=1) as response:
                                if json.load(response).get("status") == "ok":
                                    break
                        except (OSError, ValueError):
                            time.sleep(0.1)
                    else:
                        raise RuntimeError("Isolated API readiness timeout")
                    result = subprocess.run(
                        ["node", "tests/web/browser-smoke.mjs"], cwd=ROOT,
                        input=json.dumps(dict(base=base, key=key, tenant=tenant, source=source)),
                        text=True, capture_output=True, timeout=180)
                    # Do not emit request headers, credentials, or arbitrary browser output.
                    (output / "browser.log").write_text((result.stdout + result.stderr).replace(key, "[REDACTED]"))
                    if result.returncode:
                        raise RuntimeError("Rendered browser proof failed; see browser.log")
                    from scripts.verify_agent_runtime import verify
                    report_path = output / "browser-proof.json"
                    report = json.loads(report_path.read_text())
                    for viewport in report["viewports"]:
                        verification = verify(tenant, viewport["run_id"], source, "calculate 17*23",
                                              "391", os.environ["OLA_EG_DB_PATH"])
                        if verification["status"] != "VERIFIED":
                            raise RuntimeError("Independent verifier rejected browser run")
                        viewport["independent_verifier"] = verification["status"]
                    report["independent_verification"] = "VERIFIED"
                    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
                    print("BROWSER_PROOF_PASS: desktop, mobile, real result 391, evidence, IGOR, replay, REVIEW, logout")
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=5)


if __name__ == "__main__":
    main()
