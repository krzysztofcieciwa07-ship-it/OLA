import uuid
import time
from sqlalchemy import Boolean, Column, String, Integer, Text, ForeignKey, UniqueConstraint
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




class HumanPrincipal(Base):
    """Pseudonymous OLA identity; external IdP claims are stored separately."""
    __tablename__ = "human_principals"
    id = Column(String(36), primary_key=True, default=uid)
    status = Column(String(24), nullable=False, default="ACTIVE")
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))


class HumanIdentityLink(Base):
    """Mutable encrypted link from one tenant's IdP subject to an OLA principal."""
    __tablename__ = "human_identity_links"
    id = Column(String(36), primary_key=True, default=uid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    principal_id = Column(String(36), ForeignKey("human_principals.id"), nullable=False, index=True)
    issuer_lookup_hash = Column(String(64), nullable=False)
    subject_lookup_hash = Column(String(64), nullable=False)
    person_ref_hash = Column(String(64), nullable=False)
    encrypted_issuer = Column(Text, nullable=False)
    encrypted_subject = Column(Text, nullable=False)
    provisioning_source = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False, default="ACTIVE")
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    revoked_at = Column(Integer, nullable=True)
    __table_args__ = (
        UniqueConstraint("tenant_id", "issuer_lookup_hash", "subject_lookup_hash",
                         name="uq_human_identity_external_subject"),
        UniqueConstraint("tenant_id", "person_ref_hash", name="uq_human_identity_person_ref"),
    )


class TenantIdentityConfig(Base):
    """One trusted identity issuer and explicit MFA claim map per tenant."""
    __tablename__ = "tenant_identity_configs"
    tenant_id = Column(String(36), ForeignKey("tenants.id"), primary_key=True)
    issuer = Column(Text, nullable=False)
    client_id = Column(String(255), nullable=False)
    client_secret_ref = Column(String(255), nullable=False)
    allowed_audiences_json = Column(Text, nullable=False)
    mfa_claim_mapping_json = Column(Text, nullable=False, default="{}")
    active = Column(Boolean, nullable=False, default=False)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    updated_at = Column(Integer, nullable=False, default=lambda: int(time.time()))


class TenantMembership(Base):
    """Explicit tenant membership and role; login alone never grants membership."""
    __tablename__ = "tenant_memberships"
    id = Column(String(36), primary_key=True, default=uid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    principal_id = Column(String(36), ForeignKey("human_principals.id"), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False, default="ACTIVE")
    provisioning_source = Column(String(32), nullable=False)
    created_by_principal_id = Column(String(36), ForeignKey("human_principals.id"), nullable=True)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    revoked_at = Column(Integer, nullable=True)
    __table_args__ = (
        UniqueConstraint("tenant_id", "principal_id", "role", name="uq_tenant_principal_role"),
    )


class HumanIdentityEnforcement(Base):
    """One-way latch requiring Human Identity for production human actions."""
    __tablename__ = "human_identity_enforcement"
    id = Column(String(36), primary_key=True, default="production")
    required = Column(Boolean, nullable=False, default=False)
    enabled_at = Column(Integer, nullable=True)
    enabled_by_principal_id = Column(
        String(36), ForeignKey("human_principals.id"), nullable=True
    )
    evidence_id = Column(String(36), nullable=True)


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
    status = Column(String(32), nullable=False)
    payment_evidence_id = Column(String(36), nullable=True)
    approver_id = Column(String(36), ForeignKey("api_keys.id"), nullable=True)
    approval_reason = Column(Text, nullable=True)
    approved_tip_hash = Column(String(64), nullable=True)
    approval_record_hash = Column(String(64), nullable=True)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    approved_at = Column(Integer, nullable=True)


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
