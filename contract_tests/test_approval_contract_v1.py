import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app import approval_contract_v1 as approval_contract
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from app.approval_contract_v1 import (
    ApprovalContractError,
    approval_is_current,
    canonical_payload_bytes,
    oidc_subject_fingerprint,
    payload_sha256,
    signing_input,
    validate_approval_semantics,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "signed-approval-record-v1.schema.json").read_text(encoding="utf-8"))
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
AUTHOR = "11111111-1111-4111-8111-111111111111"
EXECUTION_APPROVER = "22222222-2222-4222-8222-222222222222"
REPORT_REVIEWER = "33333333-3333-4333-8333-333333333333"
EVIDENCE_0 = "44444444-4444-4444-8444-444444444444"
EVIDENCE_1 = "55555555-5555-4555-8555-555555555555"
ZERO_HASH = "0" * 64
ONE_HASH = "1" * 64
SOURCE_COMMIT = "a" * 40


def ts(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def actor(principal_id, role):
    return {
        "principal_id": principal_id,
        "tenant_id": TENANT,
        "issuer": "https://login.example.test/tenant",
        "subject_fingerprint": "a" * 64 if role == "requester" else ("b" * 64 if role == "execution_approver" else "c" * 64),
        "fingerprint_key_id": "oidc-subject-v1",
        "role": role,
        "membership_version": 1,
    }


def payload(action="EXECUTE_PAID_ORDER", now=None):
    current = now or datetime.now(timezone.utc).replace(microsecond=0)
    is_report = action == "APPROVE_CUSTOMER_REPORT"
    return {
        "schema": "ola.signed-approval/v1",
        "approval_id": "66666666-6666-4666-8666-666666666666",
        "tenant_id": TENANT,
        "operation_id": "77777777-7777-4777-8777-777777777777",
        "request": {
            "action": action,
            "resource_type": "customer_report" if is_report else "checkout_order",
            "resource_id": "88888888-8888-4888-8888-888888888888",
            "sha256": "2" * 64,
        },
        "effect": {
            "action": "RELEASE_REPORT_TO_ORIGINAL_REQUESTER" if is_report else "QUEUE_SINGLE_EXECUTION",
            "target_id": "88888888-8888-4888-8888-888888888888",
            "target_sha256": "2" * 64,
        },
        "decision": "ALLOW",
        "effect_authorized": True,
        "execution_observed": "NOT_STARTED",
        "author": actor(AUTHOR, "requester"),
        "reviewer": actor(REPORT_REVIEWER if is_report else EXECUTION_APPROVER, "report_reviewer" if is_report else "execution_approver"),
        "prior_approvers": [actor(EXECUTION_APPROVER, "execution_approver")] if is_report else [],
        "reviewer_authentication": {
            "auth_time": ts(current - timedelta(seconds=10)),
            "acr": "urn:example:loa:2",
            "amr": ["webauthn", "mfa"],
            "session_fingerprint": "4" * 64,
        },
        "policy": {"version": "human-gate-v1", "sha256": "5" * 64},
        "evidence": {
            "tip_hash": ONE_HASH,
            "records": [
                {"id": EVIDENCE_0, "sequence": 0, "record_type": "request.created", "record_hash": ZERO_HASH},
                {"id": EVIDENCE_1, "sequence": 1, "record_type": "payment.confirmed" if not is_report else "execution.completed", "record_hash": ONE_HASH},
            ],
        },
        "runtime": {"source_commit": SOURCE_COMMIT},
        "reason": "Reviewed exact order/report, evidence and policy scope.",
        "nonce": "99999999-9999-4999-8999-999999999999",
        "issued_at": ts(current),
        "expires_at": ts(current + timedelta(minutes=5)),
        "closure": {"operational": "OPEN", "epistemic": "OPEN", "remedial": "OPEN"},
    }


def envelope(candidate):
    # Schema fixture only. This generated value is NOT a cryptographic approval
    # and is never submitted to a runtime or used to authorize an action.
    signature_fixture = base64.urlsafe_b64encode(bytes(range(64))).rstrip(b"=").decode("ascii")
    return {
        "payload": candidate,
        "signature": {
            "algorithm": "Ed25519",
            "key_id": "ola-approval-signing-v1",
            "value": signature_fixture,
        },
    }


def validate_schema(record):
    Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(record)


def test_schema_is_valid_draft_2020_12():
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("action", ["EXECUTE_PAID_ORDER", "APPROVE_CUSTOMER_REPORT"])
def test_valid_action_contract_passes_schema_and_semantic_checks(action):
    candidate = payload(action)
    validate_schema(envelope(candidate))
    validate_approval_semantics(candidate, now=datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00")))


def test_signed_input_is_deterministic_and_domain_separated():
    candidate = payload()
    first = signing_input(candidate)
    second = signing_input(dict(reversed(list(candidate.items()))))
    assert first == second
    assert first.startswith(b"OLA-SIGNED-APPROVAL\x00v1\x00")
    canonical = canonical_payload_bytes(candidate)
    assert payload_sha256(candidate) == hashlib.sha256(canonical).hexdigest()
    assert first.endswith(canonical)
    assert len(payload_sha256(candidate)) == 64


def test_canonical_payload_rejects_float_values():
    candidate = payload()
    candidate["non_canonical_float"] = 1.25
    with pytest.raises(ApprovalContractError, match="floating point"):
        canonical_payload_bytes(candidate)


def test_canonical_payload_rejects_non_nfc_text():
    candidate = payload()
    candidate["reason"] = "e\u0301"
    with pytest.raises(ApprovalContractError, match="NFC"):
        canonical_payload_bytes(candidate)


def test_canonical_payload_rejects_signature_inside_payload():
    candidate = payload()
    candidate["signature"] = {"algorithm": "Ed25519"}
    with pytest.raises(ApprovalContractError, match="signature envelope"):
        canonical_payload_bytes(candidate)


def test_canonical_payload_rejects_overlarge_integer():
    candidate = payload()
    candidate["sequence"] = 2 ** 60
    with pytest.raises(ApprovalContractError, match="safe range"):
        canonical_payload_bytes(candidate)


def test_same_subject_has_tenant_scoped_stable_fingerprint():
    key = b"k" * 32
    first = oidc_subject_fingerprint(
        key, "identity-k1", TENANT, "https://login.example.test/tenant", "subject-123",
    )
    second = oidc_subject_fingerprint(
        key, "identity-k1", TENANT, "https://login.example.test/tenant", "subject-123",
    )
    assert first == second
    assert first["algorithm"] == "HMAC-SHA-256"
    assert first["value"] != "subject-123"


def test_same_oidc_subject_is_not_linkable_across_tenants():
    key = b"k" * 32
    other_tenant = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    first = oidc_subject_fingerprint(
        key, "identity-k1", TENANT, "https://login.example.test/tenant", "subject-123",
    )
    second = oidc_subject_fingerprint(
        key, "identity-k1", other_tenant, "https://login.example.test/tenant", "subject-123",
    )
    assert first["value"] != second["value"]


def test_identity_fingerprint_requires_dedicated_minimum_length_key():
    with pytest.raises(ApprovalContractError, match="at least 32 bytes"):
        oidc_subject_fingerprint(
            b"short", "identity-k1", TENANT,
            "https://login.example.test/tenant", "subject-123",
        )


def test_untrusted_tenant_claim_is_not_an_input_to_membership_role_resolution():
    # The fingerprint accepts the resource tenant selected by the caller's
    # authorized resource context; it never accepts claims/groups/roles.
    key = b"k" * 32
    fp = oidc_subject_fingerprint(
        key, "identity-k1", TENANT,
        "https://login.example.test/tenant", "subject-123",
    )
    assert set(fp) == {"algorithm", "key_id", "value"}
    assert "role" not in fp and "tenant_role" not in fp


def test_author_cannot_approve_own_action():
    candidate = payload()
    candidate["reviewer"] = dict(candidate["author"])
    with pytest.raises(ApprovalContractError, match="cannot approve their own"):
        validate_approval_semantics(candidate, now=datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00")))


def test_report_reviewer_must_be_distinct_from_execution_approver():
    candidate = payload("APPROVE_CUSTOMER_REPORT")
    candidate["reviewer"] = dict(candidate["prior_approvers"][0])
    with pytest.raises(ApprovalContractError, match="distinct from prior"):
        validate_approval_semantics(candidate, now=datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00")))


@pytest.mark.parametrize("decision", ["REFUSE", "UNRESOLVED", "INCOMPARABLE"])
def test_non_allow_disposition_cannot_authorize_effect(decision):
    candidate = payload()
    candidate["decision"] = decision
    candidate["effect_authorized"] = True
    with pytest.raises(ApprovalContractError, match="only ALLOW"):
        validate_approval_semantics(candidate, now=datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00")))


def test_allow_disposition_cannot_claim_execution_already_started():
    candidate = payload()
    candidate["execution_observed"] = "SUCCEEDED"
    with pytest.raises(ApprovalContractError, match="cannot claim"):
        validate_approval_semantics(candidate, now=datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00")))


def test_approval_cannot_claim_any_form_of_closure():
    candidate = payload()
    candidate["closure"]["operational"] = "CLOSED"
    with pytest.raises(ApprovalContractError, match="cannot self-assert closure"):
        validate_approval_semantics(candidate, now=datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00")))


def test_approval_ttl_is_bounded_to_five_minutes():
    candidate = payload()
    issued = datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00"))
    candidate["expires_at"] = ts(issued + timedelta(minutes=5, seconds=1))
    with pytest.raises(ApprovalContractError, match="five-minute"):
        validate_approval_semantics(candidate, now=issued)


def test_stale_reviewer_step_up_authentication_is_rejected():
    candidate = payload()
    issued = datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00"))
    candidate["reviewer_authentication"]["auth_time"] = ts(issued - timedelta(minutes=5, seconds=1))
    with pytest.raises(ApprovalContractError, match="too old"):
        validate_approval_semantics(candidate, now=issued)


def test_effect_digest_must_match_request_digest():
    candidate = payload()
    candidate["effect"]["target_sha256"] = "3" * 64
    with pytest.raises(ApprovalContractError, match="must match the request digest"):
        validate_approval_semantics(candidate, now=datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00")))


def test_evidence_tip_must_equal_last_referenced_record():
    candidate = payload()
    candidate["evidence"]["tip_hash"] = "9" * 64
    with pytest.raises(ApprovalContractError, match="final referenced"):
        validate_approval_semantics(candidate, now=datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00")))


def test_evidence_sequence_must_be_strictly_increasing():
    candidate = payload()
    candidate["evidence"]["records"][1]["sequence"] = 0
    with pytest.raises(ApprovalContractError, match="strictly increasing"):
        validate_approval_semantics(candidate, now=datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00")))


def test_actor_membership_must_match_record_tenant():
    candidate = payload()
    candidate["reviewer"]["tenant_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    with pytest.raises(ApprovalContractError, match="not bound to the record tenant"):
        validate_approval_semantics(candidate, now=datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00")))


@pytest.mark.parametrize("issuer", [
    "http://login.example.test/tenant",
    "https://",
    "https://user@login.example.test/tenant",
    "https://login.example.test:444/tenant",
    "https://login.example.test/tenant?query=1",
    "https://login.example.test/tenant#fragment",
    "https://login.example.test/tenant with space",
])
def test_actor_issuer_must_be_exact_https_without_unsafe_components(issuer):
    candidate = payload()
    candidate["author"]["issuer"] = issuer
    with pytest.raises(ApprovalContractError, match="issuer"):
        validate_approval_semantics(candidate, now=datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00")))


def test_membership_version_rejects_boolean():
    candidate = payload()
    candidate["reviewer"]["membership_version"] = True
    with pytest.raises(ApprovalContractError, match="membership version"):
        validate_approval_semantics(candidate, now=datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00")))


def test_semantic_validator_rejects_unhashable_decision():
    candidate = payload()
    candidate["decision"] = []
    with pytest.raises(ApprovalContractError, match="decision is invalid"):
        validate_approval_semantics(candidate, now=datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00")))


def test_approval_window_is_checked_without_mutating_record():
    candidate = payload()
    issued = datetime.fromisoformat(candidate["issued_at"].replace("Z", "+00:00"))
    assert approval_is_current(candidate, now=issued + timedelta(minutes=1)) is True
    assert approval_is_current(candidate, now=issued + timedelta(minutes=6)) is False
    assert approval_is_current(candidate, now=issued + timedelta(minutes=5)) is False
    assert candidate["execution_observed"] == "NOT_STARTED"


def test_schema_rejects_unknown_properties():
    candidate = payload()
    candidate["ambient_authority"] = True
    with pytest.raises(ValidationError):
        validate_schema(envelope(candidate))


def test_schema_rejects_non_ed25519_signature_algorithm():
    record = envelope(payload())
    record["signature"]["algorithm"] = "HS256"
    with pytest.raises(ValidationError):
        validate_schema(record)


def _require_signature_verifier():
    verifier = getattr(approval_contract, "verify_signed_approval_envelope", None)
    assert callable(verifier), "Ed25519 approval-envelope verifier is not implemented"
    return verifier


def _signed_envelope(candidate, private_key, key_id="test-ed25519-k1"):
    signature = private_key.sign(signing_input(candidate))
    value = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return (
        {
            "payload": candidate,
            "signature": {
                "algorithm": "Ed25519",
                "key_id": key_id,
                "value": value,
            },
        },
        public_key,
    )


def test_ed25519_verifier_accepts_valid_signature_for_exact_trusted_key():
    verifier = _require_signature_verifier()
    candidate = payload()
    private_key = Ed25519PrivateKey.generate()
    record, public_key = _signed_envelope(candidate, private_key)
    assert verifier(record, {"test-ed25519-k1": public_key}) is True


def test_ed25519_verifier_rejects_payload_tampering():
    verifier = _require_signature_verifier()
    candidate = payload()
    private_key = Ed25519PrivateKey.generate()
    record, public_key = _signed_envelope(candidate, private_key)
    record["payload"]["reason"] += " tampered"
    with pytest.raises(ApprovalContractError):
        verifier(record, {"test-ed25519-k1": public_key})


def test_ed25519_verifier_rejects_unknown_or_untrusted_key_id():
    verifier = _require_signature_verifier()
    candidate = payload()
    private_key = Ed25519PrivateKey.generate()
    record, public_key = _signed_envelope(candidate, private_key)
    with pytest.raises(ApprovalContractError):
        verifier(record, {"different-key-id": public_key})
