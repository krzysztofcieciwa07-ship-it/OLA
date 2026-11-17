import base64
import json

import pytest

from app.evidence_v4 import (
    ACTIVE_KEY_ENV, KEYRING_ENV, GENESIS_HASH, V2_META_KEY, V4_META_KEY,
    Keyring, MissingKeyError, InvalidKeyringError, UnknownKeyError,
    canonical_json, load_keyring, seal_payload_v4, sign_record, verify_record,
    verify_mixed_chain,
)

KEY_A = b"a" * 32
KEY_B = b"b" * 32


def _ring(active="k1", keys=None):
    return Keyring(keys=keys or {"k1": KEY_A, "k2": KEY_B}, active_key_id=active)


def _record(seq=0, prev=GENESIS_HASH, keyring=None, payload=None, record_type="provenance.runtime"):
    ring = keyring or _ring()
    row = {
        "tenant_id": "tenant-a",
        "seq": seq,
        "prev_hash": prev,
        "record_type": record_type,
        "payload_json": seal_payload_v4(record_type, payload or {"run_id": "r1", "result": 391}, ring),
    }
    row["record_hash"] = sign_record(row, ring)
    return row


def _legacy(version, seq, prev, digest):
    if version == 1:
        payload = {"run_id": "legacy"}
    else:
        payload = {
            "run_id": "legacy",
            V2_META_KEY: {
                "version": version,
                "record_type": "task.received",
                "producer": "ola_runtime",
            },
        }
    return {
        "tenant_id": "tenant-a", "seq": seq, "prev_hash": prev,
        "record_type": "task.received", "payload_json": canonical_json(payload),
        "record_hash": digest,
    }


def test_v4_sign_and_verify_with_existing_database_record_shape():
    ring = _ring()
    row = _record(keyring=ring)
    payload = json.loads(row["payload_json"])
    assert set(row) == {"tenant_id", "seq", "prev_hash", "record_type", "payload_json", "record_hash"}
    assert payload[V4_META_KEY] == {
        "version": 4, "key_id": "k1", "record_type": "provenance.runtime",
        "producer": "ola_runtime",
    }
    assert verify_record(row, ring)


def test_rotation_keeps_old_key_for_history_and_new_key_for_writes():
    old = _ring("k1")
    new = _ring("k2")
    first = _record(keyring=old)
    second = _record(1, first["record_hash"], new)
    assert verify_record(first, new)
    assert verify_record(second, new)
    assert json.loads(second["payload_json"])[V4_META_KEY]["key_id"] == "k2"


def test_unknown_key_id_fails_closed():
    row = _record()
    payload = json.loads(row["payload_json"])
    payload[V4_META_KEY]["key_id"] = "missing"
    row["payload_json"] = canonical_json(payload)
    with pytest.raises(UnknownKeyError):
        verify_record(row, _ring())


def test_key_substitution_is_detected():
    row = _record()
    payload = json.loads(row["payload_json"])
    payload[V4_META_KEY]["key_id"] = "k2"
    row["payload_json"] = canonical_json(payload)
    assert not verify_record(row, _ring())


def test_missing_keyring_fails_closed():
    with pytest.raises(MissingKeyError):
        load_keyring({})


def test_restart_reloads_same_external_keyring():
    env = {
        KEYRING_ENV: json.dumps({"k1": base64.b64encode(KEY_A).decode()}),
        ACTIVE_KEY_ENV: "k1",
    }
    before = load_keyring(env)
    after = load_keyring(dict(env))
    row = _record(keyring=before)
    assert verify_record(row, after)


def test_keyring_copies_and_freezes_caller_mapping():
    supplied = {"k1": KEY_A}
    ring = Keyring(keys=supplied, active_key_id="k1")
    supplied["k1"] = KEY_B
    supplied["k2"] = KEY_B
    assert ring.keys["k1"] == KEY_A
    assert "k2" not in ring.keys
    with pytest.raises(TypeError):
        ring.keys["k1"] = KEY_B


def test_duplicate_keyring_json_members_are_rejected():
    encoded_a = base64.b64encode(KEY_A).decode()
    encoded_b = base64.b64encode(KEY_B).decode()
    env = {
        KEYRING_ENV: '{"k1":"' + encoded_a + '","k1":"' + encoded_b + '"}',
        ACTIVE_KEY_ENV: "k1",
    }
    with pytest.raises(InvalidKeyringError):
        load_keyring(env)


def test_payload_canonicalization_is_stable():
    assert canonical_json({"z": 1, "a": 2}) == '{"a":2,"z":1}'


def test_noncanonical_payload_is_rejected():
    row = _record()
    row["payload_json"] = '{ "result":391,"run_id":"r1","' + V4_META_KEY + '":' + json.dumps(
        json.loads(row["payload_json"])[V4_META_KEY], separators=(",", ":")
    ) + '}'
    with pytest.raises(ValueError, match="payload_json is not canonical"):
        verify_record(row, _ring())


def test_duplicate_payload_json_members_are_rejected():
    row = _record()
    row["payload_json"] = '{"x":1,"x":2}'
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        verify_record(row, _ring())


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "tenant-b"),
    ("seq", 1),
    ("prev_hash", "1" * 64),
    ("record_type", "provenance.changed"),
])
def test_authenticated_record_fields_cannot_be_substituted(field, value):
    row = _record()
    row[field] = value
    assert not verify_record(row, _ring())


def test_payload_mutation_is_detected():
    row = _record()
    payload = json.loads(row["payload_json"])
    payload["result"] = 392
    row["payload_json"] = canonical_json(payload)
    assert not verify_record(row, _ring())


def test_v4_rejects_payload_reserved_metadata_collision():
    with pytest.raises(ValueError, match="reserved evidence metadata"):
        seal_payload_v4("task.received", {V2_META_KEY: {}}, _ring())


def test_key_loss_fails_closed_without_legacy_fallback():
    signed = _record(keyring=_ring("k1"))
    no_old_key = Keyring(keys={"k2": KEY_B}, active_key_id="k2")
    with pytest.raises(UnknownKeyError):
        verify_record(signed, no_old_key)


def test_backup_restore_preserves_verifiability_with_restored_secret():
    original = _ring("k1")
    row = _record(keyring=original)
    evidence_backup = json.dumps(row, sort_keys=True)
    secret_backup = {
        KEYRING_ENV: json.dumps({
            "k1": base64.b64encode(KEY_A).decode(),
            "k2": base64.b64encode(KEY_B).decode(),
        }),
        ACTIVE_KEY_ENV: "k2",
    }
    restored_row = json.loads(evidence_backup)
    restored_keyring = load_keyring(secret_backup)
    assert verify_record(restored_row, restored_keyring)


def test_mixed_v3_v4_requires_explicit_legacy_verifier():
    v3 = _legacy(3, 0, GENESIS_HASH, "1" * 64)
    v4 = _record(1, "1" * 64)
    assert verify_mixed_chain([v3, v4], _ring())[0] is False
    ok, _ = verify_mixed_chain(
        [v3, v4], _ring(), legacy_verifier=lambda segment: (segment == [v3], "legacy-fixture-ok")
    )
    assert ok


def test_mixed_v1_v2_v3_v4_keeps_continuity_across_legacy_boundary():
    v1 = _legacy(1, 0, GENESIS_HASH, "1" * 64)
    v2 = _legacy(2, 1, "1" * 64, "2" * 64)
    v3 = _legacy(3, 2, "2" * 64, "3" * 64)
    v4 = _record(3, "3" * 64)
    seen = []

    def verify_legacy(segment):
        seen.append([_version(item) for item in segment])
        return True, "verified-by-test-legacy-adapter"

    assert verify_mixed_chain([v1, v2, v3, v4], _ring(), legacy_verifier=verify_legacy)[0]
    assert seen == [[1, 2, 3]]


def _version(row):
    payload = json.loads(row["payload_json"])
    if V2_META_KEY not in payload:
        return 1
    return payload[V2_META_KEY]["version"]


def test_legacy_verifier_exceptions_fail_closed():
    v3 = _legacy(3, 0, GENESIS_HASH, "1" * 64)
    ok, reason = verify_mixed_chain(
        [v3], _ring(), legacy_verifier=lambda _segment: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert not ok
    assert reason == "legacy verifier raised an exception"
