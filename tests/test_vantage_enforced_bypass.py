"""Do not allow legacy execution routes to bypass enforced external Vantage.

A signed safe_expression approval cannot authorize unrelated low-risk agents,
arbitrary workflows, invoice effects, chats, checkout or synthetic audit writes.
Webhook intake/evidence readback is a separate scoped boundary.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.models import ApiKey, Tenant
from app.nina import NinaDecision
import app.main as main


@pytest.fixture
def operator(monkeypatch):
    monkeypatch.setenv("OLA_VANTAGE_ENFORCED", "1")
    monkeypatch.setenv("OLA_PARALLEL_WORKFLOWS_ENABLED", "1")
    tenant, key = str(uuid.uuid4()), "enforce-test-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=tenant, name="synthetic enforce bypass test"))
        db.flush()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant,
                      key_hash=api_key_fingerprint(key)))
        db.commit()
    # No actual tool/network execution, but a route not protected by the
    # top-level gate will return a non-403 result and FAIL the assertion.
    monkeypatch.setattr(main, "chat", lambda *_: {"status": "UNGUARDED"})
    monkeypatch.setattr(main, "create_checkout", lambda *_: {"id": "test-only"})
    monkeypatch.setattr(main, "run_controlled_audit", lambda *_: {"status": "UNGUARDED"})
    monkeypatch.setattr(main, "run_agent_task", lambda *_: {"status": "UNGUARDED"})
    monkeypatch.setattr(main, "run_invoice_task", lambda *_: {"status": "UNGUARDED"})
    monkeypatch.setattr(main.NinaOrchestrator, "plan",
                        lambda *_: NinaDecision(status="BLOCK", reason="stub", allowed_tools=()))
    return TestClient(main.app), key


@pytest.mark.parametrize(("path", "body"), [
    ("/chat", {"messages": [{"role": "user", "content": "hello"}]}),
    ("/checkout", {"task": "test checkout, no real payment"}),
    ("/audit", {"task": "controlled fault"}),
    ("/agent-run", {"task": "Calculate 17 * 23", "agent_id": "agent-001", "risk": "LOW"}),
    ("/nina-workflow", {"task": "test", "requested_tools": ["safe_expression"]}),
    ("/business-invoice-run", {"invoice": {"customer": "synthetic"}}),
])
def test_enforced_vantage_denies_legacy_effect_surfaces_before_execution(operator, path, body):
    client, key = operator
    response = client.post(path, headers={"X-API-Key": key}, json=body)
    assert response.status_code == 403, (path, response.status_code)
    assert response.json().get("detail") == "signed Vantage guarded execution required"
