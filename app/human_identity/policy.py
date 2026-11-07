"""Persistent, downgrade-resistant tenant Human Gate identity policy."""
import json
import time
import uuid

from sqlalchemy import select

from app.database import SessionLocal, begin_write_transaction
from app.hashchain import GENESIS_HASH, compute_record_hash_v2, sealed_payload_json
from app.models import EvidenceRecord, Tenant, TenantIdentityPolicy


VALID_MODES = frozenset({"LEGACY_API", "OIDC_REQUIRED"})
VALID_PROFILES = frozenset({"sandbox", "test", "development", "production"})


class HumanIdentityPolicyRejected(ValueError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _append_policy_evidence_locked(db, tenant_id: str, record_type: str, payload: dict) -> dict:
    """Append trusted Evidence while the tenant's evidence-chain lock is held."""
    latest = db.scalar(
        select(EvidenceRecord)
        .where(EvidenceRecord.tenant_id == tenant_id)
        .order_by(EvidenceRecord.seq.desc())
        .limit(1)
    )
    seq = latest.seq + 1 if latest is not None else 0
    previous_hash = latest.record_hash if latest is not None else GENESIS_HASH
    payload_json = sealed_payload_json(record_type, payload, producer="ola_runtime")
    digest = compute_record_hash_v2(
        tenant_id, seq, previous_hash, record_type, "ola_runtime", payload_json,
    )
    record_id = str(uuid.uuid4())
    db.add(EvidenceRecord(
        id=record_id,
        tenant_id=tenant_id,
        seq=seq,
        record_type=record_type,
        payload_json=payload_json,
        prev_hash=previous_hash,
        record_hash=digest,
    ))
    db.flush()
    return {"id": record_id, "seq": seq, "record_hash": digest}


def set_tenant_human_gate_mode(
    *, tenant_id: str, actor_ref: str, reason: str, target_mode: str,
) -> dict:
    """Move LEGACY_API to OIDC_REQUIRED once; never downgrade a tenant."""
    values = (tenant_id, actor_ref, reason, target_mode)
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise HumanIdentityPolicyRejected(400, "tenant, pseudonymous actor reference, reason and target mode are required")
    if target_mode not in VALID_MODES:
        raise HumanIdentityPolicyRejected(400, "target mode must be LEGACY_API or OIDC_REQUIRED")
    if len(reason.strip()) > 1000:
        raise HumanIdentityPolicyRejected(400, "policy reason exceeds 1000 characters")
    if len(actor_ref.strip()) > 128:
        raise HumanIdentityPolicyRejected(400, "actor reference exceeds 128 characters")

    blocked = False
    result = None
    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise HumanIdentityPolicyRejected(404, "tenant not found")
        policy = db.scalar(
            select(TenantIdentityPolicy)
            .where(TenantIdentityPolicy.tenant_id == tenant_id)
            .with_for_update()
        )
        current_mode = policy.human_gate_mode if policy is not None else "LEGACY_API"

        if current_mode == "OIDC_REQUIRED" and target_mode == "LEGACY_API":
            evidence = _append_policy_evidence_locked(
                db, tenant_id, "human.identity_policy_downgrade_blocked", {
                    "tenant_id": tenant_id,
                    "actor_ref": actor_ref.strip(),
                    "current_mode": "OIDC_REQUIRED",
                    "requested_mode": "LEGACY_API",
                    "reason": reason.strip(),
                    "decision": "BLOCKED",
                    "attempted_at": int(time.time()),
                },
            )
            db.commit()
            blocked = True
        elif current_mode == target_mode:
            db.rollback()
            result = {
                "status": current_mode,
                "tenant_id": tenant_id,
                "changed": False,
            }
        elif current_mode == "LEGACY_API" and target_mode == "OIDC_REQUIRED":
            changed_at = int(time.time())
            if policy is None:
                policy = TenantIdentityPolicy(
                    tenant_id=tenant_id,
                    human_gate_mode="OIDC_REQUIRED",
                    changed_at=changed_at,
                    changed_by_ref=actor_ref.strip(),
                    reason=reason.strip(),
                )
                db.add(policy)
            else:
                policy.human_gate_mode = "OIDC_REQUIRED"
                policy.changed_at = changed_at
                policy.changed_by_ref = actor_ref.strip()
                policy.reason = reason.strip()
            evidence = _append_policy_evidence_locked(
                db, tenant_id, "human.identity_policy_enabled", {
                    "tenant_id": tenant_id,
                    "actor_ref": actor_ref.strip(),
                    "previous_mode": "LEGACY_API",
                    "new_mode": "OIDC_REQUIRED",
                    "reason": reason.strip(),
                    "decision": "ENABLED",
                    "changed_at": changed_at,
                    "policy_evidence_id": None,
                },
            )
            db.commit()
            result = {
                "status": "OIDC_REQUIRED",
                "tenant_id": tenant_id,
                "changed": True,
                "policy_evidence_id": evidence["id"],
                "policy_evidence_hash": evidence["record_hash"],
            }
        else:
            db.rollback()
            raise HumanIdentityPolicyRejected(409, "unsupported Human Gate identity policy transition")

    if blocked:
        raise HumanIdentityPolicyRejected(
            409, "OIDC_REQUIRED is permanent for this tenant; API-key fallback is blocked"
        )
    return result


def require_human_identity_mode(*, tenant_id: str, deployment_profile: str) -> str:
    """Resolve policy; production may never operate in legacy API-key mode."""
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise HumanIdentityPolicyRejected(400, "tenant_id is required")
    if not isinstance(deployment_profile, str) or deployment_profile.strip().lower() not in VALID_PROFILES:
        raise HumanIdentityPolicyRejected(400, "unknown deployment profile")
    profile = deployment_profile.strip().lower()

    with SessionLocal() as db:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise HumanIdentityPolicyRejected(404, "tenant not found")
        policy = db.get(TenantIdentityPolicy, tenant_id)
        mode = policy.human_gate_mode if policy is not None else "LEGACY_API"

    if profile == "production" and mode != "OIDC_REQUIRED":
        raise HumanIdentityPolicyRejected(
            403, "production Human Gate requires persistent OIDC_REQUIRED policy; API-key fallback is disabled"
        )
    return mode
