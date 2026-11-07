"""TDD contracts for independently dual-signed OLA customer evidence bundles."""
import base64
import io
import json
import zipfile

import pytest


def _bundle_api():
    from app.customer_bundle.builder import build_customer_bundle
    from app.customer_bundle.signers import TestOnlyEd25519Signer
    from app.customer_bundle.verifier import verify_customer_bundle
    return build_customer_bundle, TestOnlyEd25519Signer, verify_customer_bundle


def _inputs():
    return {
        "tenant_id": "tenant-customer-bundle-1",
        "order_id": "order-customer-bundle-1",
        "profile": "CUSTOMER_BUNDLE_SANDBOX_V1",
        "report_json": b'{"order_id":"order-customer-bundle-1","result":"verified"}',
        "evidence_excerpt": (
            b'{"seq":10,"record_type":"revenue.execution_completed","record_hash":"'
            + b"a" * 64 + b'"}\n'
        ),
        "provenance_json": None,
        "approval": {
            "status": "REPORT_APPROVED",
            "approved_at": 1_800_000_000,
            "approved_tip_hash": "b" * 64,
        },
        "igor_attestation": {
            "status": "VERIFIED",
            "order_id": "order-customer-bundle-1",
            "report_sha256": None,
            "evidence_tip_hash": "b" * 64,
        },
        "approved_at": 1_800_000_000,
        "approved_tip_hash": "b" * 64,
        "signing_tip_hash": "c" * 64,
        "signed_at": 1_800_000_100,
    }


def test_bundle_builder_and_verifier_modules_exist():
    import importlib.util
    assert importlib.util.find_spec("app.customer_bundle.builder") is not None
    assert importlib.util.find_spec("app.customer_bundle.verifier") is not None


def test_customer_bundle_has_two_independent_ed25519_signatures_and_is_deterministic():
    build, TestSigner, verify = _bundle_api()
    igor = TestSigner.generate(key_id="igor-test-key-1", custody_id="igor-test-custody")
    ola = TestSigner.generate(key_id="ola-test-key-1", custody_id="ola-test-custody")
    values = _inputs()
    report = json.loads(values["report_json"])
    values["igor_attestation"]["report_sha256"] = __import__("hashlib").sha256(
        values["report_json"]
    ).hexdigest()

    first = build(
        **values,
        igor_signer=igor,
        ola_signer=ola,
    )
    second = build(
        **values,
        igor_signer=igor,
        ola_signer=ola,
    )
    assert first.zip_bytes == second.zip_bytes
    assert first.status == "PARTIAL"  # provenance unavailable in sandbox profile
    with zipfile.ZipFile(io.BytesIO(first.zip_bytes)) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert "manifest.json" in names
        assert "manifest.sig" in names
        assert "igor/attestation.json" in names
        assert "igor/attestation.sig" in names
        assert "report/report.json" in names
        assert "evidence/order-evidence.ndjson" in names
        assert "manifest.json" not in json.loads(archive.read("manifest.json"))["files"]
        sig = base64.urlsafe_b64decode(
            archive.read("manifest.sig") + b"=" * (-len(archive.read("manifest.sig")) % 4)
        )
        assert len(sig) == 64

    trusted = {
        igor.key_id: igor.public_key_bytes,
        ola.key_id: ola.public_key_bytes,
    }
    result = verify(first.zip_bytes, trusted_keys=trusted)
    assert result.status == "PARTIAL"
    assert result.igor_signature == "VERIFIED"
    assert result.ola_signature == "VERIFIED"
    assert result.full_tenant_chain_recomputed is False


def test_bundle_verifier_rejects_modified_report_or_attestation_signature():
    build, TestSigner, verify = _bundle_api()
    igor = TestSigner.generate(key_id="igor-test-key-2", custody_id="igor-test-custody")
    ola = TestSigner.generate(key_id="ola-test-key-2", custody_id="ola-test-custody")
    values = _inputs()
    import hashlib
    values["igor_attestation"]["report_sha256"] = hashlib.sha256(values["report_json"]).hexdigest()
    artifact = build(**values, igor_signer=igor, ola_signer=ola)
    trusted = {
        igor.key_id: igor.public_key_bytes,
        ola.key_id: ola.public_key_bytes,
    }

    with zipfile.ZipFile(io.BytesIO(artifact.zip_bytes)) as source:
        files = {name: source.read(name) for name in source.namelist()}
    files["report/report.json"] += b" "
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        for name, body in files.items():
            target.writestr(name, body)
    report = verify(output.getvalue(), trusted_keys=trusted)
    assert report.status == "INVALID"
    assert report.reason == "FILE_DIGEST_MISMATCH"


def test_bundle_verifier_rejects_unknown_or_revoked_signing_keys():
    build, TestSigner, verify = _bundle_api()
    igor = TestSigner.generate(key_id="igor-test-key-3", custody_id="igor-test-custody")
    ola = TestSigner.generate(key_id="ola-test-key-3", custody_id="ola-test-custody")
    values = _inputs()
    import hashlib
    values["igor_attestation"]["report_sha256"] = hashlib.sha256(values["report_json"]).hexdigest()
    artifact = build(**values, igor_signer=igor, ola_signer=ola)

    unknown = verify(artifact.zip_bytes, trusted_keys={igor.key_id: igor.public_key_bytes})
    assert unknown.status == "INVALID"
    assert unknown.reason == "UNKNOWN_OLA_KEY"

    revoked = verify(
        artifact.zip_bytes,
        trusted_keys={
            igor.key_id: igor.public_key_bytes,
            ola.key_id: ola.public_key_bytes,
        },
        revoked_key_ids={igor.key_id},
    )
    assert revoked.status == "INVALID"
    assert revoked.reason == "REVOKED_IGOR_KEY"


def test_production_bundle_rejects_test_signers_missing_timestamp_and_provenance():
    build, TestSigner, _verify = _bundle_api()
    igor = TestSigner.generate(key_id="igor-test-key-4", custody_id="igor-test-custody")
    ola = TestSigner.generate(key_id="ola-test-key-4", custody_id="ola-test-custody")
    values = _inputs()
    values["profile"] = "CUSTOMER_BUNDLE_PRODUCTION_V1"
    import hashlib
    values["igor_attestation"]["report_sha256"] = hashlib.sha256(values["report_json"]).hexdigest()

    with pytest.raises(ValueError, match="production signers must not be test-only"):
        build(**values, igor_signer=igor, ola_signer=ola)


def test_bundle_rejects_duplicate_or_path_traversal_entries():
    build, TestSigner, verify = _bundle_api()
    igor = TestSigner.generate(key_id="igor-test-key-5", custody_id="igor-test-custody")
    ola = TestSigner.generate(key_id="ola-test-key-5", custody_id="ola-test-custody")
    values = _inputs()
    import hashlib
    values["igor_attestation"]["report_sha256"] = hashlib.sha256(values["report_json"]).hexdigest()
    artifact = build(**values, igor_signer=igor, ola_signer=ola)
    trusted = {
        igor.key_id: igor.public_key_bytes,
        ola.key_id: ola.public_key_bytes,
    }

    with zipfile.ZipFile(io.BytesIO(artifact.zip_bytes)) as source:
        files = {name: source.read(name) for name in source.namelist()}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        for name, body in files.items():
            target.writestr(name, body)
        target.writestr("../escape.txt", b"bad")
    result = verify(output.getvalue(), trusted_keys=trusted)
    assert result.status == "INVALID"
    assert result.reason == "UNSAFE_ARCHIVE_PATH"
