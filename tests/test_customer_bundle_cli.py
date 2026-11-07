"""CLI-level regression tests for offline package verification exit codes."""
import base64
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from app.customer_bundle.builder import build_customer_bundle
from app.customer_bundle.signers import TestOnlyEd25519Signer


def _write_bundle(tmp_path: Path, *, lifecycle: str) -> tuple[Path, Path]:
    now = int(time.time())
    created_at = now - 600
    expires_at = now + 3600 if lifecycle == "ACTIVE" else now - 1
    bundle_id = (
        "12345678-1234-4234-8234-123456789abc"
        if lifecycle == "ACTIVE"
        else "22345678-1234-4234-8234-123456789abc"
    )
    order_id = "order-cli-" + lifecycle.lower()
    report_json = json.dumps(
        {"order_id": order_id, "summary": "approved"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    report_sha256 = hashlib.sha256(report_json).hexdigest()
    approved_at = created_at - 60
    approved_tip_hash = "a" * 64
    signing_tip_hash = "b" * 64

    igor = TestOnlyEd25519Signer.generate(
        key_id="igor-cli-" + lifecycle.lower(),
        custody_id="igor-cli-custody",
    )
    ola = TestOnlyEd25519Signer.generate(
        key_id="ola-cli-" + lifecycle.lower(),
        custody_id="ola-cli-custody",
    )
    artifact = build_customer_bundle(
        tenant_id="tenant-cli-test",
        order_id=order_id,
        bundle_id=bundle_id,
        bundle_version=1,
        created_at=created_at,
        expires_at=expires_at,
        profile="CUSTOMER_BUNDLE_SANDBOX_V1",
        report_json=report_json,
        evidence_excerpt=b'{"order_id":"' + order_id.encode("ascii") + b'"}\n',
        provenance_json=b'{"schema":"test-provenance/v1"}',
        provenance_verified=True,
        approval={
            "status": "REPORT_APPROVED",
            "approved_at": approved_at,
            "approved_tip_hash": approved_tip_hash,
            "report_sha256": report_sha256,
            "requester_person_ref": "person-requester",
            "approver_person_ref": "person-approver",
            "reviewer_person_ref": "person-reviewer",
        },
        igor_attestation={
            "status": "VERIFIED",
            "order_id": order_id,
            "report_sha256": report_sha256,
            "approved_tip_hash": approved_tip_hash,
            "evidence_tip_hash": signing_tip_hash,
        },
        igor_signer=igor,
        ola_signer=ola,
        approved_at=approved_at,
        approved_tip_hash=approved_tip_hash,
        signing_tip_hash=signing_tip_hash,
        signed_at=created_at,
    )

    bundle_path = tmp_path / f"{lifecycle.lower()}-bundle.zip"
    bundle_path.write_bytes(artifact.zip_bytes)
    trust_store_path = tmp_path / f"{lifecycle.lower()}-trust.json"
    trust_store_path.write_text(
        json.dumps({
            "keys": {
                igor.key_id: base64.urlsafe_b64encode(igor.public_key_bytes).decode("ascii").rstrip("="),
                ola.key_id: base64.urlsafe_b64encode(ola.public_key_bytes).decode("ascii").rstrip("="),
            },
            "revoked_key_ids": [],
        }),
        encoding="utf-8",
    )
    return bundle_path, trust_store_path


def _run_cli(bundle_path: Path, trust_store_path: Path) -> subprocess.CompletedProcess:
    repo_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "verify_customer_bundle.py"),
            str(bundle_path),
            "--trust-store",
            str(trust_store_path),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_cli_returns_zero_for_verified_active_bundle(tmp_path):
    bundle, trust_store = _write_bundle(tmp_path, lifecycle="ACTIVE")
    result = _run_cli(bundle, trust_store)

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "VERIFIED"
    assert report["lifecycle_status"] == "ACTIVE"


def test_cli_returns_four_for_cryptographically_valid_expired_bundle(tmp_path):
    bundle, trust_store = _write_bundle(tmp_path, lifecycle="EXPIRED")
    result = _run_cli(bundle, trust_store)

    assert result.returncode == 4, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "VERIFIED"
    assert report["lifecycle_status"] == "EXPIRED"
    assert report["igor_signature"] == "VERIFIED"
    assert report["ola_signature"] == "VERIFIED"
