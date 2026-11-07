"""Order-scoped approved-report to signed customer-bundle orchestration.

No signer, IGOR verifier, provenance verifier, TSA or storage adapter is
implicitly created here. Deployments must inject an audited runtime object;
missing dependencies fail closed.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import func, select

from app.customer_bundle.builder import (
    PRODUCTION_PROFILE,
    SANDBOX_PROFILE,
    build_customer_bundle,
    canonical_json_bytes,
)
from app.customer_bundle.signers import Ed25519Signer
from app.customer_bundle.storage import CustomerBundleStorage
from app.customer_bundle.verifier import verify_customer_bundle
from app.database import SessionLocal, begin_write_transaction
from app.hashchain import (
    EVIDENCE_META_KEY,
    GENESIS_HASH,
    compute_record_hash_v2,
    sealed_payload_json,
    trusted_record,
    verify_chain,
)
from app.models import (
    CheckoutExecutionJob,
    CheckoutOrder,
    CheckoutOrderControl,
    CustomerEvidenceBundle,
    EvidenceRecord,
    HumanCheckoutReportReview,
    Tenant,
    TenantIdentityPolicy,
)

HEX_64 = re.compile(r"^[0-9a-f]{64}$")
SAFE_EVIDENCE_FIELDS = frozenset({
    "order_id", "execution_job_id", "checkout_session_id", "payment_intent_id",
    "status", "decision", "report_sha256", "decision_report_sha256",
    "approved_tip_hash", "reviewed_tip_hash", "source_commit", "image_digest",
    "run_id", "amount_total", "currency", "event_id",
})


class CustomerBundleCreationRejected(ValueError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CustomerBundleRuntime:
    """Explicitly provisioned bundle dependencies; no production defaults."""
    profile: str
    igor_signer: Ed25519Signer
    ola_signer: Ed25519Signer
    storage: CustomerBundleStorage
    igor_attestation_provider: Callable[[dict], dict]
    provenance_provider: Callable[[dict], dict | None]
    timestamp_provider: Callable[[bytes], bytes] | None = None
    timestamp_verifier: Callable[[bytes, bytes, int], bool] | None = None
    bundle_ttl_seconds: int = 30 * 24 * 60 * 60


def _payload(record: dict) -> dict:
    try:
        value = json.loads(record["payload_json"])
    except (KeyError, TypeError, ValueError):
        raise CustomerBundleCreationRejected(409, "tenant Evidence payload is invalid") from None
    if not isinstance(value, dict):
        raise CustomerBundleCreationRejected(409, "tenant Evidence payload is not an object")
    value.pop(EVIDENCE_META_KEY, None)
    return value


def _order_evidence_excerpt(records: list[dict], *, order_id: str) -> bytes:
    excerpt = []
    for record in records:
        payload = _payload(record)
        if payload.get("order_id") != order_id or not trusted_record(record):
            continue
        safe_payload = {
            key: payload[key]
            for key in SAFE_EVIDENCE_FIELDS
            if key in payload
        }
        excerpt.append({
            "id": record["id"],
            "seq": record["seq"],
            "record_type": record["record_type"],
            "prev_hash": record["prev_hash"],
            "record_hash": record["record_hash"],
            "payload": safe_payload,
        })
    if not excerpt:
        raise CustomerBundleCreationRejected(409, "no order-scoped trusted evidence is available")
    return b"".join(canonical_json_bytes(item) + b"\n" for item in excerpt)


def _report_bytes(job_result: dict, *, expected_digest: str) -> bytes:
    report = job_result.get("report")
    decision_report = report.get("decision_report") if isinstance(report, dict) else None
    if not isinstance(decision_report, dict):
        raise CustomerBundleCreationRejected(409, "approved decision report is unavailable")
    material = dict(decision_report)
    embedded_digest = material.pop("report_sha256", None)
    data = canonical_json_bytes(material)
    actual = hashlib.sha256(data).hexdigest()
    if embedded_digest != expected_digest or actual != expected_digest:
        raise CustomerBundleCreationRejected(409, "stored report bytes do not match the approved digest")
    return data


def _append_locked(db, tenant_id: str, record_type: str, payload: dict) -> dict:
    latest = db.scalar(select(EvidenceRecord).where(
        EvidenceRecord.tenant_id == tenant_id,
    ).order_by(EvidenceRecord.seq.desc()).limit(1))
    seq = latest.seq + 1 if latest is not None else 0
    prev_hash = latest.record_hash if latest is not None else GENESIS_HASH
    payload_json = sealed_payload_json(record_type, payload, producer="ola_runtime")
    digest = compute_record_hash_v2(
        tenant_id, seq, prev_hash, record_type, "ola_runtime", payload_json,
    )
    record_id = str(uuid.uuid4())
    db.add(EvidenceRecord(
        id=record_id,
        tenant_id=tenant_id,
        seq=seq,
        record_type=record_type,
        payload_json=payload_json,
        prev_hash=prev_hash,
        record_hash=digest,
    ))
    db.flush()
    return {"id": record_id, "seq": seq, "record_hash": digest}


def _load_approved_order(tenant_id: str, order_id: str):
    with SessionLocal() as db:
        tenant = db.get(Tenant, tenant_id)
        policy = db.get(TenantIdentityPolicy, tenant_id)
        order = db.scalar(select(CheckoutOrder).where(
            CheckoutOrder.id == order_id,
            CheckoutOrder.tenant_id == tenant_id,
        ))
        control = db.scalar(select(CheckoutOrderControl).where(
            CheckoutOrder.order_id == order_id,
            CheckoutOrder.tenant_id == tenant_id,
        ))
        job = db.scalar(select(CheckoutExecutionJob).where(
            CheckoutExecutionJob.order_id == order_id,
            CheckoutExecutionJob.tenant_id == tenant_id,
        ))
        review = db.scalar(select(HumanCheckoutReportReview).where(
            HumanCheckoutReportReview.order_id == order_id,
            HumanCheckoutReportReview.tenant_id == tenant_id,
        ))
        if tenant is None or policy is None or policy.human_gate_mode != "OIDC_REQUIRED":
            raise CustomerBundleCreationRejected(403, "bundle creation requires persistent OIDC_REQUIRED tenant policy")
        if order is None:
            raise CustomerBundleCreationRejected(404, "paid order not found")
        if order.status != "REPORT_APPROVED" or control is None or job is None or review is None:
            raise CustomerBundleCreationRejected(409, "a completed, independently reviewed customer report is required")
        if (
            review.status != "APPROVED"
            or job.status != "EXECUTED_REVIEW_REQUIRED"
            or not review.approval_evidence_id
            or not review.reviewer_person_ref
            or not control.requester_person_ref
            or not control.approver_person_ref
        ):
            raise CustomerBundleCreationRejected(409, "Human Gate approval or HR-backed actor bindings are incomplete")
        if len({
            control.requester_person_ref,
            control.approver_person_ref,
            review.reviewer_person_ref,
        }) != 3:
            raise CustomerBundleCreationRejected(403, "requester, approver and reviewer must be three distinct HR-backed people")
        try:
            job_result = json.loads(job.result_json or "")
        except (ValueError, TypeError):
            raise CustomerBundleCreationRejected(409, "stored execution result is unavailable") from None
        if (
            not isinstance(job_result, dict)
            or job_result.get("status") != "EXECUTED_REVIEW_REQUIRED"
            or job_result.get("order_id") != order_id
            or job_result.get("execution_job_id") != job.id
            or any(job_result.get(name) != "VERIFIED" for name in (
                "nina_status", "igor_status", "provenance_status", "replay_status",
            ))
        ):
            raise CustomerBundleCreationRejected(409, "execution proof is not complete and independently verified")
        return {
            "order": order,
            "control": control,
            "job": job,
            "review": review,
            "job_result": job_result,
        }


def _load_chain_and_validate_approval(tenant_id: str, order_id: str, context: dict) -> tuple[list[dict], str, dict]:
    with SessionLocal() as db:
        rows = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id,
        ).order_by(EvidenceRecord.seq.asc())).all()
        records = [{
            "id": row.id,
            "tenant_id": row.tenant_id,
            "seq": row.seq,
            "record_type": row.record_type,
            "payload_json": row.payload_json,
            "prev_hash": row.prev_hash,
            "record_hash": row.record_hash,
        } for row in rows]
    valid, reason = verify_chain(records)
    if not valid or not records:
        raise CustomerBundleCreationRejected(409, f"tenant Evidence chain is invalid: {reason}")
    review = context["review"]
    approval_rows = [row for row in records if row["id"] == review.approval_evidence_id]
    if len(approval_rows) != 1:
        raise CustomerBundleCreationRejected(409, "exact report-approval Evidence record is missing")
    approval_record = approval_rows[0]
    if approval_record["record_type"] != "human.customer_report_approval" or not trusted_record(approval_record):
        raise CustomerBundleCreationRejected(409, "report-approval Evidence record is not trusted")
    approval_payload = _payload(approval_record)
    expected = {
        "order_id": order_id,
        "execution_job_id": context["job"].id,
        "reviewer_principal_id": review.reviewer_principal_id,
        "reviewer_person_ref": review.reviewer_person_ref,
        "report_sha256": review.report_sha256,
        "reviewed_tip_hash": review.reviewed_tip_hash,
        "decision": "REPORT_APPROVED",
        "reviewed_at": review.reviewed_at,
    }
    if any(approval_payload.get(key) != value for key, value in expected.items()):
        raise CustomerBundleCreationRejected(409, "report-approval Evidence does not match the approved report record")
    if not any(row["record_hash"] == review.reviewed_tip_hash for row in records):
        raise CustomerBundleCreationRejected(409, "reviewed Evidence tip is not present in the tenant chain")
    completion = []
    for row in records:
        if row["record_type"] != "revenue.execution_completed" or not trusted_record(row):
            continue
        payload = _payload(row)
        if (
            payload.get("order_id") == order_id
            and payload.get("execution_job_id") == context["job"].id
            and payload.get("decision_report_sha256") == review.report_sha256
            and payload.get("status") == "EXECUTED_REVIEW_REQUIRED"
        ):
            completion.append(row)
    if len(completion) != 1:
        raise CustomerBundleCreationRejected(409, "unique trusted execution-completion record is required")
    return records, records[-1]["record_hash"], approval_payload


def _delete_unpersisted_object(runtime: CustomerBundleRuntime, object_ref: str) -> None:
    try:
        runtime.storage.delete(object_ref)
    except Exception as exc:
        raise CustomerBundleCreationRejected(
            503,
            "bundle persistence failed and encrypted orphan cleanup also failed; operator quarantine is required",
        ) from exc


def create_customer_bundle_for_order(
    *,
    tenant_id: str,
    order_id: str,
    reviewer_principal_id: str,
    reviewer_person_ref: str,
    runtime: CustomerBundleRuntime,
    now: int | None = None,
) -> dict:
    """Create and persist a signed bundle only from a still-current approved report."""
    created_at = int(time.time()) if now is None else now
    if type(created_at) is not int:
        raise CustomerBundleCreationRejected(400, "bundle creation time must be an integer Unix timestamp")
    if not isinstance(runtime, CustomerBundleRuntime):
        raise CustomerBundleCreationRejected(503, "customer bundle signing and verification runtime is not configured")
    if runtime.profile not in {SANDBOX_PROFILE, PRODUCTION_PROFILE}:
        raise CustomerBundleCreationRejected(503, "customer bundle runtime profile is invalid")
    if type(runtime.bundle_ttl_seconds) is not int or not 300 <= runtime.bundle_ttl_seconds <= 365 * 24 * 60 * 60:
        raise CustomerBundleCreationRejected(503, "customer bundle retention window is invalid")
    for method in ("put", "get", "delete"):
        if not callable(getattr(runtime.storage, method, None)):
            raise CustomerBundleCreationRejected(503, "customer bundle storage adapter is incomplete")
    if not callable(runtime.igor_attestation_provider) or not callable(runtime.provenance_provider):
        raise CustomerBundleCreationRejected(503, "independent IGOR and provenance verifiers are required")

    context = _load_approved_order(tenant_id, order_id)
    review = context["review"]
    if (
        review.reviewer_principal_id != reviewer_principal_id
        or review.reviewer_person_ref != reviewer_person_ref
    ):
        raise CustomerBundleCreationRejected(403, "only the HR-bound report reviewer may initiate bundle issuance")

    existing = None
    with SessionLocal() as db:
        existing = db.scalar(select(CustomerEvidenceBundle).where(
            CustomerEvidenceBundle.tenant_id == tenant_id,
            CustomerEvidenceBundle.order_id == order_id,
            CustomerEvidenceBundle.report_sha256 == review.report_sha256,
            CustomerEvidenceBundle.profile == runtime.profile,
            CustomerEvidenceBundle.status == "SIGNED",
        ).order_by(CustomerEvidenceBundle.version.desc()).limit(1))
    if existing is not None and (existing.expires_at is None or existing.expires_at > created_at):
        return {
            "status": "ALREADY_SIGNED",
            "bundle_id": existing.id,
            "version": existing.version,
            "profile": existing.profile,
            "manifest_sha256": existing.manifest_sha256,
            "report_sha256": existing.report_sha256,
            "expires_at": existing.expires_at,
        }
    if existing is not None:
        with SessionLocal() as db:
            begin_write_transaction(db, tenant_id=tenant_id)
            expired = db.scalar(select(CustomerEvidenceBundle).where(
                CustomerEvidenceBundle.id == existing.id,
                CustomerEvidenceBundle.tenant_id == tenant_id,
            ).with_for_update())
            if expired is not None and expired.status == "SIGNED" and expired.expires_at <= created_at:
                expired.status = "EXPIRED"
                expired.status_reason = "bundle expiry reached before re-issuance"
                _append_locked(db, tenant_id, "revenue.customer_evidence_bundle_expired", {
                    "order_id": order_id,
                    "bundle_id": expired.id,
                    "version": expired.version,
                    "expired_at": created_at,
                    "reason": expired.status_reason,
                })
                db.commit()

    bundle_id = str(uuid.uuid4())
    expires_at = created_at + runtime.bundle_ttl_seconds
    with SessionLocal() as db:
        bundle_version = (db.scalar(select(func.max(CustomerEvidenceBundle.version)).where(
            CustomerEvidenceBundle.tenant_id == tenant_id,
            CustomerEvidenceBundle.order_id == order_id,
        )) or 0) + 1

    report_json = _report_bytes(context["job_result"], expected_digest=review.report_sha256)
    if not HEX_64.fullmatch(review.reviewed_tip_hash or ""):
        raise CustomerBundleCreationRejected(409, "approved Evidence tip is malformed")
    records, signing_tip_hash, _approval_payload = _load_chain_and_validate_approval(
        tenant_id, order_id, context,
    )
    signing_input = {
        "tenant_id": tenant_id,
        "order_id": order_id,
        "execution_job_id": context["job"].id,
        "report_sha256": review.report_sha256,
        "approved_tip_hash": review.reviewed_tip_hash,
        "evidence_tip_hash": signing_tip_hash,
        "tenant_evidence_records": records,
    }
    try:
        igor_attestation = runtime.igor_attestation_provider(signing_input)
        provenance_result = runtime.provenance_provider(signing_input)
    except Exception as exc:
        raise CustomerBundleCreationRejected(503, "independent IGOR or provenance verification service is unavailable") from exc
    if not isinstance(igor_attestation, dict):
        raise CustomerBundleCreationRejected(503, "independent IGOR attestation is unavailable")
    provenance_json = None
    provenance_verified = False
    source_sha = None
    image_digest = None
    if provenance_result is not None:
        if not isinstance(provenance_result, dict):
            raise CustomerBundleCreationRejected(503, "provenance verifier returned an invalid result")
        raw_provenance = provenance_result.get("json_bytes")
        if not isinstance(raw_provenance, bytes) or not raw_provenance:
            raise CustomerBundleCreationRejected(503, "provenance verifier did not return canonical evidence bytes")
        provenance_json = raw_provenance
        provenance_verified = provenance_result.get("verified") is True
        source_sha = provenance_result.get("source_sha")
        image_digest = provenance_result.get("image_digest")
    if runtime.profile == PRODUCTION_PROFILE and (
        runtime.timestamp_provider is None or runtime.timestamp_verifier is None
        or provenance_verified is not True
    ):
        raise CustomerBundleCreationRejected(503, "production TSA and independently verified provenance are not configured")

    evidence_excerpt = _order_evidence_excerpt(records, order_id=order_id)
    approval = {
        "status": "REPORT_APPROVED",
        "approved_at": review.reviewed_at,
        "approved_tip_hash": review.reviewed_tip_hash,
        "report_sha256": review.report_sha256,
        "requester_person_ref": context["control"].requester_person_ref,
        "approver_person_ref": context["control"].approver_person_ref,
        "reviewer_person_ref": review.reviewer_person_ref,
    }
    try:
        artifact = build_customer_bundle(
            tenant_id=tenant_id,
            order_id=order_id,
            bundle_id=bundle_id,
            bundle_version=bundle_version,
            created_at=created_at,
            expires_at=expires_at,
            profile=runtime.profile,
            report_json=report_json,
            evidence_excerpt=evidence_excerpt,
            provenance_json=provenance_json,
            approval=approval,
            igor_attestation=igor_attestation,
            igor_signer=runtime.igor_signer,
            ola_signer=runtime.ola_signer,
            approved_at=review.reviewed_at,
            approved_tip_hash=review.reviewed_tip_hash,
            signing_tip_hash=signing_tip_hash,
            signed_at=created_at,
            timestamp_provider=runtime.timestamp_provider,
            timestamp_verifier=runtime.timestamp_verifier,
            provenance_verified=provenance_verified,
            source_sha=source_sha,
            image_digest=image_digest,
        )
    except Exception as exc:
        raise CustomerBundleCreationRejected(409, f"customer bundle signing was blocked: {type(exc).__name__}") from exc

    verification = verify_customer_bundle(
        artifact.zip_bytes,
        trusted_keys={
            runtime.igor_signer.key_id: runtime.igor_signer.public_key_bytes,
            runtime.ola_signer.key_id: runtime.ola_signer.public_key_bytes,
        },
        timestamp_verifier=runtime.timestamp_verifier,
    )
    if (
        verification.status != artifact.status
        or verification.igor_signature != "VERIFIED"
        or verification.ola_signature != "VERIFIED"
        or verification.manifest_sha256 != artifact.manifest_sha256
        or verification.report_sha256 != artifact.report_sha256
        or runtime.profile == PRODUCTION_PROFILE
        and verification.timestamp_status != "VERIFIED"
    ):
        raise CustomerBundleCreationRejected(
            409,
            "independent offline verification of the generated customer bundle did not pass",
        )

    object_ref = None
    try:
        object_ref = runtime.storage.put(artifact.zip_bytes)
        if not isinstance(object_ref, str) or not object_ref:
            raise CustomerBundleCreationRejected(503, "storage adapter returned an invalid object reference")
        with SessionLocal() as db:
            begin_write_transaction(db, tenant_id=tenant_id)
            latest = db.scalar(select(EvidenceRecord).where(
                EvidenceRecord.tenant_id == tenant_id,
            ).order_by(EvidenceRecord.seq.desc()).limit(1))
            current_tip = latest.record_hash if latest is not None else GENESIS_HASH
            if current_tip != signing_tip_hash:
                raise CustomerBundleCreationRejected(409, "tenant Evidence tip changed during signing; bundle must be rebuilt")
            order = db.scalar(select(CheckoutOrder).where(
                CheckoutOrder.id == order_id,
                CheckoutOrder.tenant_id == tenant_id,
            ).with_for_update())
            current_review = db.scalar(select(HumanCheckoutReportReview).where(
                HumanCheckoutReportReview.order_id == order_id,
                HumanCheckoutReportReview.tenant_id == tenant_id,
            ).with_for_update())
            if (
                order is None or order.status != "REPORT_APPROVED"
                or current_review is None
                or current_review.status != "APPROVED"
                or current_review.report_sha256 != review.report_sha256
                or current_review.approval_evidence_id != review.approval_evidence_id
            ):
                raise CustomerBundleCreationRejected(409, "approved report changed during bundle signing")
            current_version = db.scalar(select(func.max(CustomerEvidenceBundle.version)).where(
                CustomerEvidenceBundle.tenant_id == tenant_id,
                CustomerEvidenceBundle.order_id == order_id,
            )) or 0
            if current_version + 1 != bundle_version:
                raise CustomerBundleCreationRejected(409, "bundle version changed during signing; bundle must be rebuilt")
            version = bundle_version
            bundle = CustomerEvidenceBundle(
                id=bundle_id,
                tenant_id=tenant_id,
                order_id=order_id,
                version=version,
                status="SIGNED",
                profile=runtime.profile,
                manifest_sha256=artifact.manifest_sha256,
                report_sha256=artifact.report_sha256,
                igor_key_id=artifact.igor_key_id,
                ola_key_id=artifact.ola_key_id,
                storage_object_ref=object_ref,
                approved_at=review.reviewed_at,
                approved_tip_hash=review.reviewed_tip_hash,
                signed_at=created_at,
                signing_tip_hash=signing_tip_hash,
                created_at=created_at,
                expires_at=expires_at,
                status_reason=None if artifact.status == "VERIFIED" else "cryptographic bundle signed; verification profile is PARTIAL",
            )
            db.add(bundle)
            evidence = _append_locked(db, tenant_id, "revenue.customer_evidence_bundle_signed", {
                "order_id": order_id,
                "bundle_id": bundle_id,
                "version": version,
                "profile": runtime.profile,
                "bundle_verification_status": artifact.status,
                "manifest_sha256": artifact.manifest_sha256,
                "report_sha256": artifact.report_sha256,
                "igor_key_id": artifact.igor_key_id,
                "ola_key_id": artifact.ola_key_id,
                "approved_tip_hash": review.reviewed_tip_hash,
                "signing_tip_hash": signing_tip_hash,
                "signed_at": created_at,
                "expires_at": expires_at,
            })
            db.commit()
    except CustomerBundleCreationRejected:
        if object_ref:
            _delete_unpersisted_object(runtime, object_ref)
        raise
    except Exception as exc:
        if object_ref:
            _delete_unpersisted_object(runtime, object_ref)
        raise CustomerBundleCreationRejected(503, "signed bundle could not be persisted safely") from exc

    return {
        "status": "SIGNED",
        "bundle_verification_status": artifact.status,
        "bundle_id": bundle_id,
        "version": version,
        "profile": runtime.profile,
        "manifest_sha256": artifact.manifest_sha256,
        "report_sha256": artifact.report_sha256,
        "expires_at": expires_at,
        "evidence_id": evidence["id"],
    }
