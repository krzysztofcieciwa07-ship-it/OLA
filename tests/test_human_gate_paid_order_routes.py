"""OIDC_REQUIRED paid-order routes must not fall back to API-key operators."""
import uuid

from fastapi.testclient import TestClient

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.human_identity.policy import set_tenant_human_gate_mode
from app.main import app
from app.models import (
    ApiKey,
    CheckoutOrder,
    CheckoutOrderControl,
    Tenant,
)


def _oidc_tenant_with_order():
    tenant_id = str(uuid.uuid4())
    order_id = str(uuid.uuid4())
    raw_key = f"valid-machine-key-{uuid.uuid4()}"
    key_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="oidc-paid-order-gate"))
        db.commit()
        db.add(ApiKey(
            id=key_id,
            tenant_id=tenant_id,
            key_hash=api_key_fingerprint(raw_key),
            role="tenant",
        ))
        db.add(CheckoutOrder(
            id=order_id,
            tenant_id=tenant_id,
            idempotency_key_hash="b" * 64,
            request_hash="c" * 64,
            task="protected test task",
            status="PAID_PENDING_REVIEW",
            payment_result_json="{}",
        ))
        db.add(CheckoutOrderControl(
            id=str(uuid.uuid4()),
            order_id=order_id,
            tenant_id=tenant_id,
            requester_id=key_id,
            requester_person_ref=None,
            status="PAID_PENDING_REVIEW",
        ))
        db.commit()
    set_tenant_human_gate_mode(
        tenant_id=tenant_id,
        actor_ref="bootstrap-principal-owner",
        reason="Enable OIDC-only paid-order routes in test",
        target_mode="OIDC_REQUIRED",
    )
    return tenant_id, order_id, raw_key


def test_api_key_cannot_approve_or_review_oidc_required_order():
    _tenant_id, order_id, raw_key = _oidc_tenant_with_order()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {raw_key}"}
    payload = {
        "tip_hash": "0" * 64,
        "report_sha256": "1" * 64,
        "reason": "API key must not represent a human operator",
    }

    approve = client.post(
        f"/checkout-orders/{order_id}/approve",
        headers=headers,
        json=payload,
    )
    assert approve.status_code == 401
    assert approve.json()["detail"] == "authenticated Human Identity session is required"

    review = client.post(
        f"/checkout-orders/{order_id}/review-report",
        headers=headers,
        json=payload,
    )
    assert review.status_code == 401
    assert review.json()["detail"] == "authenticated Human Identity session is required"


def test_oidc_required_order_disables_legacy_json_report_retrieval():
    _tenant_id, order_id, raw_key = _oidc_tenant_with_order()
    client = TestClient(app)
    response = client.get(
        f"/checkout-orders/{order_id}/report",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 409
    assert "signed customer bundle" in response.json()["detail"]


def test_oidc_required_checkout_rejects_api_key_without_hr_owner():
    tenant_id, _order_id, raw_key = _oidc_tenant_with_order()
    response = TestClient(app).post(
        "/checkout",
        headers={
            "X-API-Key": raw_key,
            "Idempotency-Key": f"oidc-checkout-{uuid.uuid4()}",
        },
        json={"task": "a paid customer task"},
    )
    assert response.status_code == 403
    assert "HR-backed owner" in response.json()["detail"]


def _legacy_tenant_with_order():
    """Create a pre-OIDC tenant so public-origin enforcement is exercised."""
    tenant_id = str(uuid.uuid4())
    order_id = str(uuid.uuid4())
    raw_key = f"legacy-human-gate-key-{uuid.uuid4()}"
    key_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="public-https-no-downgrade"))
        db.flush()
        db.add(ApiKey(
            id=key_id,
            tenant_id=tenant_id,
            key_hash=api_key_fingerprint(raw_key),
            role="tenant",
        ))
        db.add(CheckoutOrder(
            id=order_id,
            tenant_id=tenant_id,
            idempotency_key_hash="f" * 64,
            request_hash="e" * 64,
            task="legacy order must be blocked on public HTTPS",
            status="PAID_PENDING_REVIEW",
            payment_result_json="{}",
        ))
        db.add(CheckoutOrderControl(
            id=str(uuid.uuid4()),
            order_id=order_id,
            tenant_id=tenant_id,
            requester_id=key_id,
            requester_person_ref=None,
            status="PAID_PENDING_REVIEW",
        ))
        db.commit()
    return tenant_id, order_id, raw_key


def test_public_https_forces_production_even_when_profile_env_says_sandbox(monkeypatch):
    _tenant_id, order_id, raw_key = _legacy_tenant_with_order()
    monkeypatch.setenv("OLA_PUBLIC_BASE_URL", "https://ola.example")
    monkeypatch.setenv("OLA_DEPLOYMENT_PROFILE", "sandbox")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {raw_key}"}
    payload = {
        "tip_hash": "0" * 64,
        "report_sha256": "1" * 64,
        "reason": "public HTTPS must never fall back to a legacy API-key operator",
    }

    approve = client.post(
        f"/checkout-orders/{order_id}/approve",
        headers=headers,
        json=payload,
    )
    assert approve.status_code == 403
    assert "production Human Gate requires persistent OIDC_REQUIRED policy" in approve.json()["detail"]

    retrieve = client.get(f"/checkout-orders/{order_id}/report", headers=headers)
    assert retrieve.status_code == 403
    assert "production Human Gate requires persistent OIDC_REQUIRED policy" in retrieve.json()["detail"]
