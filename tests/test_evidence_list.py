import hashlib
import uuid

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import ApiKey, EvidenceRecord, Tenant


CLIENT = TestClient(app)


def _seed_tenant(api_key):
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name=f"evidence-list-{tenant_id}"))
        db.add(
            ApiKey(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                key_hash=hashlib.sha256(api_key.encode()).hexdigest(),
            )
        )
        db.commit()
    return tenant_id


def _create_evidence(api_key, record_type, payload):
    response = CLIENT.post(
        "/evidence",
        headers={"X-API-Key": api_key},
        json={"record_type": record_type, "payload": payload},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _count_tenant_records(tenant_id):
    with SessionLocal() as db:
        return db.query(EvidenceRecord).filter_by(tenant_id=tenant_id).count()


def test_evidence_list_is_read_only_and_tenant_scoped():
    tenant_a = _seed_tenant("evidence-list-a")
    tenant_b = _seed_tenant("evidence-list-b")

    first = _create_evidence("evidence-list-a", "test.first", {"value": 1})
    second = _create_evidence("evidence-list-a", "test.second", {"value": 2})
    _create_evidence("evidence-list-b", "test.other", {"value": 99})

    before_count = _count_tenant_records(tenant_a)

    response = CLIENT.get(
        "/evidence",
        headers={"X-API-Key": "evidence-list-a"},
        params={"limit": 20},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["count"] == 2
    assert [record["seq"] for record in body["records"]] == [second["seq"], first["seq"]]
    assert all(record["tenant_id"] == tenant_a for record in body["records"])
    assert all(len(record["prev_hash"]) == 64 for record in body["records"])
    assert all(len(record["record_hash"]) == 64 for record in body["records"])

    assert _count_tenant_records(tenant_a) == before_count
    assert CLIENT.get(
        "/evidence",
        headers={"X-API-Key": "evidence-list-b"},
        params={"limit": 20},
    ).json()["count"] == 1
