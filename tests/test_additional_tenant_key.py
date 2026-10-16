"""Additional local credentials preserve tenant isolation and existing identities.

These use disposable SQLite and the actual API. Distinct credentials are not
proof of distinct humans, and result review is not production permission.
"""
import concurrent.futures
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

from app.api_key_crypto import KeyConfigurationError, hash_api_key
from app.database import DB_PATH, SessionLocal
from app.main import app, append_record
from app.models import ApiKey, EvidenceRecord, Tenant
from conftest import bound_candidate_fields, review_body


def feature():
    # A missing implementation fails the behavior test, not test collection.
    try:
        module = importlib.import_module("scripts.provision_additional_tenant_key")
    except ModuleNotFoundError:
        pytest.fail("existing-tenant additional credential issuance is not implemented")
    assert callable(getattr(module, "issue_existing_tenant_key", None))
    return module


@pytest.fixture
def existing_tenant():
    tenant, requester = str(uuid.uuid4()), str(uuid.uuid4())
    raw = "requester-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=tenant, name="additional-key-" + uuid.uuid4().hex))
        db.flush()
        db.add(ApiKey(id=requester, tenant_id=tenant, key_hash=hash_api_key(raw)))
        db.commit()
    append_record(tenant, "generic", {"note": "preserve pre-existing evidence"})
    return tenant, requester, raw


def snapshot():
    with SessionLocal() as db:
        return {
            "tenants": sorted((row.id, row.name) for row in db.scalars(select(Tenant))),
            "keys": sorted((row.id, row.tenant_id, row.key_hash) for row in db.scalars(select(ApiKey))),
            "evidence": sorted((row.id, row.tenant_id, row.seq, row.record_type,
                                row.payload_json, row.prev_hash, row.record_hash, row.hash_version)
                               for row in db.scalars(select(EvidenceRecord))),
        }


def args_for(existing_tenant):
    tenant, requester, _ = existing_tenant
    return ["--tenant-id", tenant, "--expected-requester-id", requester,
            "--expected-key-count", "1"]


def terminal(monkeypatch, stdin=True, stdout=True):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: stdin)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: stdout)


@pytest.fixture
def isolated_inventory(existing_tenant, tmp_path, monkeypatch):
    """A real independent SQLite copy whose path can safely disappear."""
    issuer = feature()
    path = tmp_path / "baza # ąę %20.db"
    with sqlite3.connect(DB_PATH) as source, sqlite3.connect(path) as target:
        source.backup(target)
    monkeypatch.setattr(issuer, "DB_PATH", str(path))
    return issuer, path


@pytest.mark.parametrize("operation", ["inspect", "issue", "cli-dry", "cli-apply"])
def test_disappearing_database_after_file_check_is_never_recreated(
        existing_tenant, isolated_inventory, monkeypatch, capsys, operation):
    issuer, path = isolated_inventory
    saved = path.with_name("preserved-original.db")
    original_bytes = path.read_bytes()
    original_is_file = Path.is_file
    checks = 0
    target_check = 2 if operation.startswith("cli-") else 1
    def checked_then_moved(candidate):
        nonlocal checks
        result = original_is_file(candidate)
        if candidate == path and result:
            checks += 1
            if checks == target_check:
                path.rename(saved)
        return result
    monkeypatch.setattr(Path, "is_file", checked_then_moved)
    tenant, requester, _ = existing_tenant
    if operation.startswith("cli-"):
        terminal(monkeypatch)
        args = args_for(existing_tenant)
        if operation == "cli-apply":
            args += ["--apply", "--acknowledge-full-tenant-access"]
        assert issuer.main(args) == 2
        output = capsys.readouterr()
        assert "BLOCKED" in output.err and "ola2_" not in output.out + output.err
    else:
        call = issuer.inspect_existing_tenant if operation == "inspect" else issuer.issue_existing_tenant_key
        with pytest.raises(OperationalError):
            call(tenant, expected_requester_id=requester)
    assert checks == target_check
    assert not path.exists(), "a missing deployment DB must never be auto-created"
    assert saved.read_bytes() == original_bytes


def test_existing_database_path_with_spaces_unicode_hash_and_percent(
        existing_tenant, isolated_inventory):
    issuer, path = isolated_inventory
    tenant, requester, _ = existing_tenant
    before = path.read_bytes()
    inspection = issuer.inspect_existing_tenant(tenant, expected_requester_id=requester)
    assert inspection["status"] == "DRY_RUN" and path.read_bytes() == before
    _, credential_id, raw = issuer.issue_existing_tenant_key(tenant, expected_requester_id=requester)
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT id, tenant_id, key_hash FROM api_keys WHERE tenant_id=?", (tenant,)).fetchall()
    assert len(rows) == 2 and (credential_id, tenant, hash_api_key(raw)) in rows
    assert len(list(path.parent.glob("*.db"))) == 1


def test_additional_key_authenticates_same_tenant_as_distinct_identity(existing_tenant):
    issuer = feature()
    tenant, requester, old_raw = existing_tenant
    before = snapshot()
    actual_tenant, credential, raw = issuer.issue_existing_tenant_key(
        tenant, expected_requester_id=requester)
    assert actual_tenant == tenant
    assert credential != requester
    assert str(uuid.UUID(credential)) == credential
    assert raw.startswith("ola2_") and len(raw) >= 50 and raw != old_raw
    client = TestClient(app)
    old = client.get("/auth/session", headers={"X-API-Key": old_raw})
    new = client.get("/auth/session", headers={"X-API-Key": raw})
    assert old.status_code == new.status_code == 200
    assert old.json()["tenant_id"] == new.json()["tenant_id"] == tenant
    assert old.json()["credential_id"] == requester
    assert new.json()["credential_id"] == credential
    assert raw not in new.text and old_raw not in old.text
    after = snapshot()
    assert before["tenants"] == after["tenants"]
    assert before["evidence"] == after["evidence"]
    assert set(before["keys"]).issubset(after["keys"])
    added = [row for row in after["keys"] if row not in before["keys"]]
    assert added == [(credential, tenant, hash_api_key(raw))]
    assert added[0][2] != raw and len(added[0][2]) == 64


def test_32_hex_existing_ids_are_not_rewritten():
    issuer = feature()
    tenant, requester = uuid.uuid4().hex, uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=tenant, name="hex-ids")); db.flush()
        db.add(ApiKey(id=requester, tenant_id=tenant,
                      key_hash=hash_api_key("requester-" + uuid.uuid4().hex)))
        db.commit()
    actual, _, _ = issuer.issue_existing_tenant_key(tenant, expected_requester_id=requester)
    assert actual == tenant


@pytest.mark.parametrize("field,value", [
    ("tenant", None), ("tenant", ""), ("tenant", "../ola.db"),
    ("tenant", "{" + "a" * 32 + "}"), ("tenant", "a" * 36),
    ("requester", True), ("requester", "not-an-id"),
    ("count", True), ("count", False), ("count", 0),
    ("count", -1), ("count", "1"), ("count", 1.0),
])
def test_invalid_pins_never_mutate(existing_tenant, field, value):
    issuer = feature()
    tenant, requester, _ = existing_tenant
    kwargs = {"tenant": tenant, "requester": requester, "count": 1}
    kwargs[field] = value
    before = snapshot()
    with pytest.raises(ValueError):
        issuer.issue_existing_tenant_key(kwargs["tenant"],
            expected_requester_id=kwargs["requester"], expected_key_count=kwargs["count"])
    assert snapshot() == before


@pytest.mark.parametrize("kind", ["missing-tenant", "missing-requester", "foreign-requester", "count"])
def test_unknown_or_mismatched_inventory_never_mutates(existing_tenant, kind):
    issuer = feature()
    tenant, requester, _ = existing_tenant
    count = 1
    if kind == "missing-tenant":
        tenant = str(uuid.uuid4())
    elif kind == "missing-requester":
        requester = str(uuid.uuid4())
    elif kind == "foreign-requester":
        foreign = str(uuid.uuid4())
        requester = str(uuid.uuid4())
        with SessionLocal() as db:
            db.add(Tenant(id=foreign, name="foreign")); db.flush()
            db.add(ApiKey(id=requester, tenant_id=foreign,
                          key_hash=hash_api_key("foreign-" + uuid.uuid4().hex)))
            db.commit()
    else:
        count = 2
    before = snapshot()
    with pytest.raises(ValueError):
        issuer.issue_existing_tenant_key(tenant,
            expected_requester_id=requester, expected_key_count=count)
    assert snapshot() == before


def test_missing_pepper_never_mutates(existing_tenant, monkeypatch):
    issuer = feature()
    tenant, requester, _ = existing_tenant
    before = snapshot()
    monkeypatch.delenv("OLA_API_KEY_PEPPER", raising=False)
    with pytest.raises(KeyConfigurationError):
        issuer.issue_existing_tenant_key(tenant, expected_requester_id=requester)
    assert snapshot() == before


def test_repeat_with_original_count_is_refused(existing_tenant):
    issuer = feature()
    tenant, requester, _ = existing_tenant
    issuer.issue_existing_tenant_key(tenant, expected_requester_id=requester)
    before = snapshot()
    with pytest.raises(ValueError, match="count"):
        issuer.issue_existing_tenant_key(tenant, expected_requester_id=requester)
    assert snapshot() == before


def test_concurrent_issuance_with_same_count_adds_only_one_key(existing_tenant):
    issuer = feature()
    tenant, requester, _ = existing_tenant
    before = snapshot()
    start = threading.Barrier(2)
    def issue():
        start.wait(timeout=10)
        try:
            return issuer.issue_existing_tenant_key(tenant, expected_requester_id=requester)
        except ValueError as exc:
            return str(exc)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: issue(), range(2)))
    assert sum(isinstance(outcome, tuple) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, str) and "count" in outcome for outcome in outcomes) == 1
    after = snapshot()
    assert len(after["keys"]) == len(before["keys"]) + 1
    assert before["tenants"] == after["tenants"]
    assert before["evidence"] == after["evidence"]
    assert set(before["keys"]).issubset(after["keys"])


def test_cli_defaults_to_read_only_and_never_exposes_hashes(existing_tenant, capsys):
    issuer = feature()
    before = snapshot()
    assert issuer.main(args_for(existing_tenant)) == 0
    output = capsys.readouterr()
    body = json.loads(output.out)
    assert body["status"] == "DRY_RUN" and body["mutations"] == 0
    assert body["access_scope"] == "FULL_TENANT_ACCESS"
    assert body["assurance"] == "UNKNOWN" and body["production_eligible"] is False
    assert "ola2_" not in output.out and "X_API_KEY_ONCE" not in output.out
    assert all(row[2] not in output.out for row in before["keys"])
    assert snapshot() == before


@pytest.mark.parametrize("ack,stdin,stdout", [
    (False, True, True), (True, False, True),
    (True, True, False), (True, False, False),
])
def test_cli_apply_requires_ack_and_both_private_terminal_streams(
        existing_tenant, monkeypatch, capsys, ack, stdin, stdout):
    issuer = feature()
    terminal(monkeypatch, stdin, stdout)
    args = args_for(existing_tenant) + ["--apply"]
    if ack:
        args.append("--acknowledge-full-tenant-access")
    before = snapshot()
    assert issuer.main(args) == 2
    output = capsys.readouterr()
    assert "BLOCKED" in output.err and "ola2_" not in output.out + output.err
    assert snapshot() == before


def test_cli_apply_displays_only_new_secret_once_after_success(existing_tenant, monkeypatch, capsys):
    issuer = feature()
    terminal(monkeypatch)
    assert issuer.main(args_for(existing_tenant) + [
        "--apply", "--acknowledge-full-tenant-access"]) == 0
    output = capsys.readouterr()
    secrets = [line.removeprefix("X_API_KEY_ONCE: ") for line in output.out.splitlines()
               if line.startswith("X_API_KEY_ONCE: ")]
    assert len(secrets) == 1 and output.out.count(secrets[0]) == 1
    assert "FULL_TENANT_ACCESS" in output.out and "UNKNOWN" in output.out
    assert "PRODUCTION_ELIGIBLE: false" in output.out
    response = TestClient(app).get("/auth/session", headers={"X-API-Key": secrets[0]})
    assert response.status_code == 200
    assert response.json()["tenant_id"] == existing_tenant[0]
    assert response.json()["credential_id"] != existing_tenant[1]


@pytest.mark.parametrize("apply", [False, True])
def test_cli_does_not_create_unknown_database(existing_tenant, tmp_path, monkeypatch, capsys, apply):
    issuer = feature()
    missing = tmp_path / "unknown.db"
    monkeypatch.setattr(issuer, "DB_PATH", str(missing))
    terminal(monkeypatch)
    def forbidden_connection(**kwargs):
        pytest.fail("unknown configured DB must be refused before connecting")
    monkeypatch.setattr(issuer, "_database_session", forbidden_connection)
    args = args_for(existing_tenant)
    if apply:
        args += ["--apply", "--acknowledge-full-tenant-access"]
    assert issuer.main(args) == 2
    assert not missing.exists()
    output = capsys.readouterr()
    assert "BLOCKED" in output.err and "ola2_" not in output.out + output.err


def test_cli_database_exception_never_leaks_sql_or_parameters(existing_tenant, monkeypatch, capsys):
    issuer = feature()
    def broken_connection(**kwargs):
        raise OperationalError("SQL-with-private-values", {"key": "private-token-value"},
                               RuntimeError("sensitive-underlying-error"))
    monkeypatch.setattr(issuer, "_database_session", broken_connection)
    assert issuer.main(args_for(existing_tenant)) == 2
    output = capsys.readouterr()
    assert "OperationalError" in output.err
    for private in ("SQL-with-private-values", "private-token-value", "sensitive-underlying-error"):
        assert private not in output.out + output.err


def test_failed_commit_never_prints_credential_or_changes_inventory(existing_tenant, monkeypatch, capsys):
    issuer = feature()
    terminal(monkeypatch)
    before = snapshot()
    tenant = existing_tenant[0]
    def refuse_new_key(mapper, connection, target):
        if target.tenant_id == tenant:
            raise OperationalError("private-key-insert", {"key": "private-parameter"},
                                   RuntimeError("private-driver-error"))
    event.listen(ApiKey, "before_insert", refuse_new_key)
    try:
        assert issuer.main(args_for(existing_tenant) + [
            "--apply", "--acknowledge-full-tenant-access"]) == 2
    finally:
        event.remove(ApiKey, "before_insert", refuse_new_key)
    output = capsys.readouterr()
    assert "OperationalError" in output.err
    for private in ("ola2_", "private-key-insert", "private-parameter", "private-driver-error"):
        assert private not in output.out + output.err
    assert snapshot() == before


def test_additional_credential_reviews_only_own_tenant_result(existing_tenant, local_binding_source):
    issuer = feature()
    tenant, requester, requester_key = existing_tenant
    _, new_id, new_key = issuer.issue_existing_tenant_key(tenant, expected_requester_id=requester)
    foreign_tenant, foreign_id = str(uuid.uuid4()), str(uuid.uuid4())
    foreign_key = "foreign-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=foreign_tenant, name="foreign-review")); db.flush()
        db.add(ApiKey(id=foreign_id, tenant_id=foreign_tenant, key_hash=hash_api_key(foreign_key)))
        db.commit()
    run = "additional-key-review-" + uuid.uuid4().hex
    candidate = append_record(tenant, "decision.candidate", {
        "run_id": run, "requester_id": requester,
        **bound_candidate_fields(tenant, requester, run),
        "status_fields": {"RUNTIME": "VERIFIED", "EVIDENCE": "VERIFIED",
                          "REPLAY_INTEGRITY": "VERIFIED", "POLICY": "VERIFIED",
                          "HUMAN_GATE": "REVIEW", "EXECUTION_ALLOWED": "REVIEW"},
        "candidate_status": "REVIEW",
    })
    body = review_body(tenant, run, candidate["record_hash"])
    client = TestClient(app)
    def approve(key):
        return client.post(f"/nina-run/{run}/approve",
                           headers={"Authorization": "Bearer " + key}, json=body)
    assert approve(requester_key).status_code == 403
    assert approve(foreign_key).status_code == 404
    response = approve(new_key)
    assert response.status_code == 200, response.text
    approval = response.json()
    assert approval["status"] == "APPROVED" and approval["approver_id"] == new_id
    assert approval["assurance"] == "UNKNOWN" and approval["production_eligible"] is False
    assert approval["scope"] == "review-result"
    assert approve(new_key).status_code == 409
