"""Live credential authority supplements, but never rewrites, review evidence.

A stored scope is a technical capability, not proof of a human identity. The
pure hash/source verifier remains in execution_binding.review_state.
"""
from __future__ import annotations

import json

from .execution_binding import review_state
from .models import ApiKey


CORE_SCOPE = "OLA_CORE"
REVIEW_SCOPE = "REVIEW_RESULT"
SCOPES = frozenset({CORE_SCOPE, REVIEW_SCOPE})


def credential_status(db, tenant_id, credential_id, required_scope):
    """Inspect current metadata within the caller's transaction; expose no hash."""
    if not isinstance(credential_id, str) or not credential_id:
        return "MISSING"
    key = db.get(ApiKey, credential_id, populate_existing=True)
    if key is None:
        return "MISSING"
    if key.tenant_id != tenant_id:
        return "TENANT_MISMATCH"
    if key.revoked_at is not None:
        return "REVOKED"
    if key.access_scope != required_scope:
        return "INVALID_SCOPE"
    return "ACTIVE"


def read_current_review(db, chain, run_id):
    """Return review state, digest, and current reviewer credential status.

    Revoked/missing/reassigned credentials cannot remain effective even when a
    prior record is internally consistent or would otherwise merely be STALE.
    """
    state, approval_digest = review_state(chain, run_id)
    approval = None
    for row in chain:
        if row.get("record_type") != "human.approval":
            continue
        try:
            payload = json.loads(row.get("payload_json", ""))
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("run_id") == run_id:
            approval = payload
    if approval is None:
        return state, approval_digest, "UNKNOWN"
    status = credential_status(
        db, approval.get("tenant_id"), approval.get("approver_id"), REVIEW_SCOPE,
    )
    if status != "ACTIVE":
        state = "BLOCKED"
    return state, approval_digest, status
