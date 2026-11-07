"""Human Identity endpoints for order-scoped recipient grants and signed bundle downloads."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.customer_bundle.service import (
    CustomerBundleCreationRejected,
    create_customer_bundle_for_order,
)
from app.customer_bundle.delivery import (
    CustomerBundleDeliveryRejected,
    acknowledge_delivery_attempt,
    approve_recipient_grant,
    begin_delivery_attempt,
    complete_delivery_attempt,
    fail_delivery_attempt,
    request_recipient_grant,
    revoke_recipient_grant,
)
from app.customer_bundle.storage import (
    CustomerBundleStorageRejected,
    customer_bundle_storage_from_environment,
)
from app.database import SessionLocal
from app.human_identity.membership import HumanMembershipRejected, require_human_operator
from app.human_identity.routes import _deployment_profile, verify_human_csrf
from app.models import CustomerEvidenceBundle


router = APIRouter()


def _actor(request: Request, role: str):
    try:
        return require_human_operator(request, required_role=role)
    except HumanMembershipRejected as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc)) from exc


def _csrf(request: Request, token: str | None) -> None:
    verify_human_csrf(request, token)


def _delivery_error(exc: CustomerBundleDeliveryRejected):
    raise HTTPException(status_code=exc.code, detail=str(exc)) from exc


@router.post("/checkout-orders/{order_id}/bundles")
def create_customer_evidence_bundle(
    order_id: str,
    request: Request,
    x_ola_csrf: str | None = Header(default=None),
):
    """Create a signed, order-scoped bundle from an independently approved report."""
    actor = _actor(request, "report_reviewer")
    _csrf(request, x_ola_csrf)
    runtime = getattr(request.app.state, "customer_bundle_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=503,
            detail="customer bundle signing, verification, timestamp and storage services are not configured",
        )
    try:
        return create_customer_bundle_for_order(
            tenant_id=actor.tenant_id,
            order_id=order_id,
            reviewer_principal_id=actor.principal_id,
            reviewer_person_ref=actor.person_ref,
            runtime=runtime,
        )
    except CustomerBundleCreationRejected as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc)) from exc


@router.post("/checkout-orders/{order_id}/bundle-grants")
def create_customer_bundle_grant(
    order_id: str,
    body: dict,
    request: Request,
    x_ola_csrf: str | None = Header(default=None),
):
    actor = _actor(request, "tenant_identity_admin")
    _csrf(request, x_ola_csrf)
    try:
        return request_recipient_grant(
            tenant_id=actor.tenant_id,
            order_id=order_id,
            requester_principal_id=actor.principal_id,
            requester_person_ref=actor.person_ref,
            recipient_principal_id=body.get("recipient_principal_id"),
            recipient_person_ref=body.get("recipient_person_ref"),
            reason=body.get("reason"),
            expires_at=body.get("expires_at"),
        )
    except CustomerBundleDeliveryRejected as exc:
        _delivery_error(exc)


@router.post("/checkout-orders/{order_id}/bundle-grants/{grant_id}/approve")
def approve_customer_bundle_grant(
    order_id: str,
    grant_id: str,
    body: dict,
    request: Request,
    x_ola_csrf: str | None = Header(default=None),
):
    actor = _actor(request, "tenant_identity_admin")
    _csrf(request, x_ola_csrf)
    try:
        return approve_recipient_grant(
            tenant_id=actor.tenant_id,
            order_id=order_id,
            grant_id=grant_id,
            approver_principal_id=actor.principal_id,
            approver_person_ref=actor.person_ref,
            reason=body.get("reason"),
        )
    except CustomerBundleDeliveryRejected as exc:
        _delivery_error(exc)


@router.post("/checkout-orders/{order_id}/bundle-grants/{grant_id}/revoke")
def revoke_customer_bundle_grant(
    order_id: str,
    grant_id: str,
    body: dict,
    request: Request,
    x_ola_csrf: str | None = Header(default=None),
):
    actor = _actor(request, "tenant_identity_admin")
    _csrf(request, x_ola_csrf)
    try:
        return revoke_recipient_grant(
            tenant_id=actor.tenant_id,
            order_id=order_id,
            grant_id=grant_id,
            actor_principal_id=actor.principal_id,
            actor_person_ref=actor.person_ref,
            reason=body.get("reason"),
        )
    except CustomerBundleDeliveryRejected as exc:
        _delivery_error(exc)


@router.get("/checkout-orders/{order_id}/bundles/{bundle_id}/download")
def download_customer_bundle(
    order_id: str,
    bundle_id: str,
    request: Request,
):
    """Stream an encrypted-at-rest bundle only to its OIDC-authenticated recipient."""
    actor = _actor(request, "recipient")
    try:
        attempt = begin_delivery_attempt(
            tenant_id=actor.tenant_id,
            order_id=order_id,
            bundle_id=bundle_id,
            recipient_principal_id=actor.principal_id,
            recipient_person_ref=actor.person_ref,
        )
    except CustomerBundleDeliveryRejected as exc:
        _delivery_error(exc)

    if attempt["status"] != "STARTED":
        raise HTTPException(
            status_code=403,
            detail={
                "code": attempt["reason"] or "DELIVERY_BLOCKED",
                "attempt_id": attempt["attempt_id"],
            },
        )

    with SessionLocal() as db:
        bundle = db.scalar(select(CustomerEvidenceBundle).where(
            CustomerEvidenceBundle.id == bundle_id,
            CustomerEvidenceBundle.tenant_id == actor.tenant_id,
            CustomerEvidenceBundle.order_id == order_id,
        ))
        object_ref = bundle.storage_object_ref if bundle is not None else None
        version = bundle.version if bundle is not None else None

    storage = customer_bundle_storage_from_environment(profile=_deployment_profile())
    if storage is None or not object_ref:
        try:
            fail_delivery_attempt(
                tenant_id=actor.tenant_id,
                attempt_id=attempt["attempt_id"],
                recipient_principal_id=actor.principal_id,
                recipient_person_ref=actor.person_ref,
                reason="encrypted object storage is not configured for this deployment profile",
            )
        except CustomerBundleDeliveryRejected:
            pass
        raise HTTPException(
            status_code=503,
            detail="approved encrypted customer-bundle storage adapter is not configured",
        )

    try:
        payload = storage.get(object_ref)
    except CustomerBundleStorageRejected as exc:
        try:
            fail_delivery_attempt(
                tenant_id=actor.tenant_id,
                attempt_id=attempt["attempt_id"],
                recipient_principal_id=actor.principal_id,
                recipient_person_ref=actor.person_ref,
                reason="encrypted object retrieval or authentication failed",
            )
        except CustomerBundleDeliveryRejected:
            pass
        raise HTTPException(status_code=503, detail="customer bundle could not be retrieved safely") from exc

    filename = f"OLA-customer-evidence-v{version}.zip"

    def stream():
        try:
            yield payload
        except BaseException:
            try:
                fail_delivery_attempt(
                    tenant_id=actor.tenant_id,
                    attempt_id=attempt["attempt_id"],
                    recipient_principal_id=actor.principal_id,
                    recipient_person_ref=actor.person_ref,
                    reason="client disconnected or transfer failed",
                )
            except CustomerBundleDeliveryRejected:
                pass
            raise
        else:
            complete_delivery_attempt(
                tenant_id=actor.tenant_id,
                attempt_id=attempt["attempt_id"],
                recipient_principal_id=actor.principal_id,
                recipient_person_ref=actor.person_ref,
            )

    return StreamingResponse(
        stream(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/checkout-orders/{order_id}/bundles/{bundle_id}/attempts/{attempt_id}/acknowledge")
def acknowledge_customer_bundle_delivery(
    order_id: str,
    bundle_id: str,
    attempt_id: str,
    request: Request,
    x_ola_csrf: str | None = Header(default=None),
):
    """Record a recipient account's explicit acknowledgement after transfer completion."""
    actor = _actor(request, "recipient")
    _csrf(request, x_ola_csrf)
    try:
        return acknowledge_delivery_attempt(
            tenant_id=actor.tenant_id,
            order_id=order_id,
            bundle_id=bundle_id,
            attempt_id=attempt_id,
            recipient_principal_id=actor.principal_id,
            recipient_person_ref=actor.person_ref,
        )
    except CustomerBundleDeliveryRejected as exc:
        _delivery_error(exc)
