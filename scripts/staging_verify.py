#!/usr/bin/env python3
"""Independent V1/V2/V3 evidence verifier, without importing producer code."""
import argparse
import hashlib
import hmac
import json
import os
import sqlite3
import sys


def verify_chain(db_path, tenant_id, expected_count, *, tamper=False):
    with sqlite3.connect(db_path, timeout=1.0) as conn:
        rows = conn.execute(
            "SELECT id, tenant_id, seq, record_type, payload_json, prev_hash, record_hash "
            "FROM evidence_records WHERE tenant_id=? ORDER BY seq", (tenant_id,)
        ).fetchall()
        if expected_count < 1 or len(rows) != expected_count:
            raise ValueError("record count mismatch")
        previous = "0" * 64
        for expected_seq, (record_id, tenant, seq, record_type, payload, prev, digest) in enumerate(rows):
            if tenant != tenant_id or seq != expected_seq or prev != previous:
                raise ValueError("sequence or predecessor mismatch")
            value = json.loads(payload)
            metadata = value.get("__ola_evidence_v2__")
            if (not isinstance(metadata, dict)
                    or set(metadata) != {"version", "record_type", "producer"}
                    or metadata.get("version") not in (2, 3)
                    or metadata.get("record_type") != record_type
                    or metadata.get("producer") != "ola_runtime"):
                raise ValueError("untrusted record type or producer binding")
            domain = "OLA-EVIDENCE-CHAIN-V3" if metadata["version"] == 3 else "OLA-EVIDENCE-CHAIN-V2"
            material = json.dumps({
                "domain": domain, "tenant_id": tenant,
                "seq": seq, "prev_hash": prev, "record_type": record_type,
                "producer": "ola_runtime", "payload_json": payload,
            }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            if metadata["version"] == 3:
                master = os.environ.get("OLA_API_KEY_PEPPER", "").encode("utf-8")
                if len(master) < 32:
                    raise ValueError("evidence chain key is not configured")
                key = hmac.new(master, b"OLA-EVIDENCE-CHAIN-KEY-V3", hashlib.sha256).digest()
                expected = hmac.new(key, material, hashlib.sha256).hexdigest()
            else:
                expected = hashlib.sha256(material).hexdigest()
            if expected != digest:
                raise ValueError("record hash mismatch")
            previous = digest
        if tamper:
            try:
                conn.execute(
                    "UPDATE evidence_records SET payload_json=? WHERE id=?",
                    ('{"tampered":true}', rows[0][0]),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                if str(exc) != "evidence_records is append-only":
                    raise ValueError("unrelated database integrity failure") from exc
            except sqlite3.DatabaseError as exc:
                conn.rollback()
                raise ValueError("unrelated database write failure") from exc
            else:
                raise ValueError("append-only trigger did not block tamper")
        return {
            "status": "VERIFIED", "records": len(rows),
            "chain_root": previous, "tamper_blocked": bool(tamper),
        }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--expected-count", type=int, required=True)
    p.add_argument("--tamper-check", action="store_true")
    p.add_argument("--db", default=os.getenv("OLA_EG_DB_PATH", "/data/ola.db"))
    args = p.parse_args()
    try:
        result = verify_chain(args.db, args.tenant_id, args.expected_count,
                              tamper=args.tamper_check)
    except (ValueError, sqlite3.DatabaseError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
