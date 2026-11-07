"""Offline verifier for separately signed IGOR attestation and OLA manifest."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.customer_bundle.builder import (
    PRODUCTION_PROFILE,
    SANDBOX_PROFILE,
    canonical_json_bytes,
)


MAX_ENTRIES = 64
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
SIGNATURE_CONTROL_FILES = {
    "manifest.json", "manifest.sig",
    "igor/attestation.json", "igor/attestation.sig",
}


@dataclass(frozen=True)
class VerificationReport:
    status: str
    reason: str
    igor_signature: str
    ola_signature: str
    manifest_sha256: str | None
    report_sha256: str | None
    full_tenant_chain_recomputed: bool = False
    timestamp_status: str = "NOT_PRESENT"


def _invalid(reason: str, *, igor="NOT_CHECKED", ola="NOT_CHECKED",
             manifest_sha=None, report_sha=None, timestamp="NOT_PRESENT") -> VerificationReport:
    return VerificationReport(
        status="INVALID",
        reason=reason,
        igor_signature=igor,
        ola_signature=ola,
        manifest_sha256=manifest_sha,
        report_sha256=report_sha,
        full_tenant_chain_recomputed=False,
        timestamp_status=timestamp,
    )


def _safe_path(name: str) -> bool:
    if not isinstance(name, str) or not name or name.startswith("/") or "\\" in name:
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and all(part not in ("", ".", "..") for part in path.parts)


def _decode_signature(raw: bytes) -> bytes | None:
    if not isinstance(raw, bytes) or not re.fullmatch(rb"[A-Za-z0-9_-]{86}", raw):
        return None
    try:
        decoded = base64.urlsafe_b64decode(raw + b"==")
    except (ValueError, base64.binascii.Error):
        return None
    if len(decoded) != 64 or base64.urlsafe_b64encode(decoded).rstrip(b"=") != raw:
        return None
    return decoded


def _verify_signature(public_key_bytes: bytes, signature: bytes, message: bytes) -> bool:
    if not isinstance(public_key_bytes, bytes) or len(public_key_bytes) != 32:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(signature, message)
        return True
    except (ValueError, InvalidSignature):
        return False


def verify_customer_bundle(
    bundle_bytes: bytes,
    *,
    trusted_keys: dict[str, bytes],
    revoked_key_ids: set[str] | frozenset[str] = frozenset(),
    timestamp_verifier: Callable[[bytes, int], bool] | None = None,
) -> VerificationReport:
    """Verify ZIP safety, canonical manifest, two signatures and each listed file.

    A filtered order-evidence excerpt is never treated as the full tenant
    Evidence chain. Production timestamp verification requires a separate
    RFC 3161/transparency trust adapter supplied by the offline verifier.
    """
    if not isinstance(bundle_bytes, bytes) or not bundle_bytes:
        return _invalid("EMPTY_BUNDLE")
    if not isinstance(trusted_keys, dict):
        return _invalid("INVALID_TRUST_STORE")
    revoked = set(revoked_key_ids)
    try:
        archive = zipfile.ZipFile(io.BytesIO(bundle_bytes), mode="r")
    except (zipfile.BadZipFile, OSError, ValueError):
        return _invalid("INVALID_ZIP")
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            return _invalid("TOO_MANY_ARCHIVE_ENTRIES")
        names = [item.filename for item in infos]
        if len(names) != len(set(names)):
            return _invalid("DUPLICATE_ARCHIVE_ENTRY")
        if any(not _safe_path(name) for name in names):
            return _invalid("UNSAFE_ARCHIVE_PATH")
        total_size = sum(item.file_size for item in infos)
        if total_size > MAX_UNCOMPRESSED_BYTES:
            return _invalid("ARCHIVE_TOO_LARGE")
        if any(stat.S_ISLNK(item.external_attr >> 16) for item in infos):
            return _invalid("SYMLINK_ARCHIVE_ENTRY")
        archive_names = set(names)
        if not SIGNATURE_CONTROL_FILES.issubset(archive_names):
            return _invalid("MISSING_SIGNATURE_CONTROL_FILE")
        try:
            manifest_bytes = archive.read("manifest.json")
            manifest_signature_raw = archive.read("manifest.sig")
            igor_bytes = archive.read("igor/attestation.json")
            igor_signature_raw = archive.read("igor/attestation.sig")
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            igor_attestation = json.loads(igor_bytes.decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError, OSError):
            return _invalid("INVALID_CONTROL_FILE")

        if not isinstance(manifest, dict) or manifest.get("schema") != "ola-customer-evidence-bundle/v1":
            return _invalid("UNKNOWN_MANIFEST_SCHEMA")
        try:
            if canonical_json_bytes(manifest) != manifest_bytes:
                return _invalid("NON_CANONICAL_MANIFEST")
        except ValueError:
            return _invalid("INVALID_MANIFEST_JSON")

        ola_info = manifest.get("ola_signer")
        igor_info = manifest.get("igor")
        if not isinstance(ola_info, dict) or not isinstance(igor_info, dict):
            return _invalid("SIGNER_METADATA_MISSING")
        ola_key_id = ola_info.get("key_id")
        igor_key_id = igor_info.get("key_id")
        if not isinstance(ola_key_id, str) or not ola_key_id:
            return _invalid("OLA_KEY_ID_MISSING")
        if not isinstance(igor_key_id, str) or not igor_key_id:
            return _invalid("IGOR_KEY_ID_MISSING")
        if ola_key_id == igor_key_id:
            return _invalid("SIGNERS_NOT_INDEPENDENT")
        if ola_info.get("custody_id") == igor_info.get("custody_id"):
            return _invalid("SIGNER_CUSTODY_NOT_INDEPENDENT")

        if ola_key_id in revoked:
            return _invalid("REVOKED_OLA_KEY")
        ola_public = trusted_keys.get(ola_key_id)
        if ola_public is None:
            return _invalid("UNKNOWN_OLA_KEY")
        ola_signature = _decode_signature(manifest_signature_raw)
        if ola_signature is None:
            return _invalid("INVALID_OLA_SIGNATURE_FORMAT")
        if not _verify_signature(ola_public, ola_signature, manifest_bytes):
            return _invalid("OLA_SIGNATURE_INVALID", ola="INVALID")
        ola_status = "VERIFIED"

        if igor_key_id in revoked:
            return _invalid("REVOKED_IGOR_KEY", ola=ola_status)
        igor_public = trusted_keys.get(igor_key_id)
        if igor_public is None:
            return _invalid("UNKNOWN_IGOR_KEY", ola=ola_status)
        igor_signature = _decode_signature(igor_signature_raw)
        if igor_signature is None:
            return _invalid("INVALID_IGOR_SIGNATURE_FORMAT", ola=ola_status)
        if not _verify_signature(igor_public, igor_signature, igor_bytes):
            return _invalid("IGOR_SIGNATURE_INVALID", ola=ola_status, igor="INVALID")
        igor_status = "VERIFIED"

        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        report_sha = manifest.get("report_sha256")
        if hashlib.sha256(igor_bytes).hexdigest() != igor_info.get("attestation_sha256"):
            return _invalid(
                "IGOR_ATTESTATION_DIGEST_MISMATCH",
                igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
            )
        if (
            not isinstance(igor_attestation, dict)
            or igor_attestation.get("status") != "VERIFIED"
            or igor_attestation.get("order_id") != manifest.get("order_id")
            or igor_attestation.get("report_sha256") != report_sha
        ):
            return _invalid(
                "IGOR_ATTESTATION_BINDING_MISMATCH",
                igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
            )

        file_entries = manifest.get("files")
        if not isinstance(file_entries, list) or not file_entries:
            return _invalid(
                "MANIFEST_FILE_LIST_MISSING",
                igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
            )
        listed = {}
        for item in file_entries:
            if not isinstance(item, dict):
                return _invalid(
                    "INVALID_MANIFEST_FILE_ENTRY",
                    igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
                )
            path = item.get("path")
            digest = item.get("sha256")
            size = item.get("size")
            if not _safe_path(path) or path in SIGNATURE_CONTROL_FILES:
                return _invalid(
                    "UNSAFE_MANIFEST_FILE_PATH",
                    igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
                )
            if path in listed or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                return _invalid(
                    "INVALID_MANIFEST_FILE_ENTRY",
                    igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
                )
            if type(size) is not int or size < 0:
                return _invalid(
                    "INVALID_MANIFEST_FILE_SIZE",
                    igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
                )
            listed[path] = (digest, size)

        expected_names = set(listed) | SIGNATURE_CONTROL_FILES
        if archive_names != expected_names:
            return _invalid(
                "ARCHIVE_CONTENT_SET_MISMATCH",
                igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
            )
        for path, (expected_digest, expected_size) in listed.items():
            try:
                body = archive.read(path)
            except (KeyError, OSError):
                return _invalid(
                    "MISSING_LISTED_FILE",
                    igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
                )
            if len(body) != expected_size or hashlib.sha256(body).hexdigest() != expected_digest:
                return _invalid(
                    "FILE_DIGEST_MISMATCH",
                    igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
                    report_sha=report_sha,
                )

        try:
            report = json.loads(archive.read("report/report.json").decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
            return _invalid(
                "REPORT_JSON_INVALID",
                igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
            )
        if (
            not isinstance(report, dict)
            or report.get("order_id") != manifest.get("order_id")
            or hashlib.sha256(archive.read("report/report.json")).hexdigest() != report_sha
        ):
            return _invalid(
                "REPORT_BINDING_MISMATCH",
                igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
            )

        profile = manifest.get("profile")
        status = manifest.get("status")
        timestamp_status = "NOT_PRESENT"
        timestamp_path = manifest.get("timestamp_proof_path")
        if profile == PRODUCTION_PROFILE:
            if (
                status != "VERIFIED"
                or timestamp_path != "timestamp/rfc3161.tsr"
                or manifest.get("timestamp_proof_status") != "VERIFIED"
            ):
                return _invalid(
                    "PRODUCTION_PROFILE_GATES_MISSING",
                    igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
                    report_sha=report_sha,
                )
            if timestamp_verifier is None:
                return _invalid(
                    "TIMESTAMP_NOT_VERIFIED",
                    igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
                    report_sha=report_sha, timestamp="PRESENT_NOT_VERIFIED",
                )
            try:
                token = archive.read(timestamp_path)
                if not timestamp_verifier(token, manifest["signed_at"]):
                    return _invalid(
                        "TIMESTAMP_PROOF_INVALID",
                        igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
                        report_sha=report_sha, timestamp="INVALID",
                    )
            except (KeyError, TypeError, ValueError):
                return _invalid(
                    "TIMESTAMP_PROOF_INVALID",
                    igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
                    report_sha=report_sha, timestamp="INVALID",
                )
            timestamp_status = "VERIFIED"
        elif profile == SANDBOX_PROFILE:
            if timestamp_path is not None:
                timestamp_status = "PRESENT_NOT_VERIFIED"
            if status not in {"PARTIAL", "VERIFIED"}:
                return _invalid(
                    "INVALID_SANDBOX_STATUS",
                    igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
                    report_sha=report_sha,
                )
        else:
            return _invalid(
                "UNKNOWN_BUNDLE_PROFILE",
                igor=igor_status, ola=ola_status, manifest_sha=manifest_sha,
                report_sha=report_sha,
            )

        return VerificationReport(
            status=status,
            reason="VERIFIED" if status == "VERIFIED" else "PROVENANCE_NOT_AVAILABLE",
            igor_signature=igor_status,
            ola_signature=ola_status,
            manifest_sha256=manifest_sha,
            report_sha256=report_sha,
            full_tenant_chain_recomputed=False,
            timestamp_status=timestamp_status,
        )
