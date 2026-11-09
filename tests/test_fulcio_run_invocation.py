"""Regression tests for binding OCI provenance to the exact Fulcio signing run."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ObjectIdentifier

from app.customer_bundle.github_provenance import (
    OIDC_ISSUER,
    PREDICATE_TYPE,
    SCHEMA,
    verify_github_oci_provenance,
)

REPOSITORY = "krzysztofcieciwa07-ship-it/OLA"
REPOSITORY_ID = "1328264236"
SOURCE_SHA = "a" * 40
SOURCE_REF = "refs/heads/main"
IMAGE_NAME = "ghcr.io/krzysztofcieciwa07-ship-it/ola"
IMAGE_DIGEST = "sha256:" + "b" * 64
WORKFLOW_IDENTITY = (
    "https://github.com/krzysztofcieciwa07-ship-it/OLA/"
    ".github/workflows/supply-chain-evidence.yml@refs/heads/main"
)
RUN_INVOCATION_OID = ObjectIdentifier("1.3.6.1.4.1.57264.1.21")
RUN_ID = 40968975127
RUN_ATTEMPT = 1


def _der_utf8_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    size = len(encoded)
    if size < 128:
        length = bytes([size])
    else:
        raw = size.to_bytes((size.bit_length() + 7) // 8, "big")
        length = bytes([0x80 | len(raw)]) + raw
    return b"\x0c" + length + encoded


def _bundle(run_id=RUN_ID, run_attempt=RUN_ATTEMPT, *, include_extension=True):
    invocation = (
        f"https://github.com/{REPOSITORY}/actions/runs/{run_id}/attempts/{run_attempt}"
    )
    key = ec.generate_private_key(ec.SECP256R1())
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-fulcio-test")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-fulcio-test")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(minutes=5))
    )
    if include_extension:
        builder = builder.add_extension(
            x509.UnrecognizedExtension(RUN_INVOCATION_OID, _der_utf8_string(invocation)),
            critical=False,
        )
    certificate = builder.sign(key, hashes.SHA256())
    return json.dumps({
        "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "verificationMaterial": {
            "certificate": {
                "rawBytes": base64.b64encode(certificate.public_bytes(serialization.Encoding.DER)).decode("ascii"),
            },
        },
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _statement():
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{
            "name": IMAGE_NAME,
            "digest": {"sha256": IMAGE_DIGEST.removeprefix("sha256:")},
        }],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "buildDefinition": {
                "resolvedDependencies": [{
                    "uri": f"git+https://github.com/{REPOSITORY}@{SOURCE_REF}",
                    "digest": {"gitCommit": SOURCE_SHA},
                }],
            },
        },
    }


def _payload(*, run_id=RUN_ID, run_attempt=RUN_ATTEMPT, bundle_bytes=None):
    actual_bundle = bundle_bytes or _bundle(run_id, run_attempt)
    trusted_root = b'{"trustedRoot":"synthetic-test-root"}\n'
    return json.dumps({
        "schema": SCHEMA,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "source_sha": SOURCE_SHA,
        "source_ref": SOURCE_REF,
        "workflow_identity": WORKFLOW_IDENTITY,
        "image_name": IMAGE_NAME,
        "image_digest": IMAGE_DIGEST,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "attestation_bundle_b64": base64.b64encode(actual_bundle).decode("ascii"),
        "trusted_root_b64": base64.b64encode(trusted_root).decode("ascii"),
        "bundle_sha256": hashlib.sha256(actual_bundle).hexdigest(),
        "trusted_root_sha256": hashlib.sha256(trusted_root).hexdigest(),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"), hashlib.sha256(trusted_root).hexdigest()


def _verified_cli_result():
    return json.dumps([{
        "verificationResult": {
            "signature": {
                "certificate": {
                    "sourceRepositoryIdentifier": REPOSITORY_ID,
                    "issuer": OIDC_ISSUER,
                },
            },
            "statement": _statement(),
        },
    }])


def _verify(monkeypatch, *, payload=None, expected_run_id=RUN_ID, expected_run_attempt=RUN_ATTEMPT):
    raw, root_sha = _payload() if payload is None else (
        payload,
        hashlib.sha256(b'{"trustedRoot":"synthetic-test-root"}\n').hexdigest(),
    )

    def successful_gh_verify(command, **kwargs):
        bundle_path = Path(command[command.index("--bundle") + 1])
        assert bundle_path.read_bytes() == base64.b64decode(json.loads(raw)["attestation_bundle_b64"])
        return subprocess.CompletedProcess(command, 0, stdout=_verified_cli_result(), stderr="")

    monkeypatch.setattr(
        "app.customer_bundle.github_provenance.subprocess.run",
        successful_gh_verify,
    )
    return verify_github_oci_provenance(
        raw,
        SOURCE_SHA,
        IMAGE_DIGEST,
        expected_repository=REPOSITORY,
        expected_repository_id=REPOSITORY_ID,
        expected_workflow_identity=WORKFLOW_IDENTITY,
        expected_source_ref=SOURCE_REF,
        expected_image_name=IMAGE_NAME,
        expected_trusted_root_sha256=root_sha,
        expected_run_id=expected_run_id,
        expected_run_attempt=expected_run_attempt,
    )


def test_exact_fulcio_run_invocation_uri_is_required_after_sigstore_verification(monkeypatch):
    assert _verify(monkeypatch) is True


def test_fulcio_certificate_from_another_run_is_rejected(monkeypatch):
    assert _verify(monkeypatch, expected_run_id=RUN_ID + 1) is False


def test_fulcio_certificate_from_another_attempt_is_rejected(monkeypatch):
    assert _verify(monkeypatch, expected_run_attempt=RUN_ATTEMPT + 1) is False


def test_payload_run_identity_cannot_disagree_with_signed_fulcio_certificate(monkeypatch):
    raw, _ = _payload(run_id=RUN_ID + 1, run_attempt=RUN_ATTEMPT, bundle_bytes=_bundle(RUN_ID, RUN_ATTEMPT))
    assert _verify(monkeypatch, payload=raw, expected_run_id=RUN_ID + 1) is False


def test_missing_fulcio_run_invocation_extension_is_rejected(monkeypatch):
    raw, _ = _payload(bundle_bytes=_bundle(include_extension=False))
    assert _verify(monkeypatch, payload=raw) is False


def test_non_integer_or_non_positive_run_identity_is_rejected(monkeypatch):
    for run_id, attempt in ((0, 1), (RUN_ID, 0), (True, 1), (RUN_ID, True)):
        raw, _ = _payload(run_id=run_id, run_attempt=attempt)
        assert _verify(monkeypatch, payload=raw, expected_run_id=RUN_ID, expected_run_attempt=RUN_ATTEMPT) is False
