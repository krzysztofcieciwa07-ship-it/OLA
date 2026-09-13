import hashlib
import os
import tempfile
import uuid

os.environ["OLA_EG_DB_PATH"] = os.path.join(
    tempfile.mkdtemp(prefix="ola_e2e_"), "e2e.db"
)

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.database import SessionLocal
from app.models import ApiKey, EvidenceRecord, Tenant
from app.hashchain import verify_chain
from app.rules import RuleStatus, rule_cert_expiry_001, rule_core_hash_001


def _seed_tenants():
    db = SessionLocal()
    tenant_a = Tenant(id=str(uuid.uuid4()), name="tenant-a")
    tenant_b = Tenant(id=str(uuid.uuid4()), name="tenant-b")
    db.add_all([tenant_a, tenant_b])
    db.commit()
    db.add_all(
        [
            ApiKey(
                id=str(uuid.uuid4()),
                tenant_id=tenant_a.id,
                key_hash=hashlib.sha256(b"key-a").hexdigest(),
            ),
            ApiKey(
                id=str(uuid.uuid4()),
                tenant_id=tenant_b.id,
                key_hash=hashlib.sha256(b"key-b").hexdigest(),
            ),
        ]
    )
    db.commit()
    db.close()
    return tenant_a, tenant_b


def test_ola_e2e_closed_environment():
    _seed_tenants()
    client = TestClient(app)

    assert client.get("/health").status_code == 200

    created = client.post(
        "/evidence",
        headers={"X-API-Key": "key-a"},
        json={"record_type": "generic", "payload": {"x": 1}},
    )
    assert created.status_code == 200
    record = created.json()
    assert record["seq"] == 0

    owned = client.get(
        f"/evidence/{record['id']}", headers={"X-API-Key": "key-a"}
    )
    assert owned.status_code == 200
    assert owned.json()["payload"] == {"x": 1}

    cross_tenant = client.get(
        f"/evidence/{record['id']}", headers={"X-API-Key": "key-b"}
    )
    assert cross_tenant.status_code == 404

    db = SessionLocal()
    row = db.get(EvidenceRecord, record["id"])
    chain = [
        {
            "tenant_id": row.tenant_id,
            "seq": row.seq,
            "prev_hash": row.prev_hash,
            "record_hash": row.record_hash,
            "payload_json": row.payload_json,
        }
    ]
    db.close()
    assert verify_chain(chain)[0]

    chain[0]["payload_json"] = '{"x":999}'
    assert not verify_chain(chain)[0]

    db = SessionLocal()
    try:
        db.execute(
            text(
                "UPDATE evidence_records "
                "SET payload_json=:payload WHERE id=:id"
            ),
            {"payload": '{"x":2}', "id": record["id"]},
        )
        db.commit()
        raise AssertionError("append-only UPDATE was accepted")
    except AssertionError:
        raise
    except Exception:
        db.rollback()
    finally:
        db.close()

    assert rule_core_hash_001([]).status == RuleStatus.UNKNOWN
    assert (
        rule_cert_expiry_001(
            [
                {
                    "tenant_id": "t",
                    "seq": 0,
                    "record_type": "certificate",
                    "payload_json": "{}",
                }
            ]
        ).status
        == RuleStatus.UNKNOWN
    )
