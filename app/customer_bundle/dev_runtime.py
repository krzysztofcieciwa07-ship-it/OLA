"""Loopback-only, explicitly non-production customer-bundle runtime.

This module derives stable test-only Ed25519 keys with HKDF so local
Development bundles remain verifiable across API restarts. The keys are not
independent custody and are never valid for the production bundle profile.
"""
from __future__ import annotations

import base64
import binascii
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.customer_bundle.builder import SANDBOX_PROFILE
from app.customer_bundle.service import CustomerBundleRuntime
from app.customer_bundle.signers import TestOnlyEd25519Signer
from app.customer_bundle.storage import EncryptedLocalBundleStorage


_STORAGE_KEY_NAME = "OLA_CUSTOMER_BUNDLE_STORAGE_KEY"
_SESSION_KEY_NAME = "OLA_HUMAN_SESSION_ENCRYPTION_KEY"
_DERIVATION_SALT = b"OLA-DIOS-DEVELOPMENT-BUNDLE-SIGNING-V1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _decode_32_byte_base64(value: object) -> bytes | None:
    if not isinstance(value, str) or not value or len(value) > 128:
        return None
    try:
        encoded = value.encode("ascii")
        padded = encoded + b"=" * (-len(encoded) % 4)
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error):
        return None
    return decoded if len(decoded) == 32 else None


def _development_origin_is_loopback(environment: dict[str, str]) -> bool:
    raw = environment.get("OLA_PUBLIC_BASE_URL", "")
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        local_loopback = (
            parsed.scheme == "http"
            and bool(parsed.netloc)
            and hostname in _LOOPBACK_HOSTS
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
        replit_domain = environment.get("REPLIT_DEV_DOMAIN", "").strip().lower().rstrip(".")
        trusted_replit_workspace = (
            parsed.scheme == "https"
            and bool(parsed.netloc)
            and hostname is not None
            and hostname.lower().rstrip(".") == replit_domain
            and hostname.lower().endswith(".replit.dev")
            and hostname.lower() != "replit.dev"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
            and not environment.get("REPLIT_DEPLOYMENT", "").strip()
        )
        return bool(local_loopback or trusted_replit_workspace)
    except ValueError:
        return False


def _derive_signing_seed(session_material: bytes, purpose: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_DERIVATION_SALT,
        info=b"OLA-DIOS-DEV-ED25519-" + purpose,
    ).derive(session_material)


def _development_igor_attestation(signing_input: dict) -> dict:
    """Produce an explicitly labelled fixture, never an independent IGOR verdict."""
    if not isinstance(signing_input, dict):
        raise ValueError("development attestation input must be an object")
    order_id = signing_input.get("order_id")
    report_sha256 = signing_input.get("report_sha256")
    approved_tip_hash = signing_input.get("approved_tip_hash")
    evidence_tip_hash = signing_input.get("evidence_tip_hash")
    if (
        not isinstance(order_id, str) or not order_id
        or not isinstance(report_sha256, str) or not _SHA256_RE.fullmatch(report_sha256)
        or not isinstance(approved_tip_hash, str) or not _SHA256_RE.fullmatch(approved_tip_hash)
        or not isinstance(evidence_tip_hash, str) or not _SHA256_RE.fullmatch(evidence_tip_hash)
    ):
        raise ValueError("development attestation requires an order and three exact SHA-256 bindings")
    return {
        "status": "VERIFIED",
        "order_id": order_id,
        "report_sha256": report_sha256,
        "approved_tip_hash": approved_tip_hash,
        "evidence_tip_hash": evidence_tip_hash,
        "attestation_profile": "DEVELOPMENT_FIXTURE",
        "verifier": "OLA_DEVELOPMENT_FIXTURE",
    }


def _no_development_provenance(_signing_input: dict) -> None:
    # Provenance is deliberately absent in Development; generated bundles
    # remain PARTIAL and cannot be promoted to production VERIFIED.
    return None


def development_customer_bundle_runtime_from_environment(
    *,
    profile: str,
    environment: dict[str, str] | None = None,
) -> CustomerBundleRuntime | None:
    """Build a test-only runtime only for explicit loopback HTTP Development."""
    env = os.environ if environment is None else environment
    if (
        profile != "development"
        or env.get("OLA_DEPLOYMENT_PROFILE", "").strip().lower() != "development"
        or env.get("REPLIT_DEPLOYMENT", "").strip()
        or not _development_origin_is_loopback(env)
    ):
        return None

    session_key = env.get(_SESSION_KEY_NAME)
    storage_key = env.get(_STORAGE_KEY_NAME)
    if not isinstance(session_key, str) or not session_key:
        return None
    try:
        # Human Identity uses Fernet's URL-safe encoding of exactly 32 bytes.
        Fernet(session_key.encode("ascii"))
    except (UnicodeEncodeError, ValueError):
        return None

    session_material = _decode_32_byte_base64(session_key)
    storage_material = _decode_32_byte_base64(storage_key)
    if (
        session_material is None
        or storage_material is None
        or session_material == storage_material
    ):
        return None

    igor_signer = TestOnlyEd25519Signer.from_seed(
        key_id="ola-development-igor-v1",
        custody_id="ola-development-igor-fixture",
        seed=_derive_signing_seed(session_material, b"IGOR"),
    )
    ola_signer = TestOnlyEd25519Signer.from_seed(
        key_id="ola-development-issuer-v1",
        custody_id="ola-development-issuer-fixture",
        seed=_derive_signing_seed(session_material, b"OLA"),
    )
    storage_root = env.get(
        "OLA_CUSTOMER_BUNDLE_STORAGE_PATH",
        "/tmp/ola-development-customer-bundles",
    )
    storage = EncryptedLocalBundleStorage(
        root=Path(storage_root),
        key=storage_material,
    )
    trusted_keys = {
        igor_signer.key_id: igor_signer.public_key_bytes,
        ola_signer.key_id: ola_signer.public_key_bytes,
    }
    return CustomerBundleRuntime(
        profile=SANDBOX_PROFILE,
        igor_signer=igor_signer,
        ola_signer=ola_signer,
        storage=storage,
        igor_attestation_provider=_development_igor_attestation,
        provenance_provider=_no_development_provenance,
        trusted_keys=trusted_keys,
        provenance_verifier=None,
        revoked_key_ids=frozenset(),
        timestamp_provider=None,
        timestamp_verifier=None,
        bundle_ttl_seconds=3600,
    )
