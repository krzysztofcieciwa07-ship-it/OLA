"""Durable one-use consumption for signed OLA Human Gate approvals.

This module does not verify signatures, resolve OIDC memberships, evaluate
expiry, or authorize effects. Callers must do those checks first, then consume
the nonce in the same PostgreSQL transaction as the durable execution claim.
The service deliberately never commits that caller-owned transaction.
"""
from __future__ import annotations

import re
import uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .models import HumanGateApprovalNonce


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_ACTIONS = {"EXECUTE_PAID_ORDER", "APPROVE_CUSTOMER_REPORT"}


class ApprovalNonceReplayError(PermissionError):
    """The approval ID or nonce has already been consumed for this tenant."""


class ApprovalNonceLedgerUnavailable(RuntimeError):
    """The durable PostgreSQL approval nonce ledger cannot be used safely."""


def _canonical_uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a canonical UUID")
    try:
        normalized = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"{field} must be a canonical UUID") from None
    if normalized != value:
        raise ValueError(f"{field} must be a canonical lowercase UUID")
    return normalized


class PostgresApprovalNonceLedger:
    """Atomically consume a signed human approval nonce in a caller transaction.

    PostgreSQL ON CONFLICT handles concurrent duplicate attempts without a
    read-before-write race. The caller must commit this insert together with
    the job's RUNNING/claim transition. Rolling back the outer transaction
    releases the nonce claim; successful external work must never begin before
    that transaction commits.
    """

    def consume(
        self,
        db: Session,
        *,
        tenant_id: str,
        approval_id: str,
        nonce: str,
        operation_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        envelope_sha256: str,
        consumed_at: int,
    ) -> str:
        if db.get_bind().dialect.name != "postgresql":
            raise ApprovalNonceLedgerUnavailable(
                "Human Gate approval nonce consumption requires PostgreSQL"
            )

        tenant_id = _canonical_uuid(tenant_id, "tenant_id")
        approval_id = _canonical_uuid(approval_id, "approval_id")
        nonce = _canonical_uuid(nonce, "nonce")
        operation_id = _canonical_uuid(operation_id, "operation_id")
        if action not in _ALLOWED_ACTIONS:
            raise ValueError("unsupported Human Gate approval action")
        if not isinstance(resource_type, str) or not resource_type or len(resource_type) > 64:
            raise ValueError("resource_type is invalid")
        if not isinstance(resource_id, str) or not resource_id or len(resource_id) > 128:
            raise ValueError("resource_id is invalid")
        if not isinstance(envelope_sha256, str) or _SHA256_RE.fullmatch(envelope_sha256) is None:
            raise ValueError("envelope_sha256 must be a lowercase SHA-256 digest")
        if not isinstance(consumed_at, int) or isinstance(consumed_at, bool) or consumed_at <= 0:
            raise ValueError("consumed_at must be a positive integer timestamp")

        try:
            current_scope = db.execute(
                text("SELECT current_setting('ola.human_gate_tenant_id', true)")
            ).scalar_one_or_none()
            if current_scope not in (None, "", tenant_id):
                raise ApprovalNonceLedgerUnavailable(
                    "Human Gate nonce ledger tenant scope cannot change within this transaction"
                )
            db.execute(
                text("SELECT set_config('ola.human_gate_tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
        except ApprovalNonceLedgerUnavailable:
            raise
        except SQLAlchemyError:
            raise ApprovalNonceLedgerUnavailable(
                "Human Gate nonce ledger tenant scope could not be established"
            ) from None

        statement = (
            pg_insert(HumanGateApprovalNonce)
            .values(
                tenant_id=tenant_id,
                approval_id=approval_id,
                nonce=nonce,
                operation_id=operation_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                envelope_sha256=envelope_sha256,
                consumed_at=consumed_at,
            )
            .on_conflict_do_nothing()
            .returning(HumanGateApprovalNonce.id)
        )
        try:
            row_id = db.execute(statement).scalar_one_or_none()
        except SQLAlchemyError:
            raise ApprovalNonceLedgerUnavailable(
                "Human Gate approval nonce ledger write failed; execution must remain blocked"
            ) from None

        if row_id is None:
            raise ApprovalNonceReplayError(
                "signed Human Gate approval ID or nonce was already consumed"
            )
        return row_id
