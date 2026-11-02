"""Local credential administration uses real SQLite, KDF and API boundaries."""
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

from app.api_key_crypto import hash_api_key
from app.database import DB_PATH, SessionLocal
from app.hashchain import verify_chain
from app.main import app, append_record
from app.models import ApiKey, EvidenceRecord, Tenant


def feature(kind="issuer"):
    name = "provision_reviewer_credential" if kind == "issuer" else "revoke_tenant_credential"
    try:
        module = importlib.import_module("scripts." + name)
    except ModuleNotFoundError:
        pytest.fail("local " + name + " administration is not implemented")
    return module


@pytest.fixture
def operator():
    tenant, credential = str(uuid.uuid4()), str(uuid.uuid4())
    raw = "admin-fixture-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=tenant, name="admin-" + uuid.uuid4().hex))
        db.flush()
        db.add(ApiKey(id=credential, tenant_id=tenant, key_hash=hash_api_key(raw)))
        db.commit()
    append_record(tenant, "generic", {"note": "existing evidence stays intact"})
    return tenant, credential, raw


def snapshot(tenant):
    with SessionLocal() as db:
        keys = sorted((row.id, row.tenant_id, row.key_hash,
                       getattr(row, "access_scope", None), getattr(row, "revoked_at", None))
                      for row in db.scalars(select(ApiKey).where(ApiKey.tenant_id == tenant)))
        rows = [dict((name, getattr(row, name)) for name in (
            "id", "tenant_id", "seq", "record_type", "hash_version", "payload_json",
            "prev_hash", "record_hash")) for row in db.scalars(select(EvidenceRecord).where(
                EvidenceRecord.tenant_id == tenant).order_by(EvidenceRecord.seq))]
    return keys, rows


def issue(operator):
    tenant, requester, _ = operator
    return feature().issue_reviewer_credential(
        tenant, expected_requester_id=requester, expected_active_key_count=1)


def revoke_kwargs(operator, credential):
    return {"credential_id": credential, "expected_requester_id": operator[1],
            "expected_target_scope": "REVIEW_RESULT", "expected_active_key_count": 2}


def issuer_args(operator):
    return ["--tenant-id", operator[0], "--expected-requester-id", operator[1],
            "--expected-active-key-count", "1"]


def revoker_args(operator, credential):
    return ["--tenant-id", operator[0], "--credential-id", credential,
            "--expected-requester-id", operator[1], "--expected-target-scope", "REVIEW_RESULT",
            "--expected-active-key-count", "2"]


def terminal(monkeypatch, stdin=True, stdout=True):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: stdin)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: stdout)


def test_issue_review_only_key_preserves_existing_rows_and_authenticates(operator):
    issuer = feature()
    tenant, requester, old_secret = operator
    before = snapshot(tenant)
    actual, credential, raw = issuer.issue_reviewer_credential(
        tenant, expected_requester_id=requester, expected_active_key_count=1)
    assert actual == tenant and credential != requester
    assert raw.startswith("ola2_") and len(raw) >= 50 and raw != old_secret
    after = snapshot(tenant)
    assert set(before[0]).issubset(after[0]) and before[1] == after[1]
    added = [row for row in after[0] if row not in before[0]]
    assert added == [(credential, tenant, hash_api_key(raw), "REVIEW_RESULT", None)]
    client = TestClient(app)
    session = client.get("/auth/session", headers={"X-API-Key": raw})
    assert session.status_code == 200, session.text
    assert session.json()["tenant_id"] == tenant
    assert session.json()["credential_id"] == credential
    assert session.json()["scope"] == "REVIEW_RESULT"
    assert raw not in session.text
    denied = client.post("/evidence", headers={"X-API-Key": raw},
                         json={"record_type": "generic", "payload": {"reviewer": "write"}})
    assert denied.status_code == 403


def test_issuer_dry_run_has_no_mutation_secret_or_hash(operator, capsys):
    issuer = feature()
    before = snapshot(operator[0])
    assert issuer.main(issuer_args(operator)) == 0
    output = capsys.readouterr()
    receipt = json.loads(output.out)
    assert receipt["status"] == "DRY_RUN" and receipt["mutations"] == 0
    assert receipt["access_scope"] == "REVIEW_RESULT" and receipt["active_key_count"] == 1
    assert receipt["assurance"] == "UNKNOWN" and receipt["production_eligible"] is False
    assert "ola2_" not in output.out and "X_API_KEY_ONCE" not in output.out
    assert all(row[2] not in output.out for row in before[0])
    assert snapshot(operator[0]) == before


@pytest.mark.parametrize("ack,stdin,stdout", [
    (False, True, True), (True, False, True), (True, True, False), (True, False, False),
])
def test_issuer_apply_requires_acknowledgement_and_private_terminal(
        operator, monkeypatch, capsys, ack, stdin, stdout):
    issuer = feature()
    terminal(monkeypatch, stdin, stdout)
    before = snapshot(operator[0])
    args = issuer_args(operator) + ["--apply"]
    if ack:
        args.append("--acknowledge-review-result-access")
    assert issuer.main(args) == 2
    output = capsys.readouterr()
    assert "BLOCKED" in output.err and "ola2_" not in output.out + output.err
    assert snapshot(operator[0]) == before


def test_issuer_apply_reveals_one_new_secret_only_after_commit(operator, monkeypatch, capsys):
    issuer = feature()
    terminal(monkeypatch)
    assert issuer.main(issuer_args(operator) + ["--apply", "--acknowledge-review-result-access"]) == 0
    output = capsys.readouterr()
    raw = [line.split(": ", 1)[1] for line in output.out.splitlines()
           if line.startswith("X_API_KEY_ONCE: ")]
    assert len(raw) == 1 and output.out.count(raw[0]) == 1
    assert "ACCESS_SCOPE: REVIEW_RESULT" in output.out
    assert "ASSURANCE: UNKNOWN" in output.out and "PRODUCTION_ELIGIBLE: false" in output.out
    assert TestClient(app).get("/auth/session", headers={"X-API-Key": raw[0]}).status_code == 200


@pytest.mark.parametrize("bad_count", [True, False, 0, -1, 1.0, "1"])
def test_issue_invalid_count_never_mutates(operator, bad_count):
    issuer = feature()
    before = snapshot(operator[0])
    with pytest.raises(ValueError):
        issuer.issue_reviewer_credential(operator[0], expected_requester_id=operator[1],
                                         expected_active_key_count=bad_count)
    assert snapshot(operator[0]) == before


@pytest.mark.parametrize("pin", ["unknown-tenant", "foreign-requester", "count", "reviewer", "revoked"])
def test_issue_rejects_mismatched_or_inactive_requester(operator, pin):
    issuer = feature()
    tenant, requester, _ = operator
    count = 1
    if pin == "unknown-tenant":
        tenant = str(uuid.uuid4())
    elif pin == "foreign-requester":
        requester = str(uuid.uuid4())
    elif pin == "count":
        count = 2
    else:
        _, reviewer, _ = issue(operator)
        count = 2
        if pin == "reviewer":
            requester = reviewer
        else:
            with SessionLocal() as db:
                db.get(ApiKey, requester).revoked_at = 1
                db.commit()
            count = 1
    before = snapshot(operator[0])
    with pytest.raises(ValueError):
        issuer.issue_reviewer_credential(tenant, expected_requester_id=requester,
                                         expected_active_key_count=count)
    assert snapshot(operator[0]) == before


def test_issue_retry_and_concurrent_same_inventory_adds_only_one(operator):
    issuer = feature()
    start = threading.Barrier(2)
    def run():
        start.wait(timeout=10)
        try:
            return issuer.issue_reviewer_credential(operator[0],
                expected_requester_id=operator[1], expected_active_key_count=1)
        except ValueError as exc:
            return str(exc)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: run(), range(2)))
    assert sum(isinstance(outcome, tuple) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, str) and "count" in outcome for outcome in outcomes) == 1
    assert len(snapshot(operator[0])[0]) == 2


def test_revocation_retains_key_and_atomically_appends_verified_evidence(operator):
    revoker = feature("revoker")
    _, credential, raw = issue(operator)
    before = snapshot(operator[0])
    receipt = revoker.revoke_tenant_credential(operator[0], **revoke_kwargs(operator, credential))
    assert receipt["status"] == "REVOKED" and receipt["credential_id"] == credential
    assert receipt["assurance"] == "UNKNOWN" and receipt["production_eligible"] is False
    after = snapshot(operator[0])
    retained = next(row for row in after[0] if row[0] == credential)
    original = next(row for row in before[0] if row[0] == credential)
    assert retained[:4] == original[:4] and retained[4] == receipt["revoked_at"]
    assert after[1][:-1] == before[1] and verify_chain(after[1]) == (True, "ok")
    audit = after[1][-1]
    assert audit["record_type"] == "credential.revoked"
    payload = json.loads(audit["payload_json"])
    assert payload["credential_id"] == credential and payload["access_scope"] == "REVIEW_RESULT"
    assert payload["operator_pin_id"] == operator[1]
    assert raw not in audit["payload_json"] and original[2] not in audit["payload_json"]
    assert TestClient(app).get("/auth/session", headers={"X-API-Key": raw}).status_code == 401
    assert TestClient(app).get("/auth/session", headers={"X-API-Key": operator[2]}).status_code == 200


def test_revoker_dry_run_never_changes_inventory(operator, capsys):
    revoker = feature("revoker")
    _, credential, raw = issue(operator)
    before = snapshot(operator[0])
    assert revoker.main(revoker_args(operator, credential)) == 0
    output = capsys.readouterr()
    receipt = json.loads(output.out)
    assert receipt["status"] == "DRY_RUN" and receipt["mutations"] == 0
    assert receipt["active_key_count"] == 2 and receipt["credential_id"] == credential
    assert raw not in output.out + output.err
    assert snapshot(operator[0]) == before


@pytest.mark.parametrize("ack,stdin,stdout", [
    (False, True, True), (True, False, True), (True, True, False), (True, False, False),
])
def test_revoker_apply_requires_acknowledgement_and_private_terminal(
        operator, monkeypatch, capsys, ack, stdin, stdout):
    revoker = feature("revoker")
    _, credential, _ = issue(operator)
    before = snapshot(operator[0])
    terminal(monkeypatch, stdin, stdout)
    args = revoker_args(operator, credential) + ["--apply"]
    if ack:
        args.append("--acknowledge-revocation")
    assert revoker.main(args) == 2
    output = capsys.readouterr()
    assert "BLOCKED" in output.err and "ola2_" not in output.out + output.err
    assert snapshot(operator[0]) == before


def test_revoker_apply_outputs_only_public_receipt(operator, monkeypatch, capsys):
    revoker = feature("revoker")
    _, credential, raw = issue(operator)
    terminal(monkeypatch)
    assert revoker.main(revoker_args(operator, credential) + ["--apply", "--acknowledge-revocation"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "REVOKED"
    assert raw not in output.out + output.err and "X_API_KEY_ONCE" not in output.out


@pytest.mark.parametrize("pin", ["self", "scope", "count", "foreign", "revoked-requester"])
def test_revocation_invalid_pins_cannot_mutate(operator, pin):
    revoker = feature("revoker")
    _, credential, _ = issue(operator)
    kwargs = revoke_kwargs(operator, credential)
    if pin == "self":
        kwargs["credential_id"] = operator[1]
        kwargs["expected_target_scope"] = "OLA_CORE"
    elif pin == "scope":
        kwargs["expected_target_scope"] = "OLA_CORE"
    elif pin == "count":
        kwargs["expected_active_key_count"] = 3
    elif pin == "foreign":
        kwargs["credential_id"] = str(uuid.uuid4())
    else:
        with SessionLocal() as db:
            db.get(ApiKey, operator[1]).revoked_at = 1
            db.commit()
        kwargs["expected_active_key_count"] = 1
    before = snapshot(operator[0])
    with pytest.raises(ValueError):
        revoker.revoke_tenant_credential(operator[0], **kwargs)
    assert snapshot(operator[0]) == before


def test_concurrent_revocation_is_single_use(operator):
    revoker = feature("revoker")
    _, credential, _ = issue(operator)
    start = threading.Barrier(2)
    def run():
        start.wait(timeout=10)
        try:
            return revoker.revoke_tenant_credential(operator[0], **revoke_kwargs(operator, credential))
        except ValueError as exc:
            return str(exc)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: run(), range(2)))
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, str) and "revoked" in outcome for outcome in outcomes) == 1
    rows = snapshot(operator[0])[1]
    assert sum(row["record_type"] == "credential.revoked" for row in rows) == 1
    assert verify_chain(rows) == (True, "ok")


def test_failed_revocation_evidence_commit_rolls_back_key_and_chain(operator, monkeypatch, capsys):
    revoker = feature("revoker")
    _, credential, _ = issue(operator)
    before = snapshot(operator[0])
    terminal(monkeypatch)
    def refuse(mapper, connection, row):
        if row.tenant_id == operator[0] and row.record_type == "credential.revoked":
            raise OperationalError("private SQL", {"secret": "private parameter"}, RuntimeError("private driver"))
    event.listen(EvidenceRecord, "before_insert", refuse)
    try:
        result = revoker.main(revoker_args(operator, credential) + ["--apply", "--acknowledge-revocation"])
    finally:
        event.remove(EvidenceRecord, "before_insert", refuse)
    assert result == 2 and snapshot(operator[0]) == before
    output = capsys.readouterr()
    assert "OperationalError" in output.err
    assert all(sensitive not in output.out + output.err for sensitive in (
        "private SQL", "private parameter", "private driver", "ola2_"))


def test_corrupt_evidence_blocks_revocation_without_modifying_key(operator):
    revoker = feature("revoker")
    _, credential, _ = issue(operator)
    with SessionLocal() as db:
        tip = db.scalar(select(EvidenceRecord).where(EvidenceRecord.tenant_id == operator[0]))
        db.add(EvidenceRecord(id=str(uuid.uuid4()), tenant_id=operator[0], seq=1,
            record_type="generic", hash_version=2, payload_json="{}",
            prev_hash=tip.record_hash, record_hash="f" * 64))
        db.commit()
    before = snapshot(operator[0])
    with pytest.raises(ValueError, match="chain"):
        revoker.revoke_tenant_credential(operator[0], **revoke_kwargs(operator, credential))
    assert snapshot(operator[0]) == before


@pytest.mark.parametrize("kind,apply", [("issuer", False), ("issuer", True), ("revoker", False), ("revoker", True)])
def test_missing_database_is_not_created(operator, tmp_path, monkeypatch, capsys, kind, apply):
    module = feature(kind)
    base = importlib.import_module("scripts.provision_additional_tenant_key")
    credential = str(uuid.uuid4())
    missing = tmp_path / "not-there.sqlite"
    monkeypatch.setattr(base, "DB_PATH", str(missing))
    terminal(monkeypatch)
    args = issuer_args(operator) if kind == "issuer" else revoker_args(operator, credential)
    if apply:
        args += ["--apply", "--acknowledge-review-result-access" if kind == "issuer" else "--acknowledge-revocation"]
    assert module.main(args) == 2
    assert not missing.exists()
    assert "BLOCKED" in capsys.readouterr().err


@pytest.mark.parametrize("kind,apply", [("issuer", False), ("issuer", True), ("revoker", False), ("revoker", True)])
def test_database_moved_after_check_is_never_recreated(
        operator, tmp_path, monkeypatch, capsys, kind, apply):
    module = feature(kind)
    _, credential, _ = issue(operator) if kind == "revoker" else (None, str(uuid.uuid4()), None)
    base = importlib.import_module("scripts.provision_additional_tenant_key")
    path = tmp_path / "baza # ą %20.sqlite"
    with sqlite3.connect(DB_PATH) as source, sqlite3.connect(path) as target:
        source.backup(target)
    saved = path.with_name("preserved.sqlite")
    original_bytes = path.read_bytes()
    monkeypatch.setattr(base, "DB_PATH", str(path))
    original_is_file = Path.is_file
    def moved_after_positive_check(candidate):
        result = original_is_file(candidate)
        if candidate == path and result:
            path.rename(saved)
        return result
    monkeypatch.setattr(Path, "is_file", moved_after_positive_check)
    terminal(monkeypatch)
    args = issuer_args(operator) if kind == "issuer" else revoker_args(operator, credential)
    if apply:
        args += ["--apply", "--acknowledge-review-result-access" if kind == "issuer" else "--acknowledge-revocation"]
    assert module.main(args) == 2
    assert not path.exists() and saved.read_bytes() == original_bytes
    output = capsys.readouterr()
    assert "OperationalError" in output.err and "ola2_" not in output.out + output.err


def test_issuer_read_only_probe_and_rw_issue_support_special_database_path(operator, tmp_path, monkeypatch):
    issuer = feature()
    base = importlib.import_module("scripts.provision_additional_tenant_key")
    path = tmp_path / "baza # ą %20.sqlite"
    with sqlite3.connect(DB_PATH) as source, sqlite3.connect(path) as target:
        source.backup(target)
    monkeypatch.setattr(base, "DB_PATH", str(path))
    before = path.read_bytes()
    receipt = issuer.inspect_reviewer_credential(operator[0], expected_requester_id=operator[1])
    assert receipt["status"] == "DRY_RUN" and path.read_bytes() == before
    _, credential, raw = issuer.issue_reviewer_credential(operator[0], expected_requester_id=operator[1])
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT tenant_id,key_hash,access_scope,revoked_at FROM api_keys WHERE id=?",
                         (credential,)).fetchone()
    assert row == (operator[0], hash_api_key(raw), "REVIEW_RESULT", None)


def test_failed_issuer_commit_never_prints_secret_or_changes_inventory(operator, monkeypatch, capsys):
    issuer = feature()
    before = snapshot(operator[0])
    terminal(monkeypatch)
    def refuse(mapper, connection, row):
        if row.tenant_id == operator[0]:
            raise OperationalError("private SQL", {"secret": "private parameter"}, RuntimeError("private driver"))
    event.listen(ApiKey, "before_insert", refuse)
    try:
        result = issuer.main(issuer_args(operator) + ["--apply", "--acknowledge-review-result-access"])
    finally:
        event.remove(ApiKey, "before_insert", refuse)
    assert result == 2 and snapshot(operator[0]) == before
    output = capsys.readouterr()
    assert "OperationalError" in output.err
    assert all(sensitive not in output.out + output.err for sensitive in (
        "private SQL", "private parameter", "private driver", "ola2_"))


def test_missing_pepper_blocks_issuance_without_mutation(operator, monkeypatch, capsys):
    issuer = feature()
    before = snapshot(operator[0])
    monkeypatch.delenv("OLA_API_KEY_PEPPER", raising=False)
    terminal(monkeypatch)
    assert issuer.main(issuer_args(operator) + ["--apply", "--acknowledge-review-result-access"]) == 2
    output = capsys.readouterr()
    assert "BLOCKED" in output.err and "ola2_" not in output.out + output.err
    assert snapshot(operator[0]) == before


def test_revoker_can_retire_another_core_key_without_affecting_requester(operator):
    revoker = feature("revoker")
    from scripts.provision_additional_tenant_key import issue_existing_tenant_key
    _, credential, raw = issue_existing_tenant_key(operator[0], expected_requester_id=operator[1])
    receipt = revoker.revoke_tenant_credential(operator[0], credential_id=credential,
        expected_requester_id=operator[1], expected_target_scope="OLA_CORE", expected_active_key_count=2)
    assert receipt["status"] == "REVOKED" and receipt["access_scope"] == "OLA_CORE"
    client = TestClient(app)
    assert client.get("/auth/session", headers={"X-API-Key": raw}).status_code == 401
    assert client.get("/auth/session", headers={"X-API-Key": operator[2]}).status_code == 200

