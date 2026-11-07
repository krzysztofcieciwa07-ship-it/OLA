"""Private bundle storage interfaces and sandbox-only encrypted local adapter."""
from __future__ import annotations

import base64
import os
import re
import secrets
import uuid
from pathlib import Path
from typing import Protocol, runtime_checkable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CustomerBundleStorageRejected(ValueError):
    pass


@runtime_checkable
class CustomerBundleStorage(Protocol):
    def put(self, payload: bytes) -> str: ...
    def get(self, object_ref: str) -> bytes: ...


class EncryptedLocalBundleStorage:
    """Sandbox-only AES-256-GCM file adapter; never selected for public HTTPS/production."""

    _REF_RE = re.compile(r"^local-encrypted://([0-9a-f]{32})\.olb$")

    def __init__(self, *, root: str | Path, key: bytes):
        if not isinstance(key, bytes) or len(key) != 32:
            raise CustomerBundleStorageRejected("AES-256-GCM storage key must be exactly 32 bytes")
        self.root = Path(root).expanduser().resolve()
        self.cipher = AESGCM(key)

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.root.chmod(0o700)
        except OSError as exc:
            raise CustomerBundleStorageRejected("private bundle storage permissions could not be enforced") from exc

    def put(self, payload: bytes) -> str:
        if not isinstance(payload, bytes) or not payload:
            raise CustomerBundleStorageRejected("bundle payload must be nonempty bytes")
        self._ensure_root()
        object_id = uuid.uuid4().hex
        filename = object_id + ".olb"
        nonce = secrets.token_bytes(12)
        ciphertext = b"OLAB1" + nonce + self.cipher.encrypt(nonce, payload, filename.encode("ascii"))
        target = self.root / filename
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(target, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(ciphertext)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise CustomerBundleStorageRejected("encrypted bundle object could not be persisted") from exc
        return "local-encrypted://" + filename

    def get(self, object_ref: str) -> bytes:
        match = self._REF_RE.fullmatch(object_ref or "")
        if match is None:
            raise CustomerBundleStorageRejected("bundle object reference is invalid")
        filename = match.group(1) + ".olb"
        target = self.root / filename
        try:
            stat_result = target.lstat()
            if not target.is_file() or target.is_symlink():
                raise CustomerBundleStorageRejected("bundle object is not a regular private file")
            if stat_result.st_mode & 0o077:
                raise CustomerBundleStorageRejected("bundle object permissions are too broad")
            encoded = target.read_bytes()
        except FileNotFoundError as exc:
            raise CustomerBundleStorageRejected("bundle object was not found") from exc
        except OSError as exc:
            raise CustomerBundleStorageRejected("bundle object could not be read") from exc
        if len(encoded) < 5 + 12 + 16 or not encoded.startswith(b"OLAB1"):
            raise CustomerBundleStorageRejected("encrypted bundle object format is invalid")
        nonce, ciphertext = encoded[5:17], encoded[17:]
        try:
            return self.cipher.decrypt(nonce, ciphertext, filename.encode("ascii"))
        except Exception as exc:
            raise CustomerBundleStorageRejected("encrypted bundle object authentication failed") from exc


def customer_bundle_storage_from_environment(*, profile: str) -> CustomerBundleStorage | None:
    """Return a local adapter only in a non-production loopback profile.

    Production deliberately has no implicit filesystem fallback. A remote
    encrypted object-store adapter must be explicitly integrated and reviewed.
    """
    public_base = os.environ.get("OLA_PUBLIC_BASE_URL", "").strip().lower()
    if profile in {"production", "invalid"} or public_base.startswith("https://"):
        return None
    if profile not in {"sandbox", "test", "development"}:
        return None
    root = os.environ.get("OLA_CUSTOMER_BUNDLE_STORAGE_PATH")
    encoded_key = os.environ.get("OLA_CUSTOMER_BUNDLE_STORAGE_KEY")
    if not root or not encoded_key:
        return None
    try:
        key = base64.urlsafe_b64decode(encoded_key + "=" * (-len(encoded_key) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise CustomerBundleStorageRejected("bundle storage key encoding is invalid") from exc
    return EncryptedLocalBundleStorage(root=root, key=key)
