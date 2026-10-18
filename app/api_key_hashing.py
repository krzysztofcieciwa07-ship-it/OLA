"""Keyed API-key fingerprints. No legacy SHA-256 fallback."""
import hashlib
import os


def api_key_fingerprint(raw_key: str) -> str:
    if not isinstance(raw_key, str) or not raw_key:
        raise ValueError("API key required")
    pepper = os.environ.get("OLA_API_KEY_PEPPER", "")
    if len(pepper.encode("utf-8")) < 32:
        raise RuntimeError("API key hashing secret is not configured")
    return hashlib.scrypt(raw_key.encode("utf-8"), salt=pepper.encode("utf-8"),
                         n=1 << 14, r=8, p=1, maxmem=64 * 1024 * 1024,
                         dklen=32).hex()
