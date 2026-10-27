"""Regression tests for the separate invoice execution ingress."""
import hashlib
import json
import os
import subprocess
import sys
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.main as main
from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.execution_safety_gate import ExecutionDecision
from app.hashchain import canonical_json, verify_chain
from app.models import ApiKey, EvidenceRecord, Tenant


VALID = {
    "invoice_id": "DEMO-123", "supplier": "Demo Supplier",
    "currency": "EUR", "net": 120.0, "vat_rate": 0.21,
}


@pytest.fixture
def identity():
    tenant_id = str(uuid.uuid4())
    raw_key = f"invoice-admission-{tenant_id}"
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="invoice-admission-test"))
        db.flush()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant_id,
                      key_hash=api_key_fingerprint(raw_key)))
        db.commit()
    return tenant_id, {"X-API-Key": raw_key}


def _rows(tenant_id):
    with SessionLocal() as db:
        records = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id,
        ).order_by(EvidenceRecord.seq.asc())).all()
        return [{"tenant_id": r.tenant_id, "seq": r.seq,
                 "record_type": r.record_type, "prev_hash": r.prev_hash,
                 "record_hash": r.record_hash,
                 "payload_json": r.payload_json} for r in records]


def test_invoice_is_denied_by_default_with_trusted_gate_evidence(
    identity, monkeypatch,
):
    tenant_id, headers = identity
    monkeypatch.delenv("OLA_BUSINESS_INVOICE_DEMO_ENABLED", raising=False)
    monkeypatch.setattr(main, "run_invoice_task", lambda *_: 1 / 0)

    response = TestClient(main.app).post(
        "/business-invoice-run", headers=headers, json={"invoice": VALID},
    )

    assert response.status_code == 403
    rows = _rows(tenant_id)
    assert [r["record_type"] for r in rows] == ["execution.safety_gate"]
    data = json.loads(rows[0]["payload_json"])
    assert data["decision"] == "DENY"
    assert data["action"] == "run_invoice_task"
    assert data["risk"] == "HIGH"
    assert verify_chain(rows) == (True, "ok")


@pytest.mark.parametrize("bad", [
    {**VALID, "net": 1000000000},
    {**VALID, "net": "NaN"},
    {**VALID, "net": -1},
    {**VALID, "net": True},
    {**VALID, "currency": "USD"},
    {**VALID, "vat_rate": 0},
    {**VALID, "vat_rate": "Infinity"},
    {**VALID, "extra": "override"},
])
def test_enabled_demo_rejects_out_of_policy_invoice(
    identity, monkeypatch, bad,
):
    tenant_id, headers = identity
    monkeypatch.setenv("OLA_BUSINESS_INVOICE_DEMO_ENABLED", "1")
    monkeypatch.setattr(main, "run_invoice_task", lambda *_: 1 / 0)
    response = TestClient(main.app).post(
        "/business-invoice-run", headers=headers, json={"invoice": bad},
    )
    assert response.status_code in {400, 403}
    assert not [r for r in _rows(tenant_id)
                if r["record_type"].startswith("agent.")]


def test_opt_in_bounded_demo_records_allow_before_execution(identity, monkeypatch):
    tenant_id, headers = identity
    monkeypatch.setenv("OLA_BUSINESS_INVOICE_DEMO_ENABLED", "1")
    invoked = []
    monkeypatch.setattr(main, "run_invoice_task",
                        lambda tenant, task: invoked.append((tenant, task)) or
                        {"status": "DEMO_ONLY", "transfer_status": "NOT_SENT"})

    response = TestClient(main.app).post(
        "/business-invoice-run", headers=headers,
        json={"invoice": VALID, "risk": "LOW", "human_approved": True},
    )
    assert response.status_code == 200
    assert response.json()["transfer_status"] == "NOT_SENT"
    assert invoked == [(tenant_id, "INVOICE_JSON:" + canonical_json(VALID))]
    rows = _rows(tenant_id)
    assert len(rows) == 1
    data = json.loads(rows[0]["payload_json"])
    assert data["decision"] == "ALLOW"
    assert data["risk"] == "LOW"
    assert data["task_sha256"] == hashlib.sha256(invoked[0][1].encode()).hexdigest()


def test_broken_or_missing_gate_never_executes(identity, monkeypatch):
    tenant_id, headers = identity
    monkeypatch.setenv("OLA_BUSINESS_INVOICE_DEMO_ENABLED", "1")
    monkeypatch.setattr(main, "run_invoice_task", lambda *_: 1 / 0)
    monkeypatch.setattr(main, "BUSINESS_INVOICE_GATE", type("BrokenGate", (), {
        "execute": lambda self, **kwargs: ExecutionDecision(status="BLOCK"),
    })(), raising=False)

    response = TestClient(main.app).post(
        "/business-invoice-run", headers=headers, json={"invoice": VALID},
    )
    assert response.status_code == 403
    assert json.loads(_rows(tenant_id)[0]["payload_json"])["decision"] == "DENY"


def test_gate_evidence_failure_blocks_invoice(identity, monkeypatch):
    _, headers = identity
    monkeypatch.setenv("OLA_BUSINESS_INVOICE_DEMO_ENABLED", "1")
    monkeypatch.setattr(main, "run_invoice_task", lambda *_: 1 / 0)
    monkeypatch.setattr(main, "append_record", lambda *_: 1 / 0)

    response = TestClient(main.app).post(
        "/business-invoice-run", headers=headers, json={"invoice": VALID},
    )
    assert response.status_code == 403


def test_independent_verifier_requires_bounded_demo_admission(
    identity, monkeypatch,
):
    tenant_id, headers = identity
    monkeypatch.setenv("OLA_BUSINESS_INVOICE_DEMO_ENABLED", "1")
    response = TestClient(main.app).post(
        "/business-invoice-run", headers=headers, json={"invoice": VALID},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "VERIFIED"
    proof = subprocess.run([
        sys.executable, "scripts/verify_business_invoice.py",
        "--db", os.environ["OLA_EG_DB_PATH"], "--tenant-id", tenant_id,
        "--run-id", result["run_id"],
        "--invoice-json", canonical_json(VALID), "--expect-gate",
    ], capture_output=True, text=True)
    assert proof.returncode == 0, proof.stdout + proof.stderr
    data = json.loads(proof.stdout)
    assert data["admission_gate_verified"] is True
    assert data["evidence_count"] == 7
