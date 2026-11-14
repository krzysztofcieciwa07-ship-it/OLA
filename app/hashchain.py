"""OLA Evidence Chain v2 with read-only legacy V1 integrity compatibility.

The producer is selected by the authenticated server write boundary.
It is NOT an external cryptographic identity or a third-party attestation.
"""
import hashlib
import hmac
import json
import os

GENESIS_HASH = "0" * 64
EVIDENCE_META_KEY = "__ola_evidence_v2__"
TRUSTED_PRODUCER = "ola_runtime"
PUBLIC_PRODUCER = "tenant_api"
PRIVILEGED_PREFIXES = ("workflow.", "task.", "human.", "agent.",
                       "provenance.", "decision.", "execution.", "verification.",
                       "stripe.", "revenue.")


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def is_privileged_type(record_type):
    return isinstance(record_type, str) and record_type.startswith(PRIVILEGED_PREFIXES)


def sealed_payload_json(record_type, payload, *, producer=TRUSTED_PRODUCER, version=2):
    """Seal type and server-selected producer inside canonical hash material."""
    if not isinstance(record_type, str) or not record_type.strip():
        raise ValueError("evidence record type required")
    if not isinstance(payload, dict) or EVIDENCE_META_KEY in payload:
        raise ValueError("evidence must be object without reserved metadata")
    if producer not in (TRUSTED_PRODUCER, PUBLIC_PRODUCER):
        raise ValueError("unknown evidence producer")
    if type(version) is not int or version not in (2, 3):
        raise ValueError("unsupported evidence version")
    if is_privileged_type(record_type) and producer != TRUSTED_PRODUCER:
        raise ValueError("public producer may not write privileged evidence")
    value = dict(payload)
    value[EVIDENCE_META_KEY] = {
        "version": version, "record_type": record_type, "producer": producer,
    }
    return canonical_json(value)


def _binding(record):
    """(bound, valid); no v2 metadata means legacy integrity-only V1."""
    try:
        payload = json.loads(record["payload_json"])
    except (ValueError, TypeError, KeyError):
        return False, False
    if not isinstance(payload, dict):
        return False, False
    metadata = payload.get(EVIDENCE_META_KEY)
    if metadata is None:
        return False, True
    if not isinstance(metadata, dict) or set(metadata) != {"version", "record_type", "producer"}:
        return True, False
    producer = metadata["producer"]
    record_type = record.get("record_type")
    valid = (
        type(metadata["version"]) is int and metadata["version"] in (2, 3)
        and isinstance(record_type, str) and bool(record_type)
        and metadata["record_type"] == record_type
        and producer in (TRUSTED_PRODUCER, PUBLIC_PRODUCER)
        and (not is_privileged_type(record_type) or producer == TRUSTED_PRODUCER)
    )
    return True, valid


def trusted_record(record):
    """Only after full-chain verification; legacy events never grant execution trust."""
    bound, valid = _binding(record)
    if not (bound and valid):
        return False
    data = json.loads(record["payload_json"])
    return (data[EVIDENCE_META_KEY]["producer"] == TRUSTED_PRODUCER
            and is_privileged_type(record.get("record_type")))


def compute_record_hash(tenant_id, seq, prev_hash, payload_json):
    material = f"{tenant_id}|{seq}|{prev_hash}|{payload_json}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def compute_record_hash_v2(tenant_id, seq, prev_hash, record_type, producer, payload_json):
    """Domain-separated V2: historical V1 digests cannot be reinterpreted."""
    material = canonical_json({
        "domain": "OLA-EVIDENCE-CHAIN-V2",
        "tenant_id": tenant_id, "seq": seq, "prev_hash": prev_hash,
        "record_type": record_type, "producer": producer, "payload_json": payload_json,
    }).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _evidence_chain_key():
    """Derive a domain-separated evidence key from the required server-side pepper."""
    master = os.environ.get("OLA_API_KEY_PEPPER", "").encode("utf-8")
    if len(master) < 32:
        raise RuntimeError("evidence chain key is not configured")
    return hmac.new(master, b"OLA-EVIDENCE-CHAIN-KEY-V3", hashlib.sha256).digest()


def compute_record_hash_v3(tenant_id, seq, prev_hash, record_type, producer, payload_json):
    """Keyed V3 commitment; database readers cannot test payload guesses offline."""
    material = canonical_json({
        "domain": "OLA-EVIDENCE-CHAIN-V3",
        "tenant_id": tenant_id, "seq": seq, "prev_hash": prev_hash,
        "record_type": record_type, "producer": producer, "payload_json": payload_json,
    }).encode("utf-8")
    return hmac.new(_evidence_chain_key(), material, hashlib.sha256).hexdigest()


def verify_chain(records):
    expected_prev = GENESIS_HASH
    expected_seq = 0
    for row in records:
        if row["seq"] != expected_seq or row["prev_hash"] != expected_prev:
            return False, "sequence or predecessor mismatch"
        bound, valid = _binding(row)
        if not valid:
            return False, "record type or producer binding mismatch"
        if bound:
            metadata = json.loads(row["payload_json"])[EVIDENCE_META_KEY]
            if metadata["version"] == 3:
                try:
                    expected = compute_record_hash_v3(
                        row["tenant_id"], row["seq"], row["prev_hash"],
                        row["record_type"], metadata["producer"], row["payload_json"]
                    )
                except RuntimeError:
                    return False, "evidence chain key is not configured"
            else:
                expected = compute_record_hash_v2(
                    row["tenant_id"], row["seq"], row["prev_hash"],
                    row["record_type"], metadata["producer"], row["payload_json"]
                )
        else:
            expected = compute_record_hash(row["tenant_id"], row["seq"],
                                           row["prev_hash"], row["payload_json"])
        if row["record_hash"] != expected:
            return False, "record hash mismatch"
        expected_prev = row["record_hash"]
        expected_seq += 1
    return True, "ok"
