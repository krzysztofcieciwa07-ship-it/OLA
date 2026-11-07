"""Signing interfaces for independent IGOR and OLA customer-bundle attestations.

Production adapters call separate remote signer services. No production private
key is loaded into the OLA API process. Test-only local Ed25519 keys are marked
so the production bundle profile can reject them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class BundleSignerRejected(ValueError):
    pass


@runtime_checkable
class Ed25519Signer(Protocol):
    key_id: str
    custody_id: str
    test_only: bool

    @property
    def public_key_bytes(self) -> bytes: ...

    def sign(self, message: bytes) -> bytes: ...


@dataclass
class TestOnlyEd25519Signer:
    """In-memory signer for CI only. Never use for production customer bundles."""
    key_id: str
    custody_id: str
    _ed25519_signer: Ed25519PrivateKey
    test_only: bool = True

    @classmethod
    def generate(cls, *, key_id: str, custody_id: str) -> "TestOnlyEd25519Signer":
        if not key_id or not custody_id:
            raise BundleSignerRejected("test signer key and custody IDs are required")
        return cls(
            key_id=key_id,
            custody_id=custody_id,
            _ed25519_signer=Ed25519PrivateKey.generate(),
        )

    @property
    def public_key_bytes(self) -> bytes:
        return self._ed25519_signer.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def sign(self, message: bytes) -> bytes:
        if not isinstance(message, bytes):
            raise BundleSignerRejected("Ed25519 signer accepts exact message bytes")
        return self._ed25519_signer.sign(message)


@dataclass(frozen=True)
class RemoteEd25519Signer:
    """Adapter to a remote KMS/HSM signer owned by a separate service principal.

    The callback must call the configured signing service and return the raw
    64-byte Ed25519 signature. This object contains only public key metadata
    and a callable transport boundary, never a private key.
    """
    key_id: str
    custody_id: str
    public_key_bytes: bytes
    sign_request: Callable[[str, bytes], bytes]
    test_only: bool = False

    def __post_init__(self):
        if not self.key_id or not self.custody_id or not callable(self.sign_request):
            raise BundleSignerRejected("remote signer metadata and callable are required")
        if not isinstance(self.public_key_bytes, bytes) or len(self.public_key_bytes) != 32:
            raise BundleSignerRejected("remote Ed25519 public key must be exactly 32 bytes")

    def sign(self, message: bytes) -> bytes:
        if not isinstance(message, bytes):
            raise BundleSignerRejected("Ed25519 signer accepts exact message bytes")
        signature = self.sign_request(self.key_id, message)
        if not isinstance(signature, bytes) or len(signature) != 64:
            raise BundleSignerRejected("remote signing service returned an invalid Ed25519 signature")
        return signature
