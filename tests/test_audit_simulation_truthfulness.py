"""A synthetic scenario must not masquerade as an observed runtime recovery."""

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.hashchain import verify_chain
from app.main import run_controlled_audit
from app.models import EvidenceRecord, Tenant


def test_controlled_audit_is_explicitly_simulation_only():
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="audit-simulation-test"))
        db.commit()

    result = run_controlled_audit(
        tenant_id, "Recover a real service outage", "fault_then_recovery"
    )

    assert result["status"] == "PARTIAL"
    assert result["outcome"] == "simulated_only"
    assert result["runtime_status"] == "NOT_EXECUTED"
    assert result["evidence_integrity"] == "VERIFIED"
    assert result["evidence_count"] == 5

    with SessionLocal() as db:
        records = db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.tenant_id == tenant_id)
            .order_by(EvidenceRecord.seq.asc())
        ).all()

    assert [row.record_type for row in records] == [
        "simulation.requested", "simulation.started", "simulation.fault_modelled",
        "simulation.recovery_modelled", "simulation.completed",
    ]
    chain = [
        {
            "tenant_id": row.tenant_id,
            "seq": row.seq,
            "prev_hash": row.prev_hash,
            "record_hash": row.record_hash,
            "record_type": row.record_type,
            "payload_json": row.payload_json,
        }
        for row in records
    ]
    assert verify_chain(chain)[0]

    # A recorded simulation is still protected against post-facto tampering.
    chain[2]["payload_json"] = '{"fault":"silently_changed"}'
    assert not verify_chain(chain)[0]
