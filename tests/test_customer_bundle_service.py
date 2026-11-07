"""Unit and route contracts for customer bundle creation and sandbox storage."""
import hashlib
import json
from types import SimpleNamespace

import pytest


def test_report_bytes_are_reconstructed_from_the_approved_canonical_digest():
    from app.customer_bundle.service import CustomerBundleCreationRejected, _report_bytes
    from app.customer_bundle.builder import canonical_json_bytes

    report_body = {
        "order_id": "order-report-bytes",
        "summary": "approved",
        "findings": [{"severity": "LOW", "code": "example"}],
    }
    digest = hashlib.sha256(canonical_json_bytes(report_body)).hexdigest()
    job_result = {"report": {"decision_report": {**report_body, "report_sha256": digest}}}

    assert _report_bytes(job_result, expected_digest=digest) == canonical_json_bytes(report_body)

    with pytest.raises(CustomerBundleCreationRejected):
        _report_bytes(job_result, expected_digest="0" * 64)


def test_order_evidence_excerpt_contains_only_allowlisted_order_fields():
    from app.customer_bundle.service import _order_evidence_excerpt
    from app.hashchain import sealed_payload_json

    records = [
        {
            "id": "event-order-1",
            "seq": 7,
            "record_type": "revenue.execution_completed",
            "payload_json": sealed_payload_json(
                "revenue.execution_completed",
                {
                    "order_id": "order-1",
                    "execution_job_id": "job-1",
                    "decision_report_sha256": "a" * 64,
                    "private_customer_email": "customer@example.test",
                    "secret": "must-not-escape",
                },
            ),
            "prev_hash": "b" * 64,
            "record_hash": "c" * 64,
        },
        {
            "id": "event-order-2",
            "seq": 8,
            "record_type": "revenue.execution_completed",
            "payload_json": sealed_payload_json(
                "revenue.execution_completed",
                {"order_id": "order-2", "execution_job_id": "job-2"},
            ),
            "prev_hash": "c" * 64,
            "record_hash": "d" * 64,
        },
    ]

    result = _order_evidence_excerpt(records, order_id="order-1")
    rows = [json.loads(line) for line in result.splitlines()]
    assert len(rows) == 1
    assert rows[0]["id"] == "event-order-1"
    assert rows[0]["payload"]["order_id"] == "order-1"
    assert "private_customer_email" not in result.decode("utf-8")
    assert "must-not-escape" not in result.decode("utf-8")
    assert "order-2" not in result.decode("utf-8")


def test_encrypted_sandbox_storage_put_get_delete_is_idempotent_and_confined(tmp_path):
    from app.customer_bundle.storage import (
        CustomerBundleStorageRejected,
        EncryptedLocalBundleStorage,
    )

    storage = EncryptedLocalBundleStorage(root=tmp_path / "private", key=b"k" * 32)
    payload = b"test-only signed evidence bundle"
    object_ref = storage.put(payload)

    assert storage.get(object_ref) == payload
    stored_path = next((tmp_path / "private").glob("*.olb"))
    assert stored_path.stat().st_mode & 0o077 == 0

    storage.delete(object_ref)
    assert not stored_path.exists()
    storage.delete(object_ref)  # orphan cleanup is idempotent

    with pytest.raises(CustomerBundleStorageRejected):
        storage.delete("local-encrypted://../../outside.olb")


def test_create_bundle_route_fails_closed_when_runtime_services_are_missing(monkeypatch):
    from fastapi.testclient import TestClient

    from app.customer_bundle import routes as bundle_routes
    from app.main import app

    actor = SimpleNamespace(
        tenant_id="tenant-runtime-unconfigured",
        principal_id="principal-reviewer",
        person_ref="person-ref-reviewer",
    )
    monkeypatch.setattr(bundle_routes, "_actor", lambda _request, _role: actor)
    monkeypatch.setattr(bundle_routes, "_csrf", lambda _request, _token: None)
    monkeypatch.setattr(app.state, "customer_bundle_runtime", None)

    response = TestClient(app).post(
        "/checkout-orders/order-runtime-unconfigured/bundles",
    )

    assert response.status_code == 503
    assert "signing, verification, timestamp and storage services" in response.json()["detail"]
