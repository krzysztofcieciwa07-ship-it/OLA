"""Evidence Cryptography V4 primitives.

V4 uses HMAC-SHA256 with an externally supplied keyring. This module deliberately
does not read keys from the evidence database and never falls back to V1/V2/V3.
Legacy verification is delegated to a separately maintained verifier.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

DOMAIN = "OLA-EVIDENCE-CHAIN-V4"
VERSION = 4
GENESIS_HASH = "0" * 64
KEYRING_ENV = "OLA_EVIDENCE_V4_KEYRING_JSON"
ACTIVE_KEY_ENV = "OLA_EVIDENCE_V4_ACTIVE_KEY_ID"
MAX_PAYLOAD_BYTES = 1_048_576
MAX_JSON_DEPTH = 32
MAX_KEYRING_ENTRIES = 32
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class EvidenceV4Error(ValueError):
    """Base class for fail-closed Evidence V4 errors."""


class MissingKeyError(EvidenceV4Error):
    pass


class UnknownKeyError(EvidenceV4Error):
    pass


class InvalidKeyringError(EvidenceV4Error):
    pass


class InvalidRecordError(EvidenceV4Error):
    pass


@dataclass(frozen=True)
class Keyring:
    keys: Mapping[str, bytes]
    active_key_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.keys, Mapping) or not self.keys:
            raise InvalidKeyringError("empty V4 keyring")
        if len(self.keys) > MAX_KEYRING_ENTRIES:
            raise InvalidKeyringError("too many V4 keys")
        for key_id, key in self.keys.items():
            if not isinstance(key_id, str) or not _KEY_ID_RE.fullmatch(key_id):
                raise InvalidKeyringError("invalid key_id")
            if not isinstance(key, bytes) or len(key) < 32:
                raise InvalidKeyringError("V4 keys must contain at least 256 bits")
        if self.active_key_id not in self.keys:
            raise UnknownKeyError("active V4 key_id is not present in keyring")


def load_keyring(environ: Mapping[str, str] | None = None) -> Keyring:
    """Load base64-encoded key material from environment/secret injection."""
    env = os.environ if environ is None else environ
    raw = env.get(KEYRING_ENV)
    active = env.get(ACTIVE_KEY_ENV)
    if not raw or not active:
        raise MissingKeyError("V4 keyring and active key_id are required")
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise InvalidKeyringError("V4 keyring is not valid JSON") from exc
    if not isinstance(parsed, dict) or not parsed or len(parsed) > MAX_KEYRING_ENTRIES:
        raise InvalidKeyringError("V4 keyring must be a non-empty object")
    keys: dict[str, bytes] = {}
    for key_id, encoded in parsed.items():
        if not isinstance(encoded, str):
            raise InvalidKeyringError("key material must be base64 text")
        try:
            key = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise InvalidKeyringError("invalid base64 key material") from exc
        keys[key_id] = key
    return Keyring(keys=keys, active_key_id=active)


def _check_depth(value: Any, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise InvalidRecordError("payload nesting limit exceeded")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidRecordError("payload object keys must be strings")
            _check_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_depth(item, depth + 1)
    elif isinstance(value, float):
        # Avoid NaN/Infinity and ambiguous cross-runtime number encodings.
        import math
        if not math.isfinite(value):
            raise InvalidRecordError("non-finite JSON number")


def canonical_json(value: Any) -> str:
    _check_depth(value)
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise InvalidRecordError("payload is not canonicalizable JSON") from exc
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise InvalidRecordError("payload size limit exceeded")
    return encoded


def _material(record: Mapping[str, Any]) -> bytes:
    required = (
        "version", "key_id", "tenant_id", "seq", "prev_hash",
        "record_type", "producer", "payload_json",
    )
    if any(name not in record for name in required):
        raise InvalidRecordError("missing V4 authenticated field")
    if type(record["version"]) is not int or record["version"] != VERSION:
        raise InvalidRecordError("unsupported evidence version")
    key_id = record["key_id"]
    if not isinstance(key_id, str) or not _KEY_ID_RE.fullmatch(key_id):
        raise InvalidRecordError("invalid key_id")
    if not isinstance(record["tenant_id"], str) or not record["tenant_id"]:
        raise InvalidRecordError("tenant_id required")
    if type(record["seq"]) is not int or record["seq"] < 0:
        raise InvalidRecordError("invalid sequence")
    if not isinstance(record["prev_hash"], str) or not _HASH_RE.fullmatch(record["prev_hash"]):
        raise InvalidRecordError("invalid predecessor hash")
    if not isinstance(record["record_type"], str) or not record["record_type"]:
        raise InvalidRecordError("record_type required")
    if not isinstance(record["producer"], str) or not record["producer"]:
        raise InvalidRecordError("producer required")
    payload_json = record["payload_json"]
    if not isinstance(payload_json, str) or len(payload_json.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise InvalidRecordError("invalid payload size")
    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError) as exc:
        raise InvalidRecordError("payload_json is invalid JSON") from exc
    if canonical_json(payload) != payload_json:
        raise InvalidRecordError("payload_json is not canonical")
    envelope = {
        "domain": DOMAIN,
        "version": VERSION,
        "key_id": key_id,
        "tenant_id": record["tenant_id"],
        "seq": record["seq"],
        "prev_hash": record["prev_hash"],
        "record_type": record["record_type"],
        "producer": record["producer"],
        "payload_json": payload_json,
    }
    return canonical_json(envelope).encode("utf-8")


def sign_record(record: Mapping[str, Any], keyring: Keyring) -> str:
    """Return lowercase HMAC-SHA256 hex using the active key."""
    material = dict(record)
    material["version"] = VERSION
    material["key_id"] = keyring.active_key_id
    message = _material(material)
    key = keyring.keys.get(keyring.active_key_id)
    if key is None:
        raise UnknownKeyError("active V4 key unavailable")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def verify_record(record: Mapping[str, Any], keyring: Keyring) -> bool:
    """Verify exactly the key_id named by the record; no fallback is permitted."""
    if not isinstance(record, Mapping):
        raise InvalidRecordError("record must be an object")
    key_id = record.get("key_id")
    if not isinstance(key_id, str) or not _KEY_ID_RE.fullmatch(key_id):
        raise InvalidRecordError("invalid key_id")
    key = keyring.keys.get(key_id)
    if key is None:
        raise UnknownKeyError("unknown V4 key_id")
    supplied = record.get("record_hash")
    if not isinstance(supplied, str) or not _HASH_RE.fullmatch(supplied):
        raise InvalidRecordError("invalid record_hash")
    expected = hmac.new(key, _material(record), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


def verify_mixed_chain(
    records: list[Mapping[str, Any]],
    keyring: Keyring,
    *,
    legacy_verifier: Callable[[list[Mapping[str, Any]]], tuple[bool, str]] | None = None,
) -> tuple[bool, str]:
    """Verify contiguous V3/V4 segments; V3 requires an independent legacy verifier.

    V3 history is never reinterpreted as V4. V4 key failures are terminal.
    """
    if not isinstance(records, list) or not records:
        return False, "empty evidence chain"
    expected_seq = 0
    expected_prev = GENESIS_HASH
    legacy_segment: list[Mapping[str, Any]] = []

    def flush_legacy() -> tuple[bool, str]:
        nonlocal legacy_segment
        if not legacy_segment:
            return True, "ok"
        if legacy_verifier is None:
            return False, "legacy V3 verifier unavailable"
        result = legacy_verifier(legacy_segment)
        legacy_segment = []
        if not isinstance(result, tuple) or len(result) != 2 or result[0] is not True:
            return False, "legacy V3 verification failed"
        return True, str(result[1])

    for record in records:
        if not isinstance(record, Mapping):
            return False, "invalid record"
        if record.get("seq") != expected_seq or record.get("prev_hash") != expected_prev:
            return False, "sequence or predecessor mismatch"
        version = record.get("version")
        if version == 3:
            ok, reason = flush_legacy() if record.get("version") != 3 else (True, "ok")
            if not ok:
                return False, reason
            legacy_segment.append(record)
        elif version == 4:
            ok, reason = flush_legacy()
            if not ok:
                return False, reason
            try:
                if not verify_record(record, keyring):
                    return False, "V4 authentication failed"
            except EvidenceV4Error as exc:
                return False, str(exc)
        else:
            return False, "unsupported evidence version"
        expected_prev = record.get("record_hash")
        if not isinstance(expected_prev, str) or not _HASH_RE.fullmatch(expected_prev):
            return False, "invalid record_hash"
        expected_seq += 1
    return flush_legacy()
