import uuid
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


class StateCheckpoint(Base):
    __tablename__ = "state_checkpoints"
    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    run_id = Column(String(36), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    stage = Column(String(120), nullable=False)
    status = Column(String(32), nullable=False)
    artifact_path = Column(Text, nullable=False)
    artifact_sha256 = Column(String(64), nullable=False)
    previous_hash = Column(String(64), nullable=False)
    state_hash = Column(String(64), nullable=False)
    payload_json = Column(Text, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "run_id", "sequence", name="uq_state_run_sequence"),)


class StripeEvent(Base):
    __tablename__ = "stripe_events"
    id = Column(String(36), primary_key=True)
    event_id = Column(String(255), nullable=False, unique=True, index=True)
    status = Column(String(32), nullable=False)
    run_id = Column(String(36), nullable=True)
    task = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
