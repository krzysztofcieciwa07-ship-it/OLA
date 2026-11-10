import uuid
import time
from sqlalchemy import Column, String, Integer, Text, ForeignKey, UniqueConstraint
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


class AgentFirewallRequest(Base):
    """Immutable action intent plus mutable evidence/execution pointers.

    The evidence ledger remains authoritative; these indexed fields are checked
    against the ledger before approval and execution.
    """
    __tablename__ = "agent_firewall_requests"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    requester_id = Column(String(36), ForeignKey("api_keys.id"), nullable=False)
    request_record_id = Column(String(36), ForeignKey("evidence_records.id"), nullable=False, unique=True)
    decision_record_id = Column(String(36), ForeignKey("evidence_records.id"), nullable=False, unique=True)
    target_id = Column(String(64), nullable=True)
    action_type = Column(String(64), nullable=False)
    unit = Column(String(128), nullable=True)
    environment = Column(String(16), nullable=True)
    target_config_digest = Column(String(64), nullable=True)
    action_digest = Column(String(64), nullable=True)
    policy_version = Column(String(128), nullable=False)
    decision = Column(String(16), nullable=False)
    risk_score = Column(Integer, nullable=True)
    reason_code = Column(String(100), nullable=False)
    evidence_status = Column(String(32), nullable=False, default="PENDING")
    checkpoint_record_id = Column(String(36), ForeignKey("evidence_records.id"), nullable=True)
    checkpoint_sha256 = Column(String(64), nullable=True)
    execution_status = Column(String(40), nullable=True)
    execution_checkpoint_record_id = Column(String(36), ForeignKey("evidence_records.id"), nullable=True)
    execution_checkpoint_sha256 = Column(String(64), nullable=True)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))


class AgentFirewallApproval(Base):
    """One-time, expiry-bound approval for one exact action digest."""
    __tablename__ = "agent_firewall_approvals"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    request_id = Column(String(36), ForeignKey("agent_firewall_requests.id"), nullable=False)
    action_digest = Column(String(64), nullable=False)
    requester_id = Column(String(36), ForeignKey("api_keys.id"), nullable=False)
    approver_id = Column(String(36), ForeignKey("api_keys.id"), nullable=False)
    status = Column(String(32), nullable=False)
    reason_sha256 = Column(String(64), nullable=False)
    approval_record_id = Column(String(36), ForeignKey("evidence_records.id"), nullable=True)
    approval_record_hash = Column(String(64), nullable=True)
    checkpoint_record_id = Column(String(36), ForeignKey("evidence_records.id"), nullable=True)
    checkpoint_sha256 = Column(String(64), nullable=True)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
    expires_at = Column(Integer, nullable=False)
    consumed_at = Column(Integer, nullable=True)
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_id", name="uq_agent_firewall_approval_tenant_request"),
    )
