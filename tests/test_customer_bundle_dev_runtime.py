"""Loopback-only Development customer-bundle runtime contracts."""
from __future__ import annotations

import base64

from cryptography.fernet import Fernet


def _development_environment(tmp_path):
    return {
        "OLA_DEPLOYMENT_PROFILE": "development",
        "OLA_PUBLIC_BASE_URL": "http://127.0.0.1:8000",
        "OLA_HUMAN_SESSION_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "OLA_CUSTOMER_BUNDLE_STORAGE_KEY": base64.urlsafe_b64encode(
            b"dev-storage-key-32-bytes-exact!!"
        ).decode("ascii"),
        "OLA_CUSTOMER_BUNDLE_STORAGE_PATH": str(tmp_path / "private-bundles"),
    }


def test_development_runtime_builds_stable_separate_test_signers_and_encrypted_storage(tmp_path):
    from app.customer_bundle.dev_runtime import (
        development_customer_bundle_runtime_from_environment,
    )

    environment = _development_environment(tmp_path)
    first = development_customer_bundle_runtime_from_environment(
        profile="development",
        environment=environment,
    )
    after_restart = development_customer_bundle_runtime_from_environment(
        profile="development",
        environment=environment,
    )

    assert first is not None
    assert first.profile == "CUSTOMER_BUNDLE_SANDBOX_V1"
    assert first.igor_signer.test_only is True
    assert first.ola_signer.test_only is True
    assert first.igor_signer.key_id != first.ola_signer.key_id
    assert first.igor_signer.custody_id != first.ola_signer.custody_id
    assert first.igor_signer.public_key_bytes != first.ola_signer.public_key_bytes
    assert first.igor_signer.public_key_bytes == after_restart.igor_signer.public_key_bytes
    assert first.ola_signer.public_key_bytes == after_restart.ola_signer.public_key_bytes
    assert first.trusted_keys == {
        first.igor_signer.key_id: first.igor_signer.public_key_bytes,
        first.ola_signer.key_id: first.ola_signer.public_key_bytes,
    }

    payload = b"development bundle fixture"
    reference = first.storage.put(payload)
    stored_file = next((tmp_path / "private-bundles").glob("*.olb"))
    assert payload not in stored_file.read_bytes()
    assert first.storage.get(reference) == payload


def test_development_runtime_attestation_is_explicitly_marked_as_a_fixture(tmp_path):
    from app.customer_bundle.dev_runtime import (
        development_customer_bundle_runtime_from_environment,
    )

    runtime = development_customer_bundle_runtime_from_environment(
        profile="development",
        environment=_development_environment(tmp_path),
    )

    attestation = runtime.igor_attestation_provider({
        "order_id": "order-dev-1",
        "report_sha256": "a" * 64,
        "approved_tip_hash": "b" * 64,
        "evidence_tip_hash": "c" * 64,
    })

    assert attestation == {
        "status": "VERIFIED",
        "order_id": "order-dev-1",
        "report_sha256": "a" * 64,
        "approved_tip_hash": "b" * 64,
        "evidence_tip_hash": "c" * 64,
        "attestation_profile": "DEVELOPMENT_FIXTURE",
        "verifier": "OLA_DEVELOPMENT_FIXTURE",
    }
    assert runtime.provenance_provider({"order_id": "order-dev-1"}) is None


def test_development_runtime_refuses_public_https_and_production_profiles(tmp_path):
    from app.customer_bundle.dev_runtime import (
        development_customer_bundle_runtime_from_environment,
    )

    environment = _development_environment(tmp_path)
    public_environment = {
        **environment,
        "OLA_PUBLIC_BASE_URL": "https://ola-development.example.test",
    }
    production_environment = {
        **environment,
        "OLA_DEPLOYMENT_PROFILE": "production",
        "OLA_PUBLIC_BASE_URL": "http://127.0.0.1:8000",
    }

    assert development_customer_bundle_runtime_from_environment(
        profile="production",
        environment=public_environment,
    ) is None
    assert development_customer_bundle_runtime_from_environment(
        profile="production",
        environment=production_environment,
    ) is None
    assert development_customer_bundle_runtime_from_environment(
        profile="development",
        environment=public_environment,
    ) is None


def test_development_runtime_fails_closed_on_missing_or_reused_encryption_keys(tmp_path):
    from app.customer_bundle.dev_runtime import (
        development_customer_bundle_runtime_from_environment,
    )

    environment = _development_environment(tmp_path)
    missing_storage_key = {
        key: value for key, value in environment.items()
        if key != "OLA_CUSTOMER_BUNDLE_STORAGE_KEY"
    }
    reused_key = {
        **environment,
        "OLA_CUSTOMER_BUNDLE_STORAGE_KEY": environment[
            "OLA_HUMAN_SESSION_ENCRYPTION_KEY"
        ],
    }

    assert development_customer_bundle_runtime_from_environment(
        profile="development",
        environment=missing_storage_key,
    ) is None
    assert development_customer_bundle_runtime_from_environment(
        profile="development",
        environment=reused_key,
    ) is None
