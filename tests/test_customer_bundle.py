"""TDD contracts for independently dual-signed OLA customer evidence bundles."""
import base64
import io
import json
import hashlib
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
        "bundle_id": "12345678-1234-4234-8234-123456789abc",
        "bundle_version": 1,
        "created_at": 1_800_000_100,
        "expires_at": 1_900_000_100,
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
            "report_sha256": hashlib.sha256(
                b'{"order_id":"order-customer-bundle-1","result":"verified"}'
            ).hexdigest(),
            "requester_person_ref": "person-ref-requester",
            "approver_person_ref": "person-ref-approver",
            "reviewer_person_ref": "person-ref-reviewer",
        },
        "igor_attestation": {
            "status": "VERIFIED",
            "order_id": "order-customer-bundle-1",
            "report_sha256": None,
            "approved_tip_hash": "b" * 64,
            "evidence_tip_hash": "c" * 64,
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



def test_test_only_signer_generates_fresh_ephemeral_ed25519_keys():
    _build, TestSigner, _verify = _bundle_api()
    first = TestSigner.generate(key_id="ephemeral-key-a", custody_id="test-custody-a")
    second = TestSigner.generate(key_id="ephemeral-key-b", custody_id="test-custody-b")
    assert first.public_key_bytes != second.public_key_bytes
    message = b"ephemeral-signing-key-regression"
    assert first.sign(message) != second.sign(message)

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
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["bundle_id"] == values["bundle_id"]
        assert manifest["bundle_version"] == values["bundle_version"]
        assert manifest["created_at"] == values["created_at"]
        assert manifest["expires_at"] == values["expires_at"]
        assert "manifest.json" not in manifest["files"]
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



def test_bundle_builder_rejects_approval_digest_for_a_different_report():
    build, TestSigner, _verify = _bundle_api()
    igor = TestSigner.generate(key_id="igor-approval-binding", custody_id="igor-test-custody")
    ola = TestSigner.generate(key_id="ola-approval-binding", custody_id="ola-test-custody")
    values = _inputs()
    values["approval"]["report_sha256"] = "0" * 64
    values["igor_attestation"]["report_sha256"] = hashlib.sha256(
        values["report_json"]
    ).hexdigest()

    with pytest.raises(ValueError, match="approval report digest does not match"):
        build(**values, igor_signer=igor, ola_signer=ola)


def test_bundle_builder_rejects_signing_timestamp_before_human_approval():
    build, TestSigner, _verify = _bundle_api()
    igor = TestSigner.generate(key_id="igor-time-order", custody_id="igor-test-custody")
    ola = TestSigner.generate(key_id="ola-time-order", custody_id="ola-test-custody")
    values = _inputs()
    values["igor_attestation"]["report_sha256"] = hashlib.sha256(
        values["report_json"]
    ).hexdigest()
    values["signed_at"] = values["approved_at"] - 1

    with pytest.raises(ValueError, match="signing timestamp precedes approval"):
        build(**values, igor_signer=igor, ola_signer=ola)



def test_manifest_binds_report_without_requiring_order_id_inside_approved_report_bytes():
    build, TestSigner, verify = _bundle_api()
    igor = TestSigner.generate(key_id="igor-report-order-bind", custody_id="igor-test-custody")
    ola = TestSigner.generate(key_id="ola-report-order-bind", custody_id="ola-test-custody")
    values = _inputs()
    values["report_json"] = b'{"report_id":"order-customer-bundle-1","summary":"verified"}'
    digest = hashlib.sha256(values["report_json"]).hexdigest()
    values["approval"]["report_sha256"] = digest
    values["igor_attestation"]["report_sha256"] = digest

    artifact = build(**values, igor_signer=igor, ola_signer=ola)
    result = verify(
        artifact.zip_bytes,
        trusted_keys={
            igor.key_id: igor.public_key_bytes,
            ola.key_id: ola.public_key_bytes,
        },
    )
    assert result.status == "PARTIAL"
    assert result.report_sha256 == digest



def test_builder_and_offline_verifier_reject_the_same_public_key_under_two_signer_ids(monkeypatch):
    build, TestSigner, verify = _bundle_api()
    from app.customer_bundle import builder as builder_module
    from app.customer_bundle.signers import RemoteEd25519Signer

    igor = TestSigner.generate(
        key_id="igor-shared-key", custody_id="igor-independent-custody",
    )
    ola_alias = RemoteEd25519Signer(
        key_id="ola-alias-key",
        custody_id="ola-different-custody",
        public_key_bytes=igor.public_key_bytes,
        sign_request=lambda _key_id, message: igor.sign(message),
    )
    values = _inputs()
    values["igor_attestation"]["report_sha256"] = hashlib.sha256(
        values["report_json"]
    ).hexdigest()

    with pytest.raises(ValueError, match="distinct Ed25519 public keys"):
        build(**values, igor_signer=igor, ola_signer=ola_alias)

    # Exercise the independent offline verifier against a deliberately forged
    # package. Bypass only the builder's guard so the verifier itself must reject
    # the two aliases even though their key IDs and custody labels differ.
    monkeypatch.setattr(builder_module, "_validate_signers", lambda *_args, **_kwargs: None)
    forged = build(**values, igor_signer=igor, ola_signer=ola_alias)
    result = verify(
        forged.zip_bytes,
        trusted_keys={
            igor.key_id: igor.public_key_bytes,
            ola_alias.key_id: igor.public_key_bytes,
        },
    )
    assert result.status == "INVALID"
    assert result.reason == "SIGNER_PUBLIC_KEYS_NOT_INDEPENDENT"


def test_offline_verifier_rejects_manifest_without_persisted_bundle_identity():
    build, TestSigner, verify = _bundle_api()
    igor = TestSigner.generate(key_id="igor-metadata-key", custody_id="igor-metadata-custody")
    ola = TestSigner.generate(key_id="ola-metadata-key", custody_id="ola-metadata-custody")
    values = _inputs()
    values["igor_attestation"]["report_sha256"] = hashlib.sha256(values["report_json"]).hexdigest()
    artifact = build(**values, igor_signer=igor, ola_signer=ola)

    source = zipfile.ZipFile(io.BytesIO(artifact.zip_bytes))
    with source:
        entries = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(entries["manifest.json"])
    manifest.pop("bundle_id")
    from app.customer_bundle.builder import canonical_json_bytes
    changed_manifest = canonical_json_bytes(manifest)
    entries["manifest.json"] = changed_manifest
    entries["manifest.sig"] = base64.urlsafe_b64encode(
        ola.sign(changed_manifest)
    ).rstrip(b"=")
    changed = io.BytesIO()
    with zipfile.ZipFile(changed, "w", compression=zipfile.ZIP_STORED) as target:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            target.writestr(info, entries[name])

    result = verify(
        changed.getvalue(),
        trusted_keys={igor.key_id: igor.public_key_bytes, ola.key_id: ola.public_key_bytes},
    )
    assert result.status == "INVALID"
    assert result.reason == "BUNDLE_ID_INVALID"


def test_package_integrity_status_is_separate_from_expiry_lifecycle():
    build, TestSigner, verify = _bundle_api()
    igor = TestSigner.generate(key_id="igor-lifecycle-key", custody_id="igor-lifecycle-custody")
    ola = TestSigner.generate(key_id="ola-lifecycle-key", custody_id="ola-lifecycle-custody")
    values = _inputs()
    values["igor_attestation"]["report_sha256"] = hashlib.sha256(
        values["report_json"]
    ).hexdigest()
    artifact = build(**values, igor_signer=igor, ola_signer=ola)
    trusted = {
        igor.key_id: igor.public_key_bytes,
        ola.key_id: ola.public_key_bytes,
    }

    active = verify(artifact.zip_bytes, trusted_keys=trusted, now=values["expires_at"] - 1)
    expired = verify(artifact.zip_bytes, trusted_keys=trusted, now=values["expires_at"])

    assert active.status == "PARTIAL"
    assert active.lifecycle_status == "ACTIVE"
    assert expired.status == "PARTIAL"
    assert expired.lifecycle_status == "EXPIRED"
    assert expired.manifest_sha256 == artifact.manifest_sha256


def _production_bundle_with_remote_signers():
    from app.customer_bundle.builder import build_customer_bundle
    from app.customer_bundle.signers import RemoteEd25519Signer, TestOnlyEd25519Signer

    igor_key = TestOnlyEd25519Signer.generate(
        key_id="igor-prod-contract", custody_id="igor-remote-custody",
    )
    ola_key = TestOnlyEd25519Signer.generate(
        key_id="ola-prod-contract", custody_id="ola-remote-custody",
    )
    igor = RemoteEd25519Signer(
        key_id=igor_key.key_id, custody_id=igor_key.custody_id,
        public_key_bytes=igor_key.public_key_bytes,
        sign_request=lambda _key_id, message: igor_key.sign(message),
    )
    ola = RemoteEd25519Signer(
        key_id=ola_key.key_id, custody_id=ola_key.custody_id,
        public_key_bytes=ola_key.public_key_bytes,
        sign_request=lambda _key_id, message: ola_key.sign(message),
    )
    values = _inputs()
    values.update({
        "profile": "CUSTOMER_BUNDLE_PRODUCTION_V1",
        "provenance_json": b'{"attestation":"opaque-test-fixture"}',
        "provenance_verified": True,
        "source_sha": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "timestamp_provider": lambda _manifest: b"timestamp-test-fixture",
        "timestamp_verifier": lambda _token, _manifest, _signed_at: True,
    })
    values["igor_attestation"]["report_sha256"] = hashlib.sha256(
        values["report_json"]
    ).hexdigest()
    artifact = build_customer_bundle(
        **values, igor_signer=igor, ola_signer=ola,
    )
    trusted = {
        igor.key_id: igor.public_key_bytes,
        ola.key_id: ola.public_key_bytes,
    }
    return artifact, trusted, values


def test_production_offline_verifier_fails_closed_without_independent_provenance_verifier():
    _build, _TestSigner, verify = _bundle_api()
    artifact, trusted, _values = _production_bundle_with_remote_signers()

    result = verify(
        artifact.zip_bytes,
        trusted_keys=trusted,
        timestamp_verifier=lambda _token, _manifest, _signed_at: True,
    )

    assert result.status == "INVALID"
    assert result.reason == "PROVENANCE_ATTESTATION_VERIFIER_NOT_CONFIGURED"


def test_production_offline_verifier_binds_provenance_to_exact_source_and_image():
    _build, _TestSigner, verify = _bundle_api()
    artifact, trusted, values = _production_bundle_with_remote_signers()
    observed = {}

    def provenance_verifier(raw, source_sha, image_digest):
        observed["raw"] = raw
        observed["source_sha"] = source_sha
        observed["image_digest"] = image_digest
        return True

    result = verify(
        artifact.zip_bytes,
        trusted_keys=trusted,
        timestamp_verifier=lambda _token, _manifest, _signed_at: True,
        provenance_verifier=provenance_verifier,
        now=values["created_at"],
    )

    assert observed == {
        "raw": values["provenance_json"],
        "source_sha": values["source_sha"],
        "image_digest": values["image_digest"],
    }
    assert result.status == "VERIFIED"
