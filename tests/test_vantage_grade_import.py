"""Contract tests for Vantage signed grading -> OLA public tenant evidence v2."""
import base64
import hashlib
import json
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.hashchain import verify_chain
from app.main import app
from app.models import ApiKey, EvidenceRecord, Tenant
from scripts import import_vantage_grade as bridge


def _signed_grade(tmp_path: Path):
    private = tmp_path / "grader.key"
    public = tmp_path / "grader.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "Ed25519",
                    "-out", str(private)], check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout",
                    "-out", str(public)], check=True, capture_output=True)
    result = {
        "attempt_id": "attempt-test-1", "user": "person@example.invalid",
        "scenario": "certificate-apocalypse", "attested": True,
        "score": 89, "tier": "merit", "sli": {"mttr_s": 47},
        "trust": {"identity": "server", "assertions": "platform"},
    }
    message = tmp_path / "result.json"
    signature = tmp_path / "result.sig"
    message.write_bytes(json.dumps(result, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8"))
    subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(private),
                    "-rawin", "-in", str(message), "-out", str(signature)],
                   check=True, capture_output=True)
    path = tmp_path / "grade.json"
    path.write_text(json.dumps({"result": result, "signature": base64.b64encode(
        signature.read_bytes()).decode(), "alg": "ed25519",
        "signed": "canonical JSON of result"}), encoding="utf-8")
    pin = hashlib.sha256(public.read_bytes()).hexdigest()
    return path, public, pin


def _tenant():
    tenant_id = str(uuid.uuid4())
    raw_key = "vantage-test-" + tenant_id
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="vantage-import"))
        db.flush()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant_id,
                      key_hash=api_key_fingerprint(raw_key)))
        db.commit()
    return tenant_id, raw_key


def test_valid_signed_grade_records_only_digest_and_v2_tenant_evidence(tmp_path, monkeypatch):
    grade, pubkey, pin = _signed_grade(tmp_path)
    tenant, key = _tenant()
    client = TestClient(app)
    calls = []

    def request(url, token, method, payload=None):
        calls.append((url, method))
        assert token == key
        assert url.startswith("https://ola.example.invalid/evidence")
        path = url.removeprefix("https://ola.example.invalid")
        response = (client.post(path, headers={"X-API-Key": key}, json=payload)
                    if method == "POST" else
                    client.get(path, headers={"X-API-Key": key}))
        assert response.status_code == 200
        return response.json()

    monkeypatch.setattr(bridge, "_request", request)
    out = bridge.import_grade(grade, pubkey, pin, "https://ola.example.invalid",
                              tenant, key)
    assert out["status"] == "RECORDED"
    assert out["source_signature"] == "PASS"
    assert out["production_authorized"] is False
    assert [method for _, method in calls] == ["POST", "GET"]

    with SessionLocal() as db:
        rows = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant).order_by(EvidenceRecord.seq)).all()
    assert len(rows) == 1
    assert rows[0].record_type == "external.vantage.grade"
    assert "person@example.invalid" not in rows[0].payload_json
    assert "attempt-test-1" not in rows[0].payload_json
    assert verify_chain([{
        "tenant_id": row.tenant_id, "seq": row.seq, "record_type": row.record_type,
        "prev_hash": row.prev_hash, "record_hash": row.record_hash,
        "payload_json": row.payload_json,
    } for row in rows]) == (True, "ok")


def test_missing_pin_blocks_without_network(tmp_path, monkeypatch):
    grade, pubkey, _ = _signed_grade(tmp_path)
    monkeypatch.setattr(bridge, "_request", lambda *_args, **_kwargs:
                        pytest.fail("network access must not occur"))
    with pytest.raises(ValueError, match="pin"):
        bridge.import_grade(grade, pubkey, "", "https://ola.example.invalid",
                            str(uuid.uuid4()), "not-a-real-key")


def test_tampered_signed_result_blocks_without_network(tmp_path, monkeypatch):
    grade, pubkey, pin = _signed_grade(tmp_path)
    doc = json.loads(grade.read_text())
    doc["result"]["score"] = 100
    grade.write_text(json.dumps(doc))
    monkeypatch.setattr(bridge, "_request", lambda *_args, **_kwargs:
                        pytest.fail("network access must not occur"))
    with pytest.raises(ValueError, match="signature"):
        bridge.import_grade(grade, pubkey, pin, "https://ola.example.invalid",
                            str(uuid.uuid4()), "not-a-real-key")


def test_wrong_pinned_key_rejected(tmp_path):
    grade, pubkey, _ = _signed_grade(tmp_path)
    with pytest.raises(ValueError, match="pin"):
        bridge.prepare_payload(grade, pubkey, "0" * 64)


@pytest.mark.parametrize("url", [
    "http://ola.example.invalid", "https://ola.example.invalid@evil.invalid",
    "https://ola.example.invalid.evil.invalid/path",
    "https://ola.example.invalid/?token=leak",
    "file:///etc/passwd", "https://ola.example.invalid:443/evidence",
])
def test_unsafe_ola_urls_rejected(url):
    with pytest.raises(ValueError):
        bridge.validate_ola_url(url)


def test_wrong_tenant_or_wrong_record_hash_fails_readback(tmp_path, monkeypatch):
    grade, pubkey, pin = _signed_grade(tmp_path)

    def bad_request(url, _token, method, payload=None):
        if method == "POST":
            return {"id": "fake", "record_hash": "0" * 64}
        return {"id": "fake", "tenant_id": str(uuid.uuid4()),
                "record_type": "external.vantage.grade", "seq": 0,
                "prev_hash": "0" * 64, "record_hash": "0" * 64,
                "payload": payload}

    monkeypatch.setattr(bridge, "_request", bad_request)
    with pytest.raises(RuntimeError, match="evidence"):
        bridge.import_grade(grade, pubkey, pin, "https://ola.example.invalid",
                            str(uuid.uuid4()), "not-a-real-key")


def test_dry_run_has_no_network_or_production_claim(tmp_path, monkeypatch):
    grade, pubkey, pin = _signed_grade(tmp_path)
    monkeypatch.setattr(bridge, "_request", lambda *_args, **_kwargs:
                        pytest.fail("dry run must not call network"))
    out = bridge.import_grade(grade, pubkey, pin, "",
                              "", None, dry_run=True)
    assert out["status"] == "VALIDATED_NOT_RECORDED"
    assert out["production_authorized"] is False
