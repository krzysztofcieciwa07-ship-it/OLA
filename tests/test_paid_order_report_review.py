"""Report review and tenant-bound delivery tests for paid OLA orders."""
import hashlib
import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import CheckoutExecutionJob, CheckoutReportReview, CheckoutOrder, EvidenceRecord
from app.paid_order_execution import execute_paid_order_job
from test_paid_order_approval import _seed_paid_order, _approve


def _completed_order(monkeypatch):
    from app import nina_execution

    ctx = _seed_paid_order(monkeypatch)
    approved = _approve(ctx)
    assert approved.status_code == 200, approved.text
    with SessionLocal() as db:
        job = db.scalar(select(CheckoutExecutionJob).where(
            CheckoutExecutionJob.order_id == ctx["order_id"]
        ))
        job_id = job.id

    confidential = "CONFIDENTIAL_REPORT_BODY_" + ctx["order_id"]
    report_body = {"summary": confidential, "report_id": ctx["order_id"]}
    report_digest = hashlib.sha256(
        json.dumps(report_body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    decision_report = {**report_body, "report_sha256": report_digest}
    def runner(*args, **kwargs):
        return {
            "run_id": "run-" + ctx["order_id"],
            "nina": {"status": "VERIFIED"},
            "igor": {"status": "VERIFIED"},
            "provenance": {"status": "VERIFIED"},
            "replay_verification": {"status": "VERIFIED"},
            "decision_report": decision_report,
            "status": "REVIEW",
        }
    result = execute_paid_order_job(job_id, runner=runner)
    assert result["status"] == "EXECUTED_REVIEW_REQUIRED"
    ctx.update({"job_id": job_id, "report_digest": report_digest, "confidential": confidential})
    return ctx


def _tip(ctx):
    response = TestClient(app).get("/evidence/tip", headers={"X-API-Key": ctx["requester_key"]})
    assert response.status_code == 200, response.text
    return response.json()["tip_hash"]


def _review(ctx, *, reviewer_key=None, tip_hash=None, report_sha256=None):
    return TestClient(app).post(
        f"/checkout-orders/{ctx['order_id']}/review-report",
        headers={"Authorization": f"Bearer {reviewer_key or ctx['reviewer_key']}"},
        json={
            "tip_hash": tip_hash or _tip(ctx),
            "report_sha256": report_sha256 or ctx["report_digest"],
            "reason": "Independent review of the exact report and evidence tip",
        },
    )


def test_checkout_retry_never_discloses_completed_report(monkeypatch):
    from app.main import app as main_app
    ctx = _completed_order(monkeypatch)
    response = TestClient(main_app).post(
        "/checkout",
        headers={"X-API-Key": ctx["requester_key"], "Idempotency-Key": ctx["idempotency_key"]},
        json={"task": ctx["task"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    serialized = json.dumps(body, sort_keys=True)
    assert "execution_result" not in body
    assert "report" not in body
    assert ctx["confidential"] not in serialized


def test_report_review_and_download_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/checkout-orders/{order_id}/review-report" in paths
    assert "/checkout-orders/{order_id}/report" in paths


def test_customer_cannot_download_report_before_independent_review(monkeypatch):
    ctx = _completed_order(monkeypatch)
    response = TestClient(app).get(
        f"/checkout-orders/{ctx['order_id']}/report",
        headers={"Authorization": f"Bearer {ctx['requester_key']}"},
    )
    assert response.status_code == 409
    assert ctx["confidential"] not in response.text


def test_report_review_requires_third_distinct_identity(monkeypatch):
    ctx = _completed_order(monkeypatch)
    requester_attempt = _review(ctx, reviewer_key=ctx["requester_key"])
    approver_attempt = _review(ctx, reviewer_key=ctx["approver_key"])
    assert requester_attempt.status_code == 403
    assert approver_attempt.status_code == 403


def test_report_review_binds_digest_and_fresh_evidence_tip(monkeypatch):
    ctx = _completed_order(monkeypatch)
    wrong_digest = _review(ctx, report_sha256="f" * 64)
    assert wrong_digest.status_code == 409
    stale_tip = _review(ctx, tip_hash="0" * 64)
    assert stale_tip.status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(CheckoutReportReview).where(
            CheckoutReportReview.order_id == ctx["order_id"]
        )) is None


def test_reviewed_report_is_delivered_only_to_original_requester(monkeypatch):
    ctx = _completed_order(monkeypatch)
    approved = _review(ctx)
    assert approved.status_code == 200, approved.text
    approval_body = approved.json()
    assert approval_body["status"] == "REPORT_APPROVED"
    assert "report" not in approval_body
    assert ctx["confidential"] not in json.dumps(approval_body)

    wrong_identity = TestClient(app).get(
        f"/checkout-orders/{ctx['order_id']}/report",
        headers={"Authorization": f"Bearer {ctx['approver_key']}"},
    )
    assert wrong_identity.status_code == 403

    delivered = TestClient(app).get(
        f"/checkout-orders/{ctx['order_id']}/report",
        headers={"Authorization": f"Bearer {ctx['requester_key']}"},
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["status"] == "REPORT_DELIVERED"
    assert delivered.json()["report"]["decision_report"]["summary"] == ctx["confidential"]

    repeated = TestClient(app).get(
        f"/checkout-orders/{ctx['order_id']}/report",
        headers={"Authorization": f"Bearer {ctx['requester_key']}"},
    )
    assert repeated.status_code == 200
    assert repeated.json() == delivered.json()

    with SessionLocal() as db:
        review = db.scalar(select(CheckoutReportReview).where(
            CheckoutReportReview.order_id == ctx["order_id"]
        ))
        order = db.get(CheckoutOrder, ctx["order_id"])
        job = db.get(CheckoutExecutionJob, ctx["job_id"])
        records = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == ctx["tenant_id"]
        )).all()
    assert review.status == "APPROVED"
    assert review.delivery_evidence_id
    assert review.reviewer_id == ctx["reviewer_id"]
    assert order.status == "REPORT_DELIVERED"
    assert job.status == "EXECUTED_REVIEW_REQUIRED"
    assert sum(row.record_type == "human.customer_report_approval" for row in records) == 1
    assert sum(row.record_type == "revenue.report_delivered" for row in records) == 1


def test_third_tenant_key_without_report_reviewer_role_is_rejected(monkeypatch):
    import uuid
    from app.api_key_hashing import api_key_fingerprint
    from app.models import ApiKey
    ctx = _completed_order(monkeypatch)
    ordinary_key = "ordinary-tenant-key-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(ApiKey(
            id=str(uuid.uuid4()), tenant_id=ctx["tenant_id"],
            key_hash=api_key_fingerprint(ordinary_key), role="tenant",
        ))
        db.commit()
    response = _review(ctx, reviewer_key=ordinary_key)
    assert response.status_code == 403
