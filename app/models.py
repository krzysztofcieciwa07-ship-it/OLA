import uuid
import time
from sqlalchemy import Column, String, Integer, Text, ForeignKey, UniqueConstraint, Boolean
from .database import Base


def uid():
    return str(uuid.uuid4())


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    key_hash = Column(String(64), nullable=False, unique=True)
    role = Column(String(32), nullable=False, default="tenant")
    # Pseudonymous HR-backed owner; required for accountable requester SoD
    # when the tenant has enabled OIDC_REQUIRED.
    owner_person_ref = Column(String(64), nullable=True, index=True)


class TenantIdentityPolicy(Base):
    """Persistent, monotonic tenant policy for human approval identities."""
    __tablename__ = "tenant_identity_policies"
    tenant_id = Column(String(36), ForeignKey("tenants.id"), primary_key=True)
    human_gate_mode = Column(String(32), nullable=False, default="LEGACY_API")
    changed_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    changed_by_ref = Column(String(128), nullable=False)
    reason = Column(Text, nullable=False)


class HumanSession(Base):
    """Server-side Human Identity session; cookie carries only session_hash input."""
    __tablename__ = "human_sessions"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True, index=True)
    principal_ref = Column(String(64), nullable=True, index=True)
    session_hash = Column(String(64), nullable=False, unique=True, index=True)
    session_data_encrypted = Column(Text, nullable=False)
    auth_time = Column(Integer, nullable=True)
    mfa_verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    updated_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    expires_at = Column(Integer, nullable=False)
    revoked_at = Column(Integer, nullable=True)


class TenantIdentityProvider(Base):
    """Tenant-controlled OIDC issuer configuration; secrets remain external."""
    __tablename__ = "tenant_identity_providers"
    tenant_id = Column(String(36), ForeignKey("tenants.id"), primary_key=True)
    issuer = Column(String(1024), nullable=False)
    discovery_url = Column(String(1024), nullable=False)
    client_id = Column(String(255), nullable=False)
    client_secret_ref = Column(String(128), nullable=False)
    redirect_uri = Column(String(1024), nullable=False)
    id_token_algorithm = Column(String(32), nullable=False, default="RS256")
    mfa_acr_values_json = Column(Text, nullable=False, default="[]")
    mfa_amr_values_json = Column(Text, nullable=False, default="[]")
    enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    updated_at = Column(Integer, nullable=False, default=lambda: int(time.time()))


class HumanPrincipal(Base):
    """Mutable OIDC account mapping; raw identifiers stay outside append-only Evidence."""
    __tablename__ = "human_principals"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    issuer = Column(String(1024), nullable=False)
    subject = Column(String(512), nullable=False)
    status = Column(String(32), nullable=False, default="UNASSIGNED")
    # HMAC-derived tenant-scoped identity of a real HR person, never raw HR data.
    person_ref = Column(String(64), nullable=True, index=True)
    person_key_source = Column(String(32), nullable=True)
    person_bound_at = Column(Integer, nullable=True)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    last_authenticated_at = Column(Integer, nullable=True)
    __table_args__ = (
        UniqueConstraint("tenant_id", "issuer", "subject", name="uq_human_principal_tenant_issuer_subject"),
    )


class HumanMembershipRole(Base):
    """Tenant role binding to an explicitly provisioned human principal."""
    __tablename__ = "human_membership_roles"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    principal_id = Column(String(36), ForeignKey("human_principals.id"), nullable=False, index=True)
    role = Column(String(40), nullable=False)
    status = Column(String(24), nullable=False, default="ACTIVE")
    created_by_ref = Column(String(64), nullable=False)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    revoked_at = Column(Integer, nullable=True)
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "principal_id", "role",
            name="uq_human_membership_role_tenant_principal_role",
        ),
    )


class HumanRoleChangeRequest(Base):
    """Dual-controlled request to grant or revoke a privileged tenant role."""
    __tablename__ = "human_role_change_requests"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    requester_principal_id = Column(String(36), ForeignKey("human_principals.id"), nullable=False)
    requester_person_ref = Column(String(64), nullable=False)
    target_principal_id = Column(String(36), ForeignKey("human_principals.id"), nullable=False)
    target_person_ref = Column(String(64), nullable=False)
    requested_role = Column(String(40), nullable=False)
    operation = Column(String(12), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(24), nullable=False, default="PENDING")
    approver_principal_id = Column(String(36), ForeignKey("human_principals.id"), nullable=True)
    approver_person_ref = Column(String(64), nullable=True)
    requested_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    approved_at = Column(Integer, nullable=True)
    request_evidence_id = Column(String(36), nullable=True)
    approval_evidence_id = Column(String(36), nullable=True)


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    record_type = Column(String(100), nullable=False)
    payload_json = Column(Text, nullable=False)
    prev_hash = Column(String(64), nullable=False)
    record_hash = Column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "seq", name="uq_evidence_tenant_seq"),)



class StripeEvent(Base):
    __tablename__ = "stripe_events"
    id = Column(String(36), primary_key=True)
    event_id = Column(String(255), nullable=False, unique=True, index=True)
    status = Column(String(32), nullable=False)
    run_id = Column(String(36), nullable=True)
    task = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)


class CheckoutOrder(Base):
    """Durable, tenant-scoped intent to create one Stripe Checkout Session."""
    __tablename__ = "checkout_orders"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    idempotency_key_hash = Column(String(64), nullable=False)
    request_hash = Column(String(64), nullable=False)
    task = Column(Text, nullable=True)
    status = Column(String(32), nullable=False)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    stripe_session_id = Column(String(255), nullable=True, unique=True, index=True)
    checkout_url = Column(Text, nullable=True)
    payment_event_id = Column(String(255), nullable=True, unique=True)
    payment_result_json = Column(Text, nullable=True)
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key_hash", name="uq_checkout_order_tenant_idempotency"),
    )


class CheckoutOrderControl(Base):
    """Identity-bound Human Gate state for one paid Checkout order.

    The row is created with the order reservation. Legacy orders without this
    row are deliberately not approvable because their requester identity is
    not proven.
    """
    __tablename__ = "checkout_order_controls"
    id = Column(String(36), primary_key=True)
    order_id = Column(String(36), ForeignKey("checkout_orders.id"), nullable=False, unique=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    requester_id = Column(String(36), ForeignKey("api_keys.id"), nullable=False)
    requester_person_ref = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False)
    payment_evidence_id = Column(String(36), nullable=True)
    approver_id = Column(String(36), ForeignKey("api_keys.id"), nullable=True)
    approver_principal_id = Column(String(36), ForeignKey("human_principals.id"), nullable=True)
    approver_person_ref = Column(String(64), nullable=True)
    approval_reason = Column(Text, nullable=True)
    approved_tip_hash = Column(String(64), nullable=True)
    approval_record_hash = Column(String(64), nullable=True)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    approved_at = Column(Integer, nullable=True)


class HumanCheckoutReportReview(Base):
    """Report approval by a distinct HR-backed human reviewer."""
    __tablename__ = "human_checkout_report_reviews"
    id = Column(String(36), primary_key=True)
    order_id = Column(String(36), ForeignKey("checkout_orders.id"), nullable=False, unique=True, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    reviewer_principal_id = Column(String(36), ForeignKey("human_principals.id"), nullable=False)
    reviewer_person_ref = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    report_sha256 = Column(String(64), nullable=False)
    reviewed_tip_hash = Column(String(64), nullable=False)
    reason = Column(Text, nullable=False)
    approval_evidence_id = Column(String(36), nullable=True)
    reviewed_at = Column(Integer, nullable=False, default=lambda: int(time.time()))


class CheckoutExecutionJob(Base):
    """Durable, single-attempt outbox job created with Human Gate approval."""
    __tablename__ = "checkout_execution_jobs"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    order_id = Column(String(36), ForeignKey("checkout_orders.id"), nullable=False, unique=True, index=True)
    approval_record_hash = Column(String(64), nullable=False)
    task = Column(Text, nullable=False)
    status = Column(String(40), nullable=False, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    claim_token = Column(String(36), nullable=True)
    started_at = Column(Integer, nullable=True)
    finished_at = Column(Integer, nullable=True)
    run_id = Column(String(36), nullable=True)
    result_json = Column(Text, nullable=True)
    error_code = Column(String(100), nullable=True)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))


class CheckoutReportReview(Base):
    """Independent, tenant-scoped review gate for a completed customer report."""
    __tablename__ = "checkout_report_reviews"
    id = Column(String(36), primary_key=True)
    order_id = Column(String(36), ForeignKey("checkout_orders.id"), nullable=False, unique=True, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    reviewer_id = Column(String(36), ForeignKey("api_keys.id"), nullable=False)
    status = Column(String(32), nullable=False)
    report_sha256 = Column(String(64), nullable=False)
    reviewed_tip_hash = Column(String(64), nullable=False)
    reason = Column(Text, nullable=False)
    approval_evidence_id = Column(String(36), nullable=True)
    reviewed_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    delivery_evidence_id = Column(String(36), nullable=True)
    delivered_at = Column(Integer, nullable=True)


class CustomerEvidenceBundle(Base):
    """Immutable order-scoped signed artifact metadata; bytes live in private object storage."""
    __tablename__ = "customer_evidence_bundles"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    order_id = Column(String(36), ForeignKey("checkout_orders.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False)
    profile = Column(String(64), nullable=False)
    manifest_sha256 = Column(String(64), nullable=False)
    report_sha256 = Column(String(64), nullable=False)
    igor_key_id = Column(String(255), nullable=False)
    ola_key_id = Column(String(255), nullable=False)
    storage_object_ref = Column(String(1024), nullable=False, unique=True)
    approved_at = Column(Integer, nullable=False)
    approved_tip_hash = Column(String(64), nullable=False)
    signed_at = Column(Integer, nullable=False)
    signing_tip_hash = Column(String(64), nullable=False)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    expires_at = Column(Integer, nullable=True)
    revoked_at = Column(Integer, nullable=True)
    status_reason = Column(Text, nullable=True)
    __table_args__ = (
        UniqueConstraint("tenant_id", "order_id", "version",
                         name="uq_customer_bundle_tenant_order_version"),
    )


class CustomerBundleRecipientGrant(Base):
    """Dual-controlled recipient authorization scoped to exactly one paid order."""
    __tablename__ = "customer_bundle_recipient_grants"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    order_id = Column(String(36), ForeignKey("checkout_orders.id"), nullable=False, index=True)
    recipient_principal_id = Column(
        String(36), ForeignKey("human_principals.id"), nullable=False, index=True
    )
    recipient_person_ref = Column(String(64), nullable=False, index=True)
    requester_principal_id = Column(String(36), ForeignKey("human_principals.id"), nullable=False)
    requester_person_ref = Column(String(64), nullable=False)
    approver_principal_id = Column(String(36), ForeignKey("human_principals.id"), nullable=True)
    approver_person_ref = Column(String(64), nullable=True)
    status = Column(String(24), nullable=False, default="PENDING")
    reason = Column(Text, nullable=False)
    requested_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    approved_at = Column(Integer, nullable=True)
    expires_at = Column(Integer, nullable=False)
    revoked_at = Column(Integer, nullable=True)
    request_evidence_id = Column(String(36), nullable=True)
    approval_evidence_id = Column(String(36), nullable=True)
    revocation_evidence_id = Column(String(36), nullable=True)


class CustomerBundleDeliveryAttempt(Base):
    """One transfer attempt per bundle and recipient; retries create new rows."""
    __tablename__ = "customer_bundle_delivery_attempts"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    order_id = Column(String(36), ForeignKey("checkout_orders.id"), nullable=False, index=True)
    bundle_id = Column(
        String(36), ForeignKey("customer_evidence_bundles.id"), nullable=False, index=True
    )
    grant_id = Column(
        String(36), ForeignKey("customer_bundle_recipient_grants.id"), nullable=True, index=True
    )
    recipient_principal_id = Column(String(36), ForeignKey("human_principals.id"), nullable=False)
    recipient_person_ref = Column(String(64), nullable=False)
    attempt_no = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False)
    reason = Column(String(100), nullable=True)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    started_at = Column(Integer, nullable=True)
    completed_at = Column(Integer, nullable=True)
    failed_at = Column(Integer, nullable=True)
    acknowledged_at = Column(Integer, nullable=True)
    acknowledgement_evidence_id = Column(String(36), nullable=True)
    __table_args__ = (
        UniqueConstraint(
            "bundle_id", "recipient_person_ref", "attempt_no",
            name="uq_customer_bundle_recipient_attempt",
        ),
    )
