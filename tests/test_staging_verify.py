"""Independent staging verifier regression tests; no producer hash helpers."""
import hashlib
import json
import sqlite3
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from staging_verify import verify_chain


def make_db(path):
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE evidence_records(id TEXT PRIMARY KEY, tenant_id TEXT,
      seq INT, record_type TEXT, payload_json TEXT, prev_hash TEXT, record_hash TEXT);
    CREATE TRIGGER evidence_no_update BEFORE UPDATE ON evidence_records
      BEGIN SELECT RAISE(ABORT, 'evidence_records is append-only'); END;
    """)
    body = json.dumps({
        "test": True, "__ola_evidence_v2__": {
            "version": 2, "record_type": "task.received", "producer": "ola_runtime"
        }
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    material = json.dumps({
        "domain": "OLA-EVIDENCE-CHAIN-V2", "tenant_id": "tenant",
        "seq": 0, "prev_hash": "0" * 64, "record_type": "task.received",
        "producer": "ola_runtime", "payload_json": body,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(material.encode()).hexdigest()
    db.execute("INSERT INTO evidence_records VALUES (?,?,?,?,?,?,?)",
               ("r1", "tenant", 0, "task.received", body, "0" * 64, digest))
    db.commit()
    return db, digest


def test_verifies_real_v2_material_and_rejects_direct_update(tmp_path):
    path = str(tmp_path / "chain.db")
    db, root = make_db(path)
    db.close()
    output = verify_chain(path, "tenant", 1, tamper=True)
    assert output["chain_root"] == root
    assert output["tamper_blocked"]


def test_wrong_tenant_or_number_of_records_is_blocked(tmp_path):
    path = str(tmp_path / "chain.db")
    db, _ = make_db(path)
    db.close()
    with pytest.raises(ValueError, match="count"):
        verify_chain(path, "tenant", 2)
    with pytest.raises(ValueError, match="count"):
        verify_chain(path, "other", 1)


def test_tamper_hash_and_producer_binding_are_rejected(tmp_path):
    path = str(tmp_path / "chain.db")
    db, _ = make_db(path)
    db.execute("DROP TRIGGER evidence_no_update")
    db.execute("UPDATE evidence_records SET record_hash=? WHERE id='r1'", ("f" * 64,))
    db.commit()
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_chain(path, "tenant", 1)
    db.execute("UPDATE evidence_records SET record_type='other.type' WHERE id='r1'")
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="binding"):
        verify_chain(path, "tenant", 1)


def test_locked_database_cannot_masquerade_as_trigger_rejection(tmp_path):
    path = str(tmp_path / "locked.db")
    db, _ = make_db(path)
    db.execute("DROP TRIGGER evidence_no_update")
    db.commit()
    db.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(ValueError, match="unrelated"):
            verify_chain(path, "tenant", 1, tamper=True)
    finally:
        db.rollback()
        db.close()
