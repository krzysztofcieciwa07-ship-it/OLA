"""Independent chain verification and append-only-negative checks."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from staging_verify import verify_chain


def fixture_db(path):
    con = sqlite3.connect(path)
    con.executescript('''
    CREATE TABLE evidence_records(
        id TEXT PRIMARY KEY, tenant_id TEXT, seq INT, record_type TEXT,
        payload_json TEXT, prev_hash TEXT, record_hash TEXT
    );
    CREATE TRIGGER evidence_no_update BEFORE UPDATE ON evidence_records
      BEGIN SELECT RAISE(ABORT,'append-only'); END;
    ''')
    payload_json = json.dumps({
        'test': True, '__ola_evidence_v2__':
        {'version':2,'record_type':'task.received','producer':'ola_runtime'}
    }, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    anchor='0'*64
    data=json.dumps({'domain':'OLA-EVIDENCE-CHAIN-V2','tenant_id':'tenant-1',
                     'seq':0,'prev_hash':anchor,'record_type':'task.received',
                     'producer':'ola_runtime','payload_json':payload_json},
                     sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    digest=hashlib.sha256(data.encode()).hexdigest()
    con.execute('INSERT INTO evidence_records VALUES(?,?,?,?,?,?,?)',
                ('evidence-1','tenant-1',0,'task.received',payload_json,anchor,digest))
    con.commit()
    return con, digest


def test_verifies_clean_chain_and_blocks_tamper(tmp_path):
    con, root=fixture_db(str(tmp_path/'chain.db'))
    con.close()
    result=verify_chain(str(tmp_path/'chain.db'),'tenant-1',1,tamper=True)
    assert result['status']=='VERIFIED' and result['chain_root']==root
    assert result['tamper_blocked'] is True


def test_wrong_count_and_wrong_tenant_fail_closed(tmp_path):
    con,_=fixture_db(str(tmp_path/'chain.db'))
    con.close()
    with pytest.raises(ValueError,match='count mismatch'):
        verify_chain(str(tmp_path/'chain.db'),'tenant-1',2)
    with pytest.raises(ValueError,match='count mismatch'):
        verify_chain(str(tmp_path/'chain.db'),'another-tenant',1)


def test_corrupted_record_hash_rejected(tmp_path):
    con,_=fixture_db(str(tmp_path/'chain.db'))
    con.execute('DROP TRIGGER evidence_no_update')
    con.execute("UPDATE evidence_records SET record_hash='f' WHERE tenant_id='tenant-1'")
    con.commit()
    con.close()
    with pytest.raises(ValueError,match='record hash mismatch'):
        verify_chain(str(tmp_path/'chain.db'),'tenant-1',1)


def test_producer_spoofing_rejected(tmp_path):
    con,_=fixture_db(str(tmp_path/'chain.db'))
    con.execute('DROP TRIGGER evidence_no_update')
    con.execute("UPDATE evidence_records SET record_type='other.event'")
    con.commit()
    con.close()
    with pytest.raises(ValueError,match='provenance binding'):
        verify_chain(str(tmp_path/'chain.db'),'tenant-1',1)


def test_missing_append_only_trigger_fails_without_changing_any_record(tmp_path):
    path = tmp_path / "chain.db"
    con, _ = fixture_db(str(path))
    old_payload = con.execute("SELECT payload_json FROM evidence_records WHERE id='evidence-1'").fetchone()[0]
    con.execute("DROP TRIGGER evidence_no_update")
    con.commit()
    con.close()
    with pytest.raises(ValueError, match="tamper update was not rejected"):
        verify_chain(str(path), "tenant-1", 1, tamper=True)
    con = sqlite3.connect(path)
    new_payload = con.execute("SELECT payload_json FROM evidence_records WHERE id='evidence-1'").fetchone()[0]
    con.close()
    assert new_payload == old_payload, "negative test must not itself corrupt source evidence"
