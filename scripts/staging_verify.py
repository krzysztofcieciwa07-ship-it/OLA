#!/usr/bin/env python3
"""Independent read-only verifier of the local V2 SQLite chain.

This does NOT import the producer's hash helpers. Tamper testing uses a
reversible failed UPDATE, never writes to an evidence record.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys


def verify_chain(db_path: str, tenant_id: str, expected_count: int, *, tamper: bool = False):
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id,tenant_id,seq,record_type,payload_json,prev_hash,record_hash "
            "FROM evidence_records WHERE tenant_id=? ORDER BY seq", (tenant_id,)
        ).fetchall()
        if len(rows) != expected_count or expected_count < 1:
            raise ValueError("record count mismatch")
        previous = "0" * 64
        for expected_seq, (rid, tid, seq, kind, body, prev_hash, record_hash) in enumerate(rows):
            if tid != tenant_id or seq != expected_seq or prev_hash != previous:
                raise ValueError("sequence or predecessor mismatch")
            payload = json.loads(body)
            meta = payload.get("__ola_evidence_v2__")
            if meta != {"version": 2, "record_type": kind, "producer": "ola_runtime"}:
                raise ValueError("untrusted or missing V2 provenance binding")
            material = json.dumps({
                "domain": "OLA-EVIDENCE-CHAIN-V2",
                "tenant_id": tid,
                "seq": seq,
                "prev_hash": prev_hash,
                "record_type": kind,
                "producer": "ola_runtime",
                "payload_json": body,
            }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
            if digest != record_hash:
                raise ValueError("record hash mismatch")
            previous = digest
        if tamper:
            # Database-level append-only guard must reject direct mutations.
            try:
                conn.execute(
                    "UPDATE evidence_records SET payload_json=? WHERE id=?",
                    ('{"unauthorized":true}', rows[0][0]),
                )
                conn.commit()
            except sqlite3.DatabaseError:
                conn.rollback()
            else:
                raise ValueError("tamper update was not rejected")
        return {"status": "VERIFIED", "tenant_id": tenant_id,
                "records": len(rows), "chain_root": previous,
                "tamper_blocked": bool(tamper)}
    finally:
        conn.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--expected-count", type=int, required=True)
    p.add_argument("--tamper-check", action="store_true")
    p.add_argument("--db", default=os.getenv("OLA_EG_DB_PATH", "/data/ola.db"))
    opts = p.parse_args()
    try:
        out = verify_chain(opts.db, opts.tenant_id, opts.expected_count, tamper=opts.tamper_check)
        print(json.dumps(out, sort_keys=True))
    except (ValueError, sqlite3.DatabaseError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
