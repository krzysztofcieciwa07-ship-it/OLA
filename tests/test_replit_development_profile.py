"""Replit workspace Development must be distinguished from published deployments."""
from __future__ import annotations

import base64

from cryptography.fernet import Fernet


def _environment(tmp_path):
    return {
        "OLA_DEPLOYMENT_PROFILE": "development",
        "OLA_PUBLIC_BASE_URL": "https://workspace-123.server.replit.dev",
        "REPLIT_DEV_DOMAIN": "workspace-123.server.replit.dev",
        "OLA_HUMAN_SESSION_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "OLA_CUSTOMER_BUNDLE_STORAGE_KEY": base64.urlsafe_b64encode(
            b"dev-storage-key-32-bytes-exact!!"
        ).decode("ascii"),
        "OLA_CUSTOMER_BUNDLE_STORAGE_PATH": str(tmp_path / "private-bundles"),
    }


def test_deployment_profile_accepts_only_exact_replit_workspace_dev_domain(monkeypatch):
    from app.human_identity.routes import _deployment_profile

    monkeypatch.setenv("OLA_DEPLOYMENT_PROFILE", "development")
    monkeypatch.setenv("OLA_PUBLIC_BASE_URL", "https://workspace-123.server.replit.dev")
    monkeypatch.setenv("REPLIT_DEV_DOMAIN", "workspace-123.server.replit.dev")
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)

    assert _deployment_profile() == "development"


def test_deployment_profile_rejects_replit_dev_domain_host_mismatch(monkeypatch):
    from app.human_identity.routes import _deployment_profile

    monkeypatch.setenv("OLA_DEPLOYMENT_PROFILE", "development")
    monkeypatch.setenv("OLA_PUBLIC_BASE_URL", "https://attacker.server.replit.dev")
    monkeypatch.setenv("REPLIT_DEV_DOMAIN", "workspace-123.server.replit.dev")
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)

    assert _deployment_profile() == "production"


def test_deployment_profile_never_treats_a_published_replit_deployment_as_development(monkeypatch):
    from app.human_identity.routes import _deployment_profile

    monkeypatch.setenv("OLA_DEPLOYMENT_PROFILE", "development")
    monkeypatch.setenv("OLA_PUBLIC_BASE_URL", "https://workspace-123.server.replit.dev")
    monkeypatch.setenv("REPLIT_DEV_DOMAIN", "workspace-123.server.replit.dev")
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")

    assert _deployment_profile() == "production"


def test_replit_development_runtime_accepts_workspace_https_but_not_deployment(tmp_path):
    from app.customer_bundle.dev_runtime import (
        development_customer_bundle_runtime_from_environment,
    )

    environment = _environment(tmp_path)
    runtime = development_customer_bundle_runtime_from_environment(
        profile="development",
        environment=environment,
    )
    published = {
        **environment,
        "REPLIT_DEPLOYMENT": "1",
    }

    assert runtime is not None
    assert runtime.profile == "CUSTOMER_BUNDLE_SANDBOX_V1"
    assert development_customer_bundle_runtime_from_environment(
        profile="development",
        environment=published,
    ) is None


def test_replit_development_runtime_rejects_domain_spoofing(tmp_path):
    from app.customer_bundle.dev_runtime import (
        development_customer_bundle_runtime_from_environment,
    )

    environment = {
        **_environment(tmp_path),
        "OLA_PUBLIC_BASE_URL": "https://attacker.server.replit.dev",
    }

    assert development_customer_bundle_runtime_from_environment(
        profile="development",
        environment=environment,
    ) is None


def test_replit_deployment_marker_forces_production_even_for_loopback_origin(monkeypatch):
    from app.human_identity.routes import _deployment_profile
    from app.customer_bundle.dev_runtime import (
        development_customer_bundle_runtime_from_environment,
    )

    monkeypatch.setenv("OLA_DEPLOYMENT_PROFILE", "development")
    monkeypatch.setenv("OLA_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("REPLIT_DEV_DOMAIN", "workspace-123.server.replit.dev")
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")

    environment = {
        "OLA_DEPLOYMENT_PROFILE": "development",
        "OLA_PUBLIC_BASE_URL": "http://127.0.0.1:8000",
        "REPLIT_DEV_DOMAIN": "workspace-123.server.replit.dev",
        "REPLIT_DEPLOYMENT": "1",
        "OLA_HUMAN_SESSION_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "OLA_CUSTOMER_BUNDLE_STORAGE_KEY": base64.urlsafe_b64encode(
            b"dev-storage-key-32-bytes-exact!!"
        ).decode("ascii"),
    }

    assert _deployment_profile() == "production"
    assert development_customer_bundle_runtime_from_environment(
        profile="development",
        environment=environment,
    ) is None
