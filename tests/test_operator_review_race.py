"""Force two concurrent HTTP approvals to cross the pre-commit boundary.

The monkeypatch controls timing ONLY; actual approval and persistence remain real.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.main as main_module
from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.hashchain import verify_chain
from app.models import Tenant, ApiKey, EvidenceRecord


def _credentials(tenant, *, create=False):
    token = "race-review-" + uuid.uuid4().hex
    with SessionLocal() as db:
        if create:
            db.add(Tenant(id=tenant, name="approval race synthetic tenant"))
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant,
                      key_hash=api_key_fingerprint(token)))
        db.commit()
    return token


def test_concurrent_reviewers_cannot_both_approve_the_same_tip(monkeypatch):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "a" * 40)
    monkeypatch.setenv("OLA_LLM_MODE", "deterministic")
    tenant = str(uuid.uuid4())
    requester = _credentials(tenant, create=True)
    reviewer_a = _credentials(tenant)
    reviewer_b = _credentials(tenant)
    first = TestClient(main_module.app).post(
        "/nina-run", headers={"X-API-Key": requester},
        json={"task": "Calculate 17 * 23 and return verified result.",
              "requested_tools": ["safe_expression"]})
    assert first.status_code == 200
    run = first.json()
    assert run["status"] == "REVIEW"

    original_append = main_module.append_record
    race = Barrier(2, timeout=10)

    def timed_append(tenant_id, record_type, payload):
        if record_type == "human.approval":
            # On the broken implementation, both requests have already
            # validated the SAME tip when they reach this barrier.
            race.wait()
        return original_append(tenant_id, record_type, payload)

    monkeypatch.setattr(main_module, "append_record", timed_append)

    def approve(key):
        return TestClient(main_module.app).post(
            "/nina-run/" + run["run_id"] + "/approve",
            headers={"Authorization": "Bearer " + key},
            json={"tip_hash": run["tip_hash"], "reason": "independent review"})

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(approve, reviewer_a)
        f2 = executor.submit(approve, reviewer_b)
        codes = sorted((f1.result().status_code, f2.result().status_code))
    assert codes == [200, 409], "exactly one atomic reviewer may win"

    with SessionLocal() as db:
        rows = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant).order_by(EvidenceRecord.seq.asc())).all()
        evidence = [
            {"tenant_id": r.tenant_id, "seq": r.seq, "prev_hash": r.prev_hash,
             "record_hash": r.record_hash, "record_type": r.record_type,
             "payload_json": r.payload_json} for r in rows]
    assert verify_chain(evidence)[0]
    assert sum(row["record_type"] == "human.approval" for row in evidence) == 1
