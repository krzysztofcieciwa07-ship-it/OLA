import hashlib
import json
import subprocess
import sys
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

TEST_API_KEY_SALT = b"scrudix-test-api-key-salt"

from app.database import SessionLocal
from app.hashchain import verify_chain
from app.main import app
from app.models import ApiKey, EvidenceRecord, Tenant
from scripts import import_scrudix_report as importer


REPORT = """Scrudix Usage Reports Export
Generated: 2026-10-24T20:51:18.413Z
User: owner@example.test

## Engineering Productivity Report
Metric: 11 actions in last 30 days
"""


def _report(tmp_path):
    path = tmp_path / "scrudix-usage.md"
    path.write_text(REPORT, encoding="utf-8")
    return path


def _tenant():
    tenant_id = str(uuid.uuid4())
    api_key = f"key-{tenant_id}"
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="scrudix-import-test"))
        db.flush()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant_id,
                      key_hash=hashlib.pbkdf2_hmac(
                          "sha256",
                          api_key.encode("utf-8"),
                          TEST_API_KEY_SALT,
                          600_000,
                      ).hex()))
        db.commit()
    return tenant_id, api_key


def test_import_uses_existing_tenant_evidence_and_verifies_record(tmp_path, monkeypatch):
    tenant_id, key = _tenant()
    client = TestClient(app)
    calls = []

    def request(url, supplied_key, method, payload=None):
        calls.append((url, method))
        assert supplied_key == key
        path = url.removeprefix("https://ola.example.test")
        if method == "POST":
            response = client.post(path, headers={"X-API-Key": key}, json=payload)
        else:
            response = client.get(path, headers={"X-API-Key": key})
        assert response.status_code == 200
        return response.json()

    monkeypatch.setattr(importer, "_request", request)
    result = importer.import_report(_report(tmp_path), "https://ola.example.test", key)

    assert result["status"] == "RECORDED"
    assert result["record_integrity"] == "PASS"
    assert result["source_authenticity"] == "UNVERIFIED"
    assert [method for _, method in calls] == ["POST", "GET"]
    assert all(url.startswith("https://ola.example.test/evidence") for url, _ in calls)

    with SessionLocal() as db:
        rows = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id
        ).order_by(EvidenceRecord.seq.asc())).all()
        assert len(rows) == 1
        payload = json.loads(rows[0].payload_json)
        assert rows[0].record_type == importer.RECORD_TYPE
        assert payload["source"] == "scrudix.user_export"
        assert payload["sha256"] == hashlib.sha256(REPORT.encode()).hexdigest()
        assert "owner@example.test" not in rows[0].payload_json
        assert verify_chain([{
            "tenant_id": row.tenant_id, "seq": row.seq,
            "prev_hash": row.prev_hash, "record_hash": row.record_hash,
            "payload_json": row.payload_json,
        } for row in rows]) == (True, "ok")


def test_dry_run_requires_no_key_or_network(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "_request", lambda *_args, **_kwargs: 1 / 0)
    result = importer.import_report(_report(tmp_path), "https://ola.example.test",
                                    None, dry_run=True)
    assert result["status"] == "DRY_RUN"
    assert result["payload"]["source_authenticity"] == "UNVERIFIED"
    assert "owner@example.test" not in json.dumps(result)


def test_cli_dry_run_without_credentials(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "scripts.import_scrudix_report",
         str(_report(tmp_path)), "--dry-run"],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout)["status"] == "DRY_RUN"
    assert "owner@example.test" not in result.stdout


def test_missing_key_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "_request", lambda *_args, **_kwargs: 1 / 0)
    with pytest.raises(ValueError, match="OLA_API_KEY"):
        importer.import_report(_report(tmp_path), "https://ola.example.test", None)


def test_rejects_unrelated_document(tmp_path):
    path = tmp_path / "secrets.txt"
    path.write_text("unrelated report", encoding="utf-8")
    with pytest.raises(ValueError, match="not a recognized"):
        importer.build_report_payload(path)


@pytest.mark.parametrize("url", [
    "http://example.com", "https://user:pass@example.com",
    "https://ola.example.test/other", "https://ola.example.test?token=private",
])
def test_rejects_unsafe_ola_urls(url):
    with pytest.raises(ValueError):
        importer.validate_ola_url(url)


def test_responding_with_wrong_record_hash_is_not_verified(tmp_path, monkeypatch):
    recorded = {}

    def fake_request(_url, _key, method, payload=None):
        if method == "POST":
            recorded.update(payload["payload"])
            return {"id": "record-1", "record_hash": "0" * 64}
        return {
            "tenant_id": "tenant", "seq": 0, "prev_hash": "0" * 64,
            "record_hash": "0" * 64, "record_type": importer.RECORD_TYPE,
            "payload": recorded,
        }

    monkeypatch.setattr(importer, "_request", fake_request)
    with pytest.raises(RuntimeError, match="hash mismatch"):
        importer.import_report(_report(tmp_path), "https://ola.example.test", "test-key")
