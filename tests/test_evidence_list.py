import uuid

from fastapi.testclient import TestClient

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.main import app
from app.models import ApiKey, EvidenceRecord, Tenant


CLIENT = TestClient(app)


def _tenant_with_key():
    tenant_id = str(uuid.uuid4())
    raw_key = "evidence-list-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name=f"evidence-list-{tenant_id}"))
        db.add(
            ApiKey(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                key_hash=api_key_fingerprint(raw_key),
                role="tenant",
            )
        )
        db.commit()
    return tenant_id, raw_key


def _create_evidence(api_key, record_type, value):
    response = CLIENT.post(
        "/evidence",
        headers={"X-API-Key": api_key},
        json={"record_type": record_type, "payload": {"value": value}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _record_count(tenant_id):
    with SessionLocal() as db:
        return db.query(EvidenceRecord).filter_by(tenant_id=tenant_id).count()


def test_evidence_list_is_read_only_and_tenant_scoped():
    tenant_a, key_a = _tenant_with_key()
    tenant_b, key_b = _tenant_with_key()

    first = _create_evidence(key_a, "test.first", 1)
    second = _create_evidence(key_a, "test.second", 2)
    _create_evidence(key_b, "test.other", 99)
    before_count = _record_count(tenant_a)

    response = CLIENT.get(
        "/evidence",
        headers={"X-API-Key": key_a},
        params={"limit": 20},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    assert [record["seq"] for record in body["records"]] == [
        second["seq"],
        first["seq"],
    ]
    assert all(record["tenant_id"] == tenant_a for record in body["records"])
    assert all(len(record["prev_hash"]) == 64 for record in body["records"])
    assert all(len(record["record_hash"]) == 64 for record in body["records"])
    assert _record_count(tenant_a) == before_count

    other_tenant = CLIENT.get(
        "/evidence",
        headers={"X-API-Key": key_b},
        params={"limit": 20},
    )
    assert other_tenant.status_code == 200, other_tenant.text
    assert other_tenant.json()["count"] == 1
    assert all(
        record["tenant_id"] == tenant_b
        for record in other_tenant.json()["records"]
    )


def test_evidence_list_paginates_strictly_before_cursor():
    tenant_id, key = _tenant_with_key()
    records = [
        _create_evidence(key, f"test.page.{index}", index)
        for index in (1, 2, 3)
    ]

    first_page = CLIENT.get(
        "/evidence",
        headers={"X-API-Key": key},
        params={"limit": 2},
    )
    assert first_page.status_code == 200, first_page.text
    first_body = first_page.json()
    assert [row["seq"] for row in first_body["records"]] == [
        records[2]["seq"],
        records[1]["seq"],
    ]

    cursor = first_body["records"][-1]["seq"]
    second_page = CLIENT.get(
        "/evidence",
        headers={"X-API-Key": key},
        params={"limit": 2, "before_seq": cursor},
    )
    assert second_page.status_code == 200, second_page.text
    assert [row["seq"] for row in second_page.json()["records"]] == [
        records[0]["seq"]
    ]
    assert all(
        row["tenant_id"] == tenant_id for row in second_page.json()["records"]
    )


def test_evidence_list_requires_authentication_and_valid_pagination():
    _, key = _tenant_with_key()

    assert CLIENT.get("/evidence").status_code == 401
    assert CLIENT.get(
        "/evidence", headers={"X-API-Key": "not-a-valid-key"}
    ).status_code == 401

    for limit in (0, 101):
        response = CLIENT.get(
            "/evidence",
            headers={"X-API-Key": key},
            params={"limit": limit},
        )
        assert response.status_code == 400, response.text

    response = CLIENT.get(
        "/evidence",
        headers={"X-API-Key": key},
        params={"before_seq": -1},
    )
    assert response.status_code == 400, response.text
