"""Regression tests for the legacy /nina-run human approval boundary."""

import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.main import app
from app.models import ApiKey, Tenant


def _create_run(monkeypatch):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "test-bound-commit")
    tenant_id = str(uuid.uuid4())
    keys = [f"human-gate-{uuid.uuid4().hex}" for _ in range(2)]
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="nina-run-human-gate"))
        for key in keys:
            db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant_id,
                          key_hash=api_key_fingerprint(key)))
        db.commit()
    client = TestClient(app)
    response = client.post("/nina-run", headers={"X-API-Key": keys[0]}, json={
        "task": "Calculate 17 * 23 and return the verified result.",
        "requested_tools": ["safe_expression"],
    })
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "REVIEW", run
    return client, keys, run


def _approve(client, key, run, *, tip=None, digest=None,
             reason="Reviewed independent evidence"):
    return client.post(f"/nina-run/{run['run_id']}/approve",
                       headers={"Authorization": f"Bearer {key}"},
                       json={"tip_hash": tip or run["tip_hash"],
                             "report_sha256": digest or run["decision_report"]["report_sha256"],
                             "reason": reason})


def test_independent_human_can_review_candidate_exactly_once(monkeypatch):
    client, keys, run = _create_run(monkeypatch)
    assert _approve(client, keys[0], run).status_code == 403

    approved = _approve(client, keys[1], run)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED_FOR_REVIEW_ONLY"
    assert approved.json()["production_authorized"] is False

    repeated = _approve(client, keys[1], run, tip=approved.json()["tip_hash"])
    assert repeated.status_code == 409, repeated.text


def test_rejects_empty_reason_even_for_eligible_candidate(monkeypatch):
    client, keys, run = _create_run(monkeypatch)
    refused = _approve(client, keys[1], run, reason="  ")
    assert refused.status_code == 400, refused.text


def test_rejects_unbound_report_and_stale_tip(monkeypatch):
    client, keys, run = _create_run(monkeypatch)
    assert _approve(client, keys[1], run, digest="unrelated-report").status_code == 409
    assert _approve(client, keys[1], run, tip="0" * 64).status_code == 409
    assert _approve(client, keys[1], run).status_code == 200


def test_concurrent_approvals_commit_only_one_record(monkeypatch):
    _, keys, run = _create_run(monkeypatch)

    def submit(_):
        return _approve(TestClient(app), keys[1], run).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, range(2)))
    assert sorted(results) == [200, 409], results
