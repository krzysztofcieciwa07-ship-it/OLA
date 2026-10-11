"""Run the real deterministic API -> evidence -> browser-model contract in an isolated DB.

Run with Python + Node installed; outputs contain no API credentials.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
with tempfile.TemporaryDirectory(prefix="ola-console-proof-") as directory:
    os.environ["OLA_EG_DB_PATH"] = str(Path(directory) / "proof.db")
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    os.environ.update(OLA_SOURCE_COMMIT=source, OLA_RUNTIME_COMMIT=source,
                      OLA_LLM_PROVIDER="local", OLA_LLM_MODE="deterministic")
    os.environ.pop("OPENAI_API_KEY", None)
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import SessionLocal
    from app.models import Tenant, ApiKey
    tenant, key = str(uuid.uuid4()), uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=tenant, name="isolated-console-proof"))
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant,
                      key_hash=hashlib.sha256(key.encode()).hexdigest()))
        db.commit()
    client = TestClient(app)
    task = "calculate 17*23"
    response = client.post("/nina-run", headers={"X-API-Key": key},
                           json={"task": task, "requested_tools": ["safe_expression"]})
    assert response.status_code == 200
    data = response.json()
    records = [client.get(f"/evidence/{item}", headers={"X-API-Key": key}).json()
               for item in data["decision_report"]["evidence_ids"]]
    script = """
import {summarize, scopedReport} from './web/model.mjs';
let input = ''; for await (const chunk of process.stdin) input += chunk;
const {data, records, tenant, task} = JSON.parse(input);
const view = summarize(data, records, tenant, task);
process.stdout.write(JSON.stringify(scopedReport(data, records, view)));
"""
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                            input=json.dumps(dict(data=data, records=records, tenant=tenant, task=task)),
                            capture_output=True, text=True, check=True)
    observation = json.loads(result.stdout)
    assert observation["view"]["result"] == "391", observation["view"]
    assert observation["view"]["issues"] == []
    assert observation["view"]["decision"] == "REVIEW"
    assert observation["view"]["mode"] == "Lokalne wykonanie deterministyczne"
    assert key not in result.stdout
    from scripts.verify_agent_runtime import verify
    verification = verify(tenant, data["run_id"], source, task, "391", os.environ["OLA_EG_DB_PATH"])
    assert verification["status"] == "VERIFIED", verification
    observation["independent_verifier"] = verification
    print(json.dumps(observation, indent=2, ensure_ascii=False))
