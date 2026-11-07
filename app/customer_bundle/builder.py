"""Deterministic, order-scoped customer evidence bundle builder."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any, Callable

from app.customer_bundle.signers import BundleSignerRejected, Ed25519Signer


SANDBOX_PROFILE = "CUSTOMER_BUNDLE_SANDBOX_V1"
PRODUCTION_PROFILE = "CUSTOMER_BUNDLE_PRODUCTION_V1"
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
HEX_40_RE = re.compile(r"^[0-9a-f]{40}$")


class CustomerBundleRejected(ValueError):
    pass


@dataclass(frozen=True)
class BundleArtifact:
    zip_bytes: bytes
    status: str
    manifest_sha256: str
    report_sha256: str
    igor_key_id: str
    ola_key_id: str


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CustomerBundleRejected("bundle input is not canonical JSON") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _b64url(signature: bytes) -> bytes:
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise CustomerBundleRejected("Ed25519 signature must be exactly 64 raw bytes")
    return base64.urlsafe_b64encode(signature).rstrip(b"=")


def _safe_approval(approval: dict) -> dict:
    if not isinstance(approval, dict) or approval.get("status") != "REPORT_APPROVED":
        raise CustomerBundleRejected("independently approved customer report is required")
    allowed = (
        "status", "approved_at", "approved_tip_hash",
        "approver_person_ref", "reviewer_person_ref",
    )
    return {key: approval[key] for key in allowed if key in approval}


def _validate_signers(igor_signer: Ed25519Signer, ola_signer: Ed25519Signer, *, production: bool):
    for signer, label in ((igor_signer, "IGOR"), (ola_signer, "OLA")):
        if not isinstance(signer.key_id, str) or not signer.key_id:
            raise CustomerBundleRejected(f"{label} signer key ID is required")
        if not isinstance(signer.custody_id, str) or not signer.custody_id:
            raise CustomerBundleRejected(f"{label} signer custody ID is required")
        if not isinstance(signer.public_key_bytes, bytes) or len(signer.public_key_bytes) != 32:
            raise CustomerBundleRejected(f"{label} signer Ed25519 public key must be exactly 32 bytes")
    if igor_signer.key_id == ola_signer.key_id:
        raise CustomerBundleRejected("IGOR and OLA signatures must use distinct signing keys")
    if igor_signer.custody_id == ola_signer.custody_id:
        raise CustomerBundleRejected("IGOR and OLA signers must have independent custody principals")
    if production and (igor_signer.test_only or ola_signer.test_only):
        raise CustomerBundleRejected("production signers must not be test-only")


def _safe_archive_name(name: str) -> bool:
    if not isinstance(name, str) or not name or name.startswith("/") or "\\" in name:
        return False
    parts = name.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def build_customer_bundle(
    *,
    tenant_id: str,
    order_id: str,
    profile: str,
    report_json: bytes,
    evidence_excerpt: bytes,
    provenance_json: bytes | None,
    approval: dict,
    igor_attestation: dict,
    igor_signer: Ed25519Signer,
    ola_signer: Ed25519Signer,
    approved_at: int,
    approved_tip_hash: str,
    signing_tip_hash: str,
    signed_at: int,
    timestamp_proof: bytes | None = None,
    timestamp_provider: Callable[[bytes], bytes] | None = None,
    timestamp_verifier: Callable[[bytes, bytes, int], bool] | None = None,
    source_sha: str | None = None,
    image_digest: str | None = None,
) -> BundleArtifact:
    """Build a deterministic ZIP with separate IGOR attestation and OLA manifest signatures.

    The evidence NDJSON is a filtered order-scoped excerpt. Its original record
    hashes are preserved as references but the verifier does not claim to
    recompute the full tenant chain from that filtered excerpt.
    """
    if profile not in {SANDBOX_PROFILE, PRODUCTION_PROFILE}:
        raise CustomerBundleRejected("unknown customer bundle verification profile")
    if not isinstance(tenant_id, str) or not tenant_id or not isinstance(order_id, str) or not order_id:
        raise CustomerBundleRejected("tenant_id and order_id are required")
    if not isinstance(report_json, bytes) or not report_json:
        raise CustomerBundleRejected("sanitized report JSON bytes are required")
    if not isinstance(evidence_excerpt, bytes):
        raise CustomerBundleRejected("order evidence excerpt must be bytes")
    if not isinstance(approved_at, int) or not isinstance(signed_at, int):
        raise CustomerBundleRejected("approval and signing timestamps must be integer Unix timestamps")
    if not HEX_64_RE.fullmatch(approved_tip_hash or "") or not HEX_64_RE.fullmatch(signing_tip_hash or ""):
        raise CustomerBundleRejected("approval and signing Evidence tips must be SHA-256 digests")

    production = profile == PRODUCTION_PROFILE
    _validate_signers(igor_signer, ola_signer, production=production)
    clean_approval = _safe_approval(approval)
    if clean_approval.get("approved_at") != approved_at:
        raise CustomerBundleRejected("approval timestamp does not match the reviewed approval record")
    if clean_approval.get("approved_tip_hash") != approved_tip_hash:
        raise CustomerBundleRejected("approval Evidence tip does not match the reviewed approval record")

    try:
        report_obj = json.loads(report_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CustomerBundleRejected("report JSON is invalid") from exc
    if not isinstance(report_obj, dict) or report_obj.get("order_id") != order_id:
        raise CustomerBundleRejected("report must be bound to this exact order")
    report_sha256 = _sha256(report_json)

    if not isinstance(igor_attestation, dict):
        raise CustomerBundleRejected("independent IGOR attestation is required")
    igor_payload = dict(igor_attestation)
    if (
        igor_payload.get("status") != "VERIFIED"
        or igor_payload.get("order_id") != order_id
        or igor_payload.get("report_sha256") != report_sha256
    ):
        raise CustomerBundleRejected("IGOR attestation is not verified for this exact order and report")
    igor_bytes = canonical_json_bytes(igor_payload)
    igor_signature = igor_signer.sign(igor_bytes)
    if not isinstance(igor_signature, bytes) or len(igor_signature) != 64:
        raise BundleSignerRejected("IGOR signer did not return a 64-byte Ed25519 signature")

    files: dict[str, bytes] = {
        "report/report.json": report_json,
        "evidence/order-evidence.ndjson": evidence_excerpt,
        "verification/README.txt": (
            b"OLA customer evidence bundle. Verify manifest.sig and igor/attestation.sig "
            b"with independently trusted public keys. order-evidence.ndjson is a "
            b"filtered order-scoped excerpt, not the complete tenant Evidence chain.\n"
        ),
    }
    if provenance_json is not None:
        if not isinstance(provenance_json, bytes) or not provenance_json:
            raise CustomerBundleRejected("provenance JSON must be nonempty bytes when supplied")
        files["provenance/source-runtime.json"] = provenance_json
    if timestamp_proof is not None and (
        not isinstance(timestamp_proof, bytes) or not timestamp_proof
    ):
        raise CustomerBundleRejected("timestamp proof must be nonempty bytes when supplied")

    if production:
        if provenance_json is None or timestamp_provider is None or timestamp_verifier is None:
            raise CustomerBundleRejected("production bundle requires provenance and an independent RFC 3161 provider/verifier")
        if not isinstance(source_sha, str) or not HEX_40_RE.fullmatch(source_sha):
            raise CustomerBundleRejected("production bundle requires a 40-character source SHA")
        if not isinstance(image_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
            raise CustomerBundleRejected("production bundle requires an OCI sha256 image digest")
        if not clean_approval.get("approver_person_ref") or not clean_approval.get("reviewer_person_ref"):
            raise CustomerBundleRejected("production bundle requires HR-backed approver and reviewer person references")
        status = "VERIFIED"
    else:
        status = "VERIFIED" if provenance_json is not None else "PARTIAL"

    for name, body in files.items():
        if not _safe_archive_name(name) or not isinstance(body, bytes):
            raise CustomerBundleRejected("bundle contains an unsafe path or non-byte file")
    if len(files) != len(set(files)):
        raise CustomerBundleRejected("bundle contains duplicate archive paths")

    manifest = {
        "schema": "ola-customer-evidence-bundle/v1",
        "profile": profile,
        "status": status,
        "tenant_id": tenant_id,
        "order_id": order_id,
        "report_sha256": report_sha256,
        "approved_at": approved_at,
        "approved_tip_hash": approved_tip_hash,
        "signed_at": signed_at,
        "signing_tip_hash": signing_tip_hash,
        "approval": clean_approval,
        "igor": {
            "status": "VERIFIED",
            "key_id": igor_signer.key_id,
            "custody_id": igor_signer.custody_id,
            "attestation_path": "igor/attestation.json",
            "attestation_sha256": _sha256(igor_bytes),
            "signature_path": "igor/attestation.sig",
        },
        "ola_signer": {
            "key_id": ola_signer.key_id,
            "custody_id": ola_signer.custody_id,
            "signature_path": "manifest.sig",
            "signature_format": "base64url-no-padding-ed25519-64-bytes",
        },
        "source_sha": source_sha,
        "image_digest": image_digest,
        "timestamp_proof_path": "timestamp/rfc3161.tsr" if (production or timestamp_proof is not None) else None,
        "timestamp_proof_status": "ATTACHED_AND_ISSUER_VERIFIED" if production else ("PRESENT_NOT_VERIFIED" if timestamp_proof is not None else "NOT_PRESENT"),
        "evidence_scope": "ORDER_SCOPED_EXCERPT",
        "full_tenant_chain_recomputable": False,
        "files": [
            {"path": name, "sha256": _sha256(body), "size": len(body)}
            for name, body in sorted(files.items())
        ],
        "control_files_excluded_from_file_list": [
            "manifest.json", "manifest.sig", "igor/attestation.json", "igor/attestation.sig", "timestamp/rfc3161.tsr",
        ],
    }
    manifest_bytes = canonical_json_bytes(manifest)
    if production:
        try:
            timestamp_proof = timestamp_provider(manifest_bytes)
            timestamp_valid = (
                isinstance(timestamp_proof, bytes)
                and bool(timestamp_proof)
                and timestamp_verifier(timestamp_proof, manifest_bytes, signed_at) is True
            )
        except Exception as exc:
            raise CustomerBundleRejected("independent RFC 3161 timestamp issuance/verification failed") from exc
        if not timestamp_valid:
            raise CustomerBundleRejected("independent RFC 3161 timestamp issuance/verification failed")
    manifest_signature = ola_signer.sign(manifest_bytes)
    if not isinstance(manifest_signature, bytes) or len(manifest_signature) != 64:
        raise BundleSignerRejected("OLA signer did not return a 64-byte Ed25519 signature")

    archive_files = dict(files)
    archive_files["igor/attestation.json"] = igor_bytes
    archive_files["igor/attestation.sig"] = _b64url(igor_signature)
    archive_files["manifest.json"] = manifest_bytes
    archive_files["manifest.sig"] = _b64url(manifest_signature)
    if timestamp_proof is not None:
        archive_files["timestamp/rfc3161.tsr"] = timestamp_proof

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED, strict_timestamps=True) as archive:
        for name in sorted(archive_files):
            if not _safe_archive_name(name):
                raise CustomerBundleRejected("bundle contains an unsafe archive path")
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            info.flag_bits = 0
            info.extra = b""
            info.comment = b""
            archive.writestr(info, archive_files[name])

    return BundleArtifact(
        zip_bytes=buffer.getvalue(),
        status=status,
        manifest_sha256=_sha256(manifest_bytes),
        report_sha256=report_sha256,
        igor_key_id=igor_signer.key_id,
        ola_key_id=ola_signer.key_id,
    )
