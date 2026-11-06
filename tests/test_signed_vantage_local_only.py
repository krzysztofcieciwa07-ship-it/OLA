"""Signed safe-expression pilot must never invoke external models/tools.

The Vantage Ed25519 check occurs before this test's runtime seam; the
external service is mocked only to test the *post-approval* execution scope.
Real two-container signature tests are in separate GitHub Actions.
"""
import uuid

from fastapi.testclient import TestClient

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.models import ApiKey, Tenant
import app.main as main_module
import app.agent_runtime as runtime


def test_signed_safe_expression_does_not_invoke_llm_even_with_provider_key(monkeypatch):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "a" * 40)
    monkeypatch.setenv("OLA_LLM_MODE", "required")
    monkeypatch.setenv("OLA_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-only-not-real")
    monkeypatch.setenv("OLA_VANTAGE_ENFORCED", "1")
    tenant = str(uuid.uuid4())
    api_key = "signed-only-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=tenant, name="synthetic safe-expression-only"))
        db.flush()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant,
                      key_hash=api_key_fingerprint(api_key)))
        db.commit()

    def remote_llm_forbidden(*_args, **_kwargs):
        raise AssertionError("signed safe_expression must not contact remote LLM")

    def fake_boundary(*, tenant_id, operation_id, action, task_text):
        assert tenant_id == tenant and action == "safe_expression"
        return {"receipt": {"verdict": "ALLOW", "operation_id": operation_id},
                "signature": "test-double-only; real signatures tested separately"}

    monkeypatch.setattr(runtime, "_invoke_llm", remote_llm_forbidden)
    monkeypatch.setattr(main_module, "request_verified_vantage_decision", fake_boundary)

    response = TestClient(main_module.app).post(
        "/operator/guarded-run",
        headers={"X-API-Key": api_key},
        json={"task": "Calculate 17 * 23 and return verified result.",
              "requested_tools": ["safe_expression"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "REVIEW"
    assert body["vantage"]["status"] == "SIGNED_RECEIPT_VERIFIED"
    assert body["nina"]["llm_invocations"] == 6
    assert body["nina"]["invocation_type"] == "local_deterministic_model"
    assert body["production_authorized"] is False
