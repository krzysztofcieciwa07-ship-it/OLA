"""Behavioral contract for separate customer bundle, grant and delivery-attempt lifecycles."""
import importlib
import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    CheckoutOrder,
    HumanMembershipRole,
    HumanPrincipal,
    Tenant,
    TenantIdentityPolicy,
)


def _delivery_api():
    module = importlib.import_module("app.customer_bundle.delivery")
    required = (
        "request_recipient_grant",
        "approve_recipient_grant",
        "revoke_recipient_grant",
        "begin_delivery_attempt",
        "complete_delivery_attempt",
        "acknowledge_delivery_attempt",
        "assert_delivery_attempt_authorized",
    )
    missing = [name for name in required if not callable(getattr(module, name, None))]
    assert not missing, f"customer delivery lifecycle functions are missing: {missing}"
    return module


def _identity_fixture():
    tenant_id = str(uuid.uuid4())
    requester_id, approver_id, recipient_id = (str(uuid.uuid4()) for _ in range(3))
    order_id = str(uuid.uuid4())
    people = {
        requester_id: "person-ref-admin-requester",
        approver_id: "person-ref-admin-approver",
        recipient_id: "person-ref-customer-recipient",
    }
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="bundle-delivery-lifecycle-test"))
        db.flush()
        db.add(TenantIdentityPolicy(
            tenant_id=tenant_id,
            human_gate_mode="OIDC_REQUIRED",
            changed_by_ref="principal-ref-bootstrap",
            reason="delivery lifecycle contract test",
        ))
        db.add(CheckoutOrder(
            id=order_id,
            tenant_id=tenant_id,
            idempotency_key_hash="d" * 64,
            request_hash="e" * 64,
            task="approved customer report",
            status="REPORT_APPROVED",
        ))
        for principal_id, person_ref in people.items():
            db.add(HumanPrincipal(
                id=principal_id,
                tenant_id=tenant_id,
                issuer="https://idp.example",
                subject=f"subject-{principal_id}",
                status="ACTIVE",
                person_ref=person_ref,
                person_key_source="HR_SCIM",
            ))
        for principal_id, role in (
            (requester_id, "tenant_identity_admin"),
            (approver_id, "tenant_identity_admin"),
            (recipient_id, "recipient"),
        ):
            db.add(HumanMembershipRole(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                principal_id=principal_id,
                role=role,
                status="ACTIVE",
                created_by_ref="principal-ref-bootstrap",
            ))
        db.commit()
    return tenant_id, order_id, requester_id, approver_id, recipient_id, people


def _signed_bundle(tenant_id, order_id):
    from app.models import CustomerEvidenceBundle

    bundle_id = str(uuid.uuid4())
    bundle = CustomerEvidenceBundle(
        id=bundle_id,
        tenant_id=tenant_id,
        order_id=order_id,
        version=1,
        status="SIGNED",
        profile="CUSTOMER_BUNDLE_SANDBOX_V1",
        manifest_sha256="a" * 64,
        report_sha256="b" * 64,
        igor_key_id="igor-key-1",
        ola_key_id="ola-key-1",
        storage_object_ref=f"opaque-encrypted-object-{bundle_id}",
        approved_at=1_800_000_000,
        approved_tip_hash="c" * 64,
        signed_at=1_800_000_010,
        signing_tip_hash="d" * 64,
        created_at=1_800_000_000,
        expires_at=1_900_000_000,
    )
    with SessionLocal() as db:
        db.add(bundle)
        db.commit()
    return bundle_id


def test_delivery_lifecycle_has_distinct_persistent_bundle_grant_and_attempt_models():
    from app import models

    required = (
        "CustomerEvidenceBundle",
        "CustomerBundleRecipientGrant",
        "CustomerBundleDeliveryAttempt",
    )
    missing = [name for name in required if not hasattr(models, name)]
    assert not missing, f"customer delivery lifecycle models are missing: {missing}"

    assert {"status", "manifest_sha256", "storage_object_ref"} <= set(
        models.CustomerEvidenceBundle.__table__.columns.keys()
    )
    assert {"status", "recipient_principal_id", "recipient_person_ref"} <= set(
        models.CustomerBundleRecipientGrant.__table__.columns.keys()
    )
    assert {
        "status", "attempt_no", "bundle_id", "grant_id",
        "acknowledged_at", "acknowledgement_evidence_id",
    } <= set(models.CustomerBundleDeliveryAttempt.__table__.columns.keys())


def test_recipient_grant_requires_dual_control_from_distinct_hr_people():
    delivery = _delivery_api()
    tenant_id, order_id, requester_id, approver_id, recipient_id, people = _identity_fixture()

    request = delivery.request_recipient_grant(
        tenant_id=tenant_id,
        order_id=order_id,
        requester_principal_id=requester_id,
        requester_person_ref=people[requester_id],
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        reason="Grant access to the approved order report",
        expires_at=1_900_000_000,
    )
    assert request["status"] == "PENDING"

    with pytest.raises(delivery.CustomerBundleDeliveryRejected) as self_approval:
        delivery.approve_recipient_grant(
            tenant_id=tenant_id,
            order_id=order_id,
            grant_id=request["grant_id"],
            approver_principal_id=requester_id,
            approver_person_ref=people[requester_id],
            reason="same person must not approve the grant",
        )
    assert self_approval.value.code == 403

    approved = delivery.approve_recipient_grant(
        tenant_id=tenant_id,
        order_id=order_id,
        grant_id=request["grant_id"],
        approver_principal_id=approver_id,
        approver_person_ref=people[approver_id],
        reason="Second administrator approved the recipient scope",
    )
    assert approved["status"] == "ACTIVE"
    assert approved["grant_id"] == request["grant_id"]


def test_each_download_is_a_new_attempt_and_does_not_mutate_bundle_or_grant():
    delivery = _delivery_api()
    tenant_id, order_id, requester_id, approver_id, recipient_id, people = _identity_fixture()
    bundle_id = _signed_bundle(tenant_id, order_id)
    request = delivery.request_recipient_grant(
        tenant_id=tenant_id,
        order_id=order_id,
        requester_principal_id=requester_id,
        requester_person_ref=people[requester_id],
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        reason="Grant recipient access",
        expires_at=1_900_000_000,
    )
    delivery.approve_recipient_grant(
        tenant_id=tenant_id,
        order_id=order_id,
        grant_id=request["grant_id"],
        approver_principal_id=approver_id,
        approver_person_ref=people[approver_id],
        reason="Approve recipient access",
    )

    first = delivery.begin_delivery_attempt(
        tenant_id=tenant_id,
        order_id=order_id,
        bundle_id=bundle_id,
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        now=1_800_000_100,
    )
    second = delivery.begin_delivery_attempt(
        tenant_id=tenant_id,
        order_id=order_id,
        bundle_id=bundle_id,
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        now=1_800_000_200,
    )
    assert first["status"] == "STARTED"
    assert second["status"] == "STARTED"
    assert first["attempt_no"] == 1
    assert second["attempt_no"] == 2
    assert first["attempt_id"] != second["attempt_id"]

    completed = delivery.complete_delivery_attempt(
        tenant_id=tenant_id,
        attempt_id=first["attempt_id"],
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        now=1_800_000_150,
    )
    assert completed["status"] == "COMPLETED"

    from app.models import (
        CustomerBundleDeliveryAttempt,
        CustomerBundleRecipientGrant,
        CustomerEvidenceBundle,
    )
    with SessionLocal() as db:
        bundle = db.get(CustomerEvidenceBundle, bundle_id)
        grant = db.get(CustomerBundleRecipientGrant, request["grant_id"])
        attempts = db.scalars(
            select(CustomerBundleDeliveryAttempt)
            .where(CustomerBundleDeliveryAttempt.bundle_id == bundle_id)
            .order_by(CustomerBundleDeliveryAttempt.attempt_no.asc())
        ).all()
        assert bundle.status == "SIGNED"
        assert grant.status == "ACTIVE"
        assert [item.status for item in attempts] == ["COMPLETED", "STARTED"]
        assert [item.attempt_no for item in attempts] == [1, 2]


def test_revoked_grant_creates_blocked_attempt_without_changing_bundle_state():
    delivery = _delivery_api()
    tenant_id, order_id, requester_id, approver_id, recipient_id, people = _identity_fixture()
    bundle_id = _signed_bundle(tenant_id, order_id)
    request = delivery.request_recipient_grant(
        tenant_id=tenant_id,
        order_id=order_id,
        requester_principal_id=requester_id,
        requester_person_ref=people[requester_id],
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        reason="Grant recipient access",
        expires_at=1_900_000_000,
    )
    delivery.approve_recipient_grant(
        tenant_id=tenant_id,
        order_id=order_id,
        grant_id=request["grant_id"],
        approver_principal_id=approver_id,
        approver_person_ref=people[approver_id],
        reason="Approve recipient access",
    )
    revoked = delivery.revoke_recipient_grant(
        tenant_id=tenant_id,
        order_id=order_id,
        grant_id=request["grant_id"],
        actor_principal_id=approver_id,
        actor_person_ref=people[approver_id],
        reason="Recipient access revoked",
    )
    assert revoked["status"] == "REVOKED"

    blocked = delivery.begin_delivery_attempt(
        tenant_id=tenant_id,
        order_id=order_id,
        bundle_id=bundle_id,
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        now=1_800_000_300,
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["reason"] == "RECIPIENT_GRANT_INACTIVE"

    from app.models import CustomerEvidenceBundle, CustomerBundleDeliveryAttempt
    with SessionLocal() as db:
        bundle = db.get(CustomerEvidenceBundle, bundle_id)
        attempt = db.get(CustomerBundleDeliveryAttempt, blocked["attempt_id"])
        assert bundle.status == "SIGNED"
        assert attempt.status == "BLOCKED"


def test_customer_bundle_routes_require_human_identity_not_api_key():
    from fastapi.testclient import TestClient

    from app.main import app

    required_paths = {
        "/checkout-orders/{order_id}/bundle-grants",
        "/checkout-orders/{order_id}/bundle-grants/{grant_id}/approve",
        "/checkout-orders/{order_id}/bundle-grants/{grant_id}/revoke",
        "/checkout-orders/{order_id}/bundles",
        "/checkout-orders/{order_id}/bundles/{bundle_id}/download",
        "/checkout-orders/{order_id}/bundles/{bundle_id}/attempts/{attempt_id}/acknowledge",
    }
    mounted_paths = {route.path for route in app.routes}
    assert required_paths <= mounted_paths

    client = TestClient(app)
    headers = {"X-API-Key": "not-a-human-session", "Origin": "http://localhost:8000"}
    create_bundle = client.post(
        "/checkout-orders/order-route-test/bundles",
        headers=headers,
    )
    assert create_bundle.status_code == 401

    grant = client.post(
        "/checkout-orders/order-route-test/bundle-grants",
        headers=headers,
        json={
            "recipient_principal_id": "recipient-principal",
            "recipient_person_ref": "person-ref-recipient",
            "reason": "grant report access",
            "expires_at": 1_900_000_000,
        },
    )
    assert grant.status_code == 401

    download = client.get(
        "/checkout-orders/order-route-test/bundles/bundle-route-test/download",
        headers=headers,
    )
    assert download.status_code == 401


def test_recipient_acknowledgement_is_separate_from_transfer_completion():
    delivery = _delivery_api()
    tenant_id, order_id, requester_id, approver_id, recipient_id, people = _identity_fixture()
    bundle_id = _signed_bundle(tenant_id, order_id)
    grant = delivery.request_recipient_grant(
        tenant_id=tenant_id,
        order_id=order_id,
        requester_principal_id=requester_id,
        requester_person_ref=people[requester_id],
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        reason="Grant access for acknowledgement contract",
        expires_at=1_900_000_000,
    )
    delivery.approve_recipient_grant(
        tenant_id=tenant_id,
        order_id=order_id,
        grant_id=grant["grant_id"],
        approver_principal_id=approver_id,
        approver_person_ref=people[approver_id],
        reason="Second administrator approves recipient",
    )
    attempt = delivery.begin_delivery_attempt(
        tenant_id=tenant_id,
        order_id=order_id,
        bundle_id=bundle_id,
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        now=1_800_000_100,
    )
    completed = delivery.complete_delivery_attempt(
        tenant_id=tenant_id,
        attempt_id=attempt["attempt_id"],
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        now=1_800_000_150,
    )
    assert completed["status"] == "COMPLETED"

    from app.models import CustomerBundleDeliveryAttempt
    with SessionLocal() as db:
        row = db.get(CustomerBundleDeliveryAttempt, attempt["attempt_id"])
        assert row.status == "COMPLETED"
        assert row.acknowledged_at is None
        assert row.acknowledgement_evidence_id is None

    acknowledged = delivery.acknowledge_delivery_attempt(
        tenant_id=tenant_id,
        order_id=order_id,
        bundle_id=bundle_id,
        attempt_id=attempt["attempt_id"],
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        now=1_800_000_200,
    )
    assert acknowledged["status"] == "ACKNOWLEDGED"

    with SessionLocal() as db:
        row = db.get(CustomerBundleDeliveryAttempt, attempt["attempt_id"])
        assert row.status == "COMPLETED"
        assert row.acknowledged_at == 1_800_000_200
        assert row.acknowledgement_evidence_id == acknowledged["acknowledgement_evidence_id"]

    with pytest.raises(delivery.CustomerBundleDeliveryRejected) as duplicate:
        delivery.acknowledge_delivery_attempt(
            tenant_id=tenant_id,
            order_id=order_id,
            bundle_id=bundle_id,
            attempt_id=attempt["attempt_id"],
            recipient_principal_id=recipient_id,
            recipient_person_ref=people[recipient_id],
            now=1_800_000_201,
        )
    assert duplicate.value.code == 409


def test_recipient_acknowledgement_route_requires_oidc_recipient_session():
    from fastapi.testclient import TestClient
    from app.main import app

    path = "/checkout-orders/{order_id}/bundles/{bundle_id}/attempts/{attempt_id}/acknowledge"
    assert path in {route.path for route in app.routes}
    response = TestClient(app).post(
        "/checkout-orders/order-1/bundles/bundle-1/attempts/attempt-1/acknowledge",
        headers={"X-API-Key": "api-key-is-not-a-human-recipient", "Origin": "http://localhost:8000"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "authenticated Human Identity session is required"



def test_revoking_grant_invalidates_an_already_started_transfer():
    delivery = _delivery_api()
    tenant_id, order_id, requester_id, approver_id, recipient_id, people = _identity_fixture()
    bundle_id = _signed_bundle(tenant_id, order_id)

    grant = delivery.request_recipient_grant(
        tenant_id=tenant_id,
        order_id=order_id,
        requester_principal_id=requester_id,
        requester_person_ref=people[requester_id],
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        reason="Grant access for in-flight revocation test",
        expires_at=1_900_000_000,
    )
    delivery.approve_recipient_grant(
        tenant_id=tenant_id,
        order_id=order_id,
        grant_id=grant["grant_id"],
        approver_principal_id=approver_id,
        approver_person_ref=people[approver_id],
        reason="Approve access for in-flight revocation test",
    )
    attempt = delivery.begin_delivery_attempt(
        tenant_id=tenant_id,
        order_id=order_id,
        bundle_id=bundle_id,
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        now=1_800_000_100,
    )
    assert attempt["status"] == "STARTED"
    assert delivery.assert_delivery_attempt_authorized(
        tenant_id=tenant_id,
        attempt_id=attempt["attempt_id"],
        recipient_principal_id=recipient_id,
        recipient_person_ref=people[recipient_id],
        now=1_800_000_150,
    )["status"] == "AUTHORIZED"

    revoked = delivery.revoke_recipient_grant(
        tenant_id=tenant_id,
        order_id=order_id,
        grant_id=grant["grant_id"],
        actor_principal_id=approver_id,
        actor_person_ref=people[approver_id],
        reason="Revoke access while transfer is in flight",
        now=1_800_000_200,
    )
    assert revoked["status"] == "REVOKED"

    with pytest.raises(delivery.CustomerBundleDeliveryRejected) as blocked:
        delivery.assert_delivery_attempt_authorized(
            tenant_id=tenant_id,
            attempt_id=attempt["attempt_id"],
            recipient_principal_id=recipient_id,
            recipient_person_ref=people[recipient_id],
            now=1_800_000_201,
        )
    assert blocked.value.code == 403


def test_production_download_fails_closed_without_provenance_verifier(monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.customer_bundle import routes

    actor = SimpleNamespace(
        tenant_id="tenant-production-download",
        principal_id="recipient-principal",
        person_ref="recipient-person-ref",
    )
    runtime = SimpleNamespace(
        storage=SimpleNamespace(get=lambda _object_ref: b""),
        trusted_keys={},
        revoked_key_ids=frozenset(),
        profile="CUSTOMER_BUNDLE_PRODUCTION_V1",
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(customer_bundle_runtime=runtime),
        ),
    )
    monkeypatch.setattr(routes, "_recipient", lambda _request: actor)
    monkeypatch.setattr(routes, "_deployment_profile", lambda: "production")

    with pytest.raises(HTTPException) as blocked:
        routes.download_customer_bundle("order-1", "bundle-1", request)

    assert blocked.value.status_code == 503
