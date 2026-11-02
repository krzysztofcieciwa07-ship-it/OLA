"""Core writes must recheck request authority after reserving SQLite's writer.

These are real HTTP/SQLite tests. A hook changes authority after successful
authentication to make the otherwise narrow race deterministic.
"""
import concurrent.futures
import contextvars
import importlib
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api_key_crypto import hash_api_key
from app.database import SessionLocal
from app.models import ApiKey, EvidenceRecord, Tenant


main = importlib.import_module("app.main")


def seed():
    tenant, credential, foreign = (str(uuid.uuid4()) for _ in range(3))
    raw = "core-race-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add_all([Tenant(id=tenant, name="core-race"), Tenant(id=foreign, name="foreign")])
        db.flush()
        db.add(ApiKey(id=credential, tenant_id=tenant, key_hash=hash_api_key(raw)))
        db.commit()
    return tenant, credential, raw, foreign


def records(tenant):
    with SessionLocal() as db:
        return db.scalars(select(EvidenceRecord).where(EvidenceRecord.tenant_id == tenant)).all()


def change_authority(credential, mutation, foreign):
    with SessionLocal() as db:
        key = db.get(ApiKey, credential)
        if mutation == "revoked":
            key.revoked_at = 123
        elif mutation == "scope":
            key.access_scope = "REVIEW_RESULT"
        elif mutation == "rotated":
            key.key_hash = hash_api_key("replacement-" + uuid.uuid4().hex)
        elif mutation == "tenant":
            key.tenant_id = foreign
        else:
            raise AssertionError("unknown fixture mutation")
        db.commit()


@pytest.mark.parametrize("endpoint,body", [
    ("/evidence", {"record_type": "user.race", "payload": {"note": "must not persist"}}),
    ("/audit", {"task": "controlled recovery", "scenario": "fault_then_recovery"}),
    ("/nina-run", {"task": "Calculate 17 * 23", "requested_tools": ["safe_expression"]}),
])
@pytest.mark.parametrize("mutation", ["revoked", "scope", "rotated", "tenant"])
def test_changed_core_authority_after_authentication_blocks_before_write_and_nina_executor(
        monkeypatch, local_binding_source, endpoint, body, mutation):
    tenant, credential, raw, foreign = seed()
    authenticate = main.identity_from_key
    calls = []

    def authenticated_then_changed(candidate):
        identity = authenticate(candidate)
        change_authority(credential, mutation, foreign)
        return identity

    def forbidden_executor(*args, **kwargs):
        calls.append("executor")
        raise AssertionError("NINA executor must not begin with changed Core authority")

    monkeypatch.setattr(main, "identity_from_key", authenticated_then_changed)
    monkeypatch.setattr(main.NinaOrchestrator, "execute", forbidden_executor)
    response = TestClient(main.app, raise_server_exceptions=False).post(
        endpoint, headers={"X-API-Key": raw}, json=body,
    )
    expected = 403 if mutation == "scope" else 401
    assert response.status_code == expected, response.text
    assert records(tenant) == []
    assert records(foreign) == []
    assert calls == []
    assert raw not in response.text


def test_parallel_core_requests_keep_tenant_authority_isolated(monkeypatch):
    accounts = [seed(), seed()]
    authenticate = main.identity_from_key
    arrival = threading.Barrier(2)

    def authenticated_together(candidate):
        identity = authenticate(candidate)
        arrival.wait(timeout=10)
        return identity

    monkeypatch.setattr(main, "identity_from_key", authenticated_together)

    def post(account):
        tenant, _, raw, _ = account
        response = TestClient(main.app).post(
            "/evidence", headers={"X-API-Key": raw},
            json={"record_type": "user.parallel", "payload": {"tenant_marker": tenant}},
        )
        assert response.status_code == 200, response.text
        assert response.json()["tenant_id"] == tenant
        return response

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(post, accounts))
    assert [len(records(account[0])) for account in accounts] == [1, 1]


def test_core_authority_does_not_leak_to_later_unauthenticated_requests_or_internal_appends():
    tenant, _, raw, foreign = seed()
    client = TestClient(main.app)
    assert client.post("/evidence", headers={"X-API-Key": raw}, json={"payload": {}}).status_code == 200
    assert client.post("/evidence", json={"payload": {}}).status_code == 401
    assert client.get("/health").json() == {"status": "ok"}
    # Signed payment/webhook processing has its own authorization boundary;
    # this generic internal append must not inherit a prior Core request.
    internal = main.append_record(foreign, "internal.fixture", {"kind": "direct-call"})
    assert internal["tenant_id"] == foreign
    assert len(records(tenant)) == len(records(foreign)) == 1


def test_copied_request_context_cannot_authorize_a_write_after_response(monkeypatch):
    tenant, _, raw, _ = seed()
    authenticate = main.identity_from_key
    captured = []

    def capture_authenticated_context(candidate):
        identity = authenticate(candidate)
        captured.append(contextvars.copy_context())
        return identity

    monkeypatch.setattr(main, "identity_from_key", capture_authenticated_context)
    response = TestClient(main.app).post(
        "/evidence", headers={"X-API-Key": raw}, json={"payload": {}},
    )
    assert response.status_code == 200
    assert len(captured) == 1
    with pytest.raises(main.HTTPException) as denied:
        captured[0].run(main.append_record, tenant, "user.late", {"must": "not persist"})
    assert denied.value.status_code == 401
    assert len(records(tenant)) == 1


def test_nested_http_request_restores_outer_tenant_authority(monkeypatch):
    outer, inner = seed(), seed()
    authenticate = main.identity_from_key

    def nested_authenticated(candidate):
        identity = authenticate(candidate)
        if candidate == outer[2]:
            nested = TestClient(main.app).post(
                "/evidence", headers={"X-API-Key": inner[2]}, json={"payload": {}},
            )
            assert nested.status_code == 200
            assert nested.json()["tenant_id"] == inner[0]
        return identity

    monkeypatch.setattr(main, "identity_from_key", nested_authenticated)
    response = TestClient(main.app).post(
        "/evidence", headers={"X-API-Key": outer[2]}, json={"payload": {}},
    )
    assert response.status_code == 200
    assert response.json()["tenant_id"] == outer[0]
    assert len(records(outer[0])) == len(records(inner[0])) == 1


def test_system_payment_evidence_uses_its_own_authority_after_core_request(monkeypatch):
    tenant, _, raw, foreign = seed()
    client = TestClient(main.app)
    assert client.post("/evidence", headers={"X-API-Key": raw}, json={"payload": {}}).status_code == 200
    monkeypatch.setattr(main, "retrieve_checkout", lambda _: {
        "metadata": {"tenant_id": foreign}, "payment_status": "unpaid", "status": "open",
    })
    response = client.get("/payment-success", params={"session_id": "disposable-unpaid-checkout"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "BLOCK"
    assert len(records(tenant)) == 1
    assert [record.record_type for record in records(foreign)] == ["revenue.payment_blocked"]

