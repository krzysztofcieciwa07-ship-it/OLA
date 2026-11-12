"""Normative RFC 8785 JSON Canonicalization Scheme helpers for OLA v3 evidence."""

import hashlib
import json
from typing import Any

import rfc8785


def canonical_json(value: Any) -> str:
    """Return RFC 8785 canonical JSON as UTF-8 text."""
    try:
        return rfc8785.dumps(value).decode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("value is not valid RFC 8785 JSON data") from exc


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _unique_object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_nonfinite_constant(value):
    raise ValueError("non-finite JSON constant is not allowed")


def parse_json_object(value: str, *, max_bytes: int = 16384) -> dict:
    """Parse a bounded JSON object; reject duplicate keys and NaN/Infinity."""
    if not isinstance(value, str):
        raise ValueError("JSON object must be text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("JSON object must be valid UTF-8") from None
    if not encoded or len(encoded) > max_bytes:
        raise ValueError("JSON object is empty or exceeds its size limit")
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=_unique_object_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        raise ValueError("JSON object is invalid or non-canonical") from None
    if not isinstance(parsed, dict):
        raise ValueError("JSON value must be an object")
    return parsed
