import base64
import json

import pytest

from app.evidence_v4 import (
    ACTIVE_KEY_ENV, KEYRING_ENV, GENESIS_HASH, Keyring, MissingKeyError,
    InvalidKeyringError, UnknownKeyError, canonical_json, load_keyring, sign_record, verify_record,
    verify_mixed_chain,
)

KEY_A = b"a" * 32
KEY_B = b"b" * 32


def _ring(active="k1", keys=None):
    return Keyring(keys=keys or {"k1": KEY_A, "k2": KEY_B}, active_key_id=active)


def _record(seq=0, prev=GENESIS_HASH, keyring=None, payload=None):
    ring = keyring or _ring()
    record = {
        "version": 4, "key_id": ring.active_key_id, "tenant_id": "tenant-a",
        "seq": seq, "prev_hash": prev, "record_type": "provenance.runtime",
        "producer": "ola_runtime",
        "payload_json": canonical_json(payload or {"run_id": "r1", "result": 391}),
    }
    record["record_hash"] = sign_record(record, ring)
    return record


def test_v4_sign_and_verify():
    ring = _ring()
    assert verify_record(_record(keyring=ring), ring)


def test_rotation_keeps_old_key_for_history_and_new_key_for_writes():
    old = _ring("k1")
    new = _ring("k2")
    first = _record(keyring=old)
    second = _record(1, first["record_hash"], new)
    assert verify_record(first, new)
    assert verify_record(second, new)
    assert second["key_id"] == "k2"


def test_unknown_key_id_fails_closed():
    record = _record()
    record["key_id"] = "not-in-keyring"
    with pytest.raises(UnknownKeyError):
        verify_record(record, _ring())


def test_key_substitution_is_detected():
    record = _record()
    record["key_id"] = "k2"
    assert not verify_record(record, _ring())


def test_missing_keyring_fails_closed():
    with pytest.raises(MissingKeyError):
        load_keyring({})


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
    env = {
        KEYRING_ENV: '{"k1":"' + base64.b64encode(KEY_A).decode() + '","k1":"' + base64.b64encode(KEY_B).decode() + '"}',
        ACTIVE_KEY_ENV: "k1",
    }
    with pytest.raises(InvalidKeyringError):
        load_keyring(env)


def test_restart_reloads_same_external_keyring():
    env = {
        KEYRING_ENV: json.dumps({"k1": base64.b64encode(KEY_A).decode()}),
        ACTIVE_KEY_ENV: "k1",
    }
    before = load_keyring(env)
    after = load_keyring(dict(env))
    record = _record(keyring=before)
    assert verify_record(record, after)


def test_mixed_v3_v4_requires_explicit_legacy_verifier():
    v3 = {
        "version": 3, "seq": 0, "prev_hash": GENESIS_HASH,
        "record_hash": "1" * 64, "tenant_id": "tenant-a",
    }
    v4 = _record(1, "1" * 64)
    assert verify_mixed_chain([v3, v4], _ring())[0] is False
    ok, _ = verify_mixed_chain(
        [v3, v4], _ring(), legacy_verifier=lambda segment: (segment == [v3], "fixture-ok")
    )
    assert ok


def test_payload_canonicalization_is_stable():
    assert canonical_json({"z": 1, "a": 2}) == '{"a":2,"z":1}'


def test_noncanonical_payload_is_rejected():
    record = _record()
    # Whitespace makes this JSON semantically equivalent but not canonical.
    record["payload_json"] = '{ "result":391,"run_id":"r1"}'
    with pytest.raises(ValueError, match="payload_json is not canonical"):
        verify_record(record, _ring())


def test_duplicate_payload_json_members_are_rejected():
    record = _record()
    record["payload_json"] = '{"result":391,"result":392,"run_id":"r1"}'
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        verify_record(record, _ring())


def test_key_loss_fails_closed_without_legacy_fallback():
    signed = _record(keyring=_ring("k1"))
    no_old_key = Keyring(keys={"k2": KEY_B}, active_key_id="k2")
    with pytest.raises(UnknownKeyError):
        verify_record(signed, no_old_key)


def test_backup_restore_preserves_verifiability_with_restored_secret():
    original = _ring("k1")
    record = _record(keyring=original)
    evidence_backup = json.dumps(record, sort_keys=True)
    secret_backup = {
        KEYRING_ENV: json.dumps({
            "k1": base64.b64encode(KEY_A).decode(),
            "k2": base64.b64encode(KEY_B).decode(),
        }),
        ACTIVE_KEY_ENV: "k2",
    }
    restored_record = json.loads(evidence_backup)
    restored_keyring = load_keyring(secret_backup)
    assert verify_record(restored_record, restored_keyring)
