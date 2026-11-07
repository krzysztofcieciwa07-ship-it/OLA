"""Fail-closed CORE readiness contract; not a production certification.

Liveness (/health) is independent from readiness (/readyz).
"""
from fastapi.testclient import TestClient

from app.main import app
from app.database import engine, install_append_only_triggers


def client():
    return TestClient(app)


def test_readyz_blocks_if_commit_missing(monkeypatch):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "runtime-check-fixture-0123456789abcdef")
    monkeypatch.delenv("OLA_RUNTIME_COMMIT", raising=False)
    response = client().get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["core_status"] == "BLOCKED"
    assert "source_commit" in body["failed_checks"]
    assert body["system_acceptance"] == "NOT_VERIFIED"


def test_readyz_blocks_if_auth_pepper_missing(monkeypatch):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "a" * 40)
    monkeypatch.delenv("OLA_API_KEY_PEPPER", raising=False)
    response = client().get("/readyz")
    assert response.status_code == 503
    assert "api_key_pepper" in response.json()["failed_checks"]


def test_readyz_does_not_leak_pepper_and_returns_core_only(monkeypatch):
    secret = "runtime-test-secret-0123456789abcdef"
    monkeypatch.setenv("OLA_API_KEY_PEPPER", secret)
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "a" * 40)
    response = client().get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["core_status"] == "READY"
    assert body["system_acceptance"] == "NOT_VERIFIED"
    assert body["source_commit"] == "a" * 40
    assert body["failed_checks"] == []
    assert secret not in response.text


def test_readyz_blocks_without_append_only_evidence_guards(monkeypatch):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "runtime-check-fixture-0123456789abcdef")
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "b" * 40)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TRIGGER IF EXISTS evidence_no_update")
        response = client().get("/readyz")
        assert response.status_code == 503
        assert "evidence_append_only" in response.json()["failed_checks"]
    finally:
        install_append_only_triggers()


def test_readyz_blocks_invalid_commit_even_with_valid_db(monkeypatch):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "runtime-check-fixture-0123456789abcdef")
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "not-a-sha")
    response = client().get("/readyz")
    assert response.status_code == 503
    assert "source_commit" in response.json()["failed_checks"]


def test_readyz_blocks_a_spoofed_noop_trigger(monkeypatch):
    """A trigger name is not proof of a trigger's actual enforcement."""
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "c" * 40)
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "runtime-check-fixture-0123456789abcdef")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TRIGGER IF EXISTS evidence_no_update")
            conn.exec_driver_sql(
                "CREATE TRIGGER evidence_no_update "
                "BEFORE UPDATE ON evidence_records BEGIN SELECT 1; END;"
            )
        response = client().get("/readyz")
        assert response.status_code == 503
        assert "evidence_append_only" in response.json()["failed_checks"]
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TRIGGER IF EXISTS evidence_no_update")
        install_append_only_triggers()


def test_strict_readyz_blocks_mutable_build_info_and_ignores_env_spoof(monkeypatch, tmp_path):
    import json
    path = tmp_path / "ola-build-info.json"
    source = "a" * 40
    path.write_text(json.dumps({"schema": "ola-build-info/v1", "source_commit": source}))
    path.chmod(0o644)
    monkeypatch.setenv("OLA_REQUIRE_BUILD_INFO", "1")
    monkeypatch.setenv("OLA_BUILD_INFO_PATH", str(path))
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "b" * 40)
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "runtime-check-fixture-0123456789abcdef")
    response = client().get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["source_commit"] == source
    assert "build_info_mutable" in body["failed_checks"]


def test_strict_readyz_accepts_read_only_embedded_build_info(monkeypatch, tmp_path):
    import json
    path = tmp_path / "ola-build-info.json"
    source = "c" * 40
    path.write_text(json.dumps({"schema": "ola-build-info/v1", "source_commit": source}))
    path.chmod(0o444)
    tmp_path.chmod(0o555)
    monkeypatch.setenv("OLA_REQUIRE_BUILD_INFO", "1")
    monkeypatch.setenv("OLA_BUILD_INFO_PATH", str(path))
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "d" * 40)
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "runtime-check-fixture-0123456789abcdef")
    try:
        response = client().get("/readyz")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source_commit"] == source
        assert body["core_status"] == "READY"
    finally:
        tmp_path.chmod(0o755)
