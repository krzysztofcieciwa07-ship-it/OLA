"""Normative RFC 8785 JSON Canonicalization Scheme helpers for OLA v3 evidence."""

import hashlib
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
