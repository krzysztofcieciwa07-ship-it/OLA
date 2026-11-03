"""Tenant-scoped operation receipt reconstructed from verified OLA Evidence V2.

This module does not contact or impersonate the external Vantage service.
A verified local ledger is not independent production attestation.
"""
from datetime import datetime, timezone
import json
import re
import uuid

from .hashchain import trusted_record, verify_chain
from .igor import IgorVerifier
from .nina_igor import NinaIgorChain, STATUS_FIELDS
from .replay import verify_replay
from .vantage_client import verify_signed_envelope, VantagePolicyError

MAX_TENANT_RECORDS = 5000
SOURCE_COMMIT = re.compile(r"[a-fA-F0-9]{40}\Z")


class ReceiptRejected(ValueError):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


def read_operation_receipt(*, tenant_id, run_id, records, expected_commit):
    try:
        if str(uuid.UUID(run_id)) != run_id:
            raise ValueError("noncanonical run id")
    except (TypeError, ValueError, AttributeError) as exc:
        raise ReceiptRejected(400, "invalid operation id") from exc
    if len(records) > MAX_TENANT_RECORDS:
        raise ReceiptRejected(503, "tenant ledger exceeds verified read window")
    if not records:
        raise ReceiptRejected(404, "operation not found")
    if any(row.get("tenant_id") != tenant_id for row in records):
        raise ReceiptRejected(409, "tenant evidence mismatch")
    chain_ok, _ = verify_chain(records)
    if not chain_ok:
        raise ReceiptRejected(409, "tenant evidence integrity unavailable")

    matched = {"provenance.runtime": [], "decision.candidate": [],
               "human.approval": [], "verification.vantage_policy": []}
    run_event_count = 0
    for row in records:
        try:
            payload = json.loads(row["payload_json"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ReceiptRejected(409, "malformed evidence payload") from exc
        if not isinstance(payload, dict) or payload.get("run_id") != run_id:
            continue
        run_event_count += 1
        record_type = row.get("record_type")
        if record_type in matched:
            if not trusted_record(row):
                raise ReceiptRejected(409, "untrusted privileged operation record")
            matched[record_type].append((row, payload))

    if not matched["decision.candidate"]:
        raise ReceiptRejected(404, "operation not found")
    if len(matched["decision.candidate"]) != 1 or len(matched["provenance.runtime"]) != 1:
        raise ReceiptRejected(409, "ambiguous operation provenance")
    if len(matched["human.approval"]) > 1:
        raise ReceiptRejected(409, "duplicate operation review")

    candidate_row, candidate = matched["decision.candidate"][0]
    _, provenance = matched["provenance.runtime"][0]
    requester_id = candidate.get("requester_id")
    if (not isinstance(requester_id, str) or not requester_id
            or provenance.get("requester_id") != requester_id):
        raise ReceiptRejected(409, "requester identity mismatch")

    fields = candidate.get("status_fields")
    if not isinstance(fields, dict):
        raise ReceiptRejected(409, "invalid candidate status fields")
    canonical = {field: fields.get(field) for field in STATUS_FIELDS}
    declared_policy = NinaIgorChain.derive_status(canonical)
    if fields.get("EXECUTION_ALLOWED") != declared_policy:
        raise ReceiptRejected(409, "inconsistent stored execution decision")

    vantage = {"status": "NOT_CONNECTED",
               "reason": "external Vantage receipt not integrated"}
    policy_events = matched["verification.vantage_policy"]
    if len(policy_events) > 1:
        raise ReceiptRejected(409, "ambiguous Vantage policy evidence")
    if policy_events:
        _, policy = policy_events[0]
        if (policy.get("requester_id") != requester_id
                or policy.get("task_sha256")
                   != __import__("hashlib").sha256(provenance.get("task", "").encode()).hexdigest()):
            raise ReceiptRejected(409, "Vantage policy and NINA task binding mismatch")
        if policy.get("status") == "SIGNED_RECEIPT_VERIFIED":
            envelope = policy.get("envelope")
            receipt = envelope.get("receipt") if isinstance(envelope, dict) else None
            if not isinstance(receipt, dict):
                raise ReceiptRejected(409, "missing Vantage signed decision")
            try:
                verified = verify_signed_envelope(
                    envelope, tenant_id=tenant_id, operation_id=run_id,
                    action="safe_expression",
                    task_sha256=policy["task_sha256"],
                    request_nonce=receipt.get("request_nonce"),
                    expected_commit=__import__("os").getenv(
                        "OLA_VANTAGE_EXPECTED_SOURCE_COMMIT", ""),
                    historical=True,
                )
            except VantagePolicyError as exc:
                raise ReceiptRejected(409, "Vantage signed decision no longer verifiable") from exc
            vantage = {
                "status": "SIGNED_RECEIPT_VERIFIED_HISTORICALLY",
                "verdict": verified["verdict"],
                "signer_key_id": verified["signer_key_id"],
                "source_commit": verified["source_commit"],
                "expires_at": verified["expires_at"],
                "trust_scope": "signed_heuristic_policy_only",
                "production_authorized": False,
            }
        else:
            raise ReceiptRejected(409, "Vantage policy blocked local operation")

    approval = None
    if matched["human.approval"]:
        _, approval = matched["human.approval"][0]
        if (approval.get("requester_id") != requester_id
                or not approval.get("approver_id")
                or approval["approver_id"] == requester_id
                or approval.get("tip_hash") != candidate_row["record_hash"]
                or approval.get("status") != "VERIFIED"
                or approval.get("production_authorized") is not False):
            raise ReceiptRejected(409, "invalid local approval evidence")

    source_valid = (
        isinstance(expected_commit, str)
        and bool(SOURCE_COMMIT.fullmatch(expected_commit))
        and provenance.get("commit") == expected_commit
    )
    invocation = provenance.get("invocation_type")
    expected_provider = provenance.get("provider") if invocation == "real_llm" else None
    expected_model = provenance.get("model") if invocation == "real_llm" else None
    igor = IgorVerifier().verify_records(
        records,
        expected_commit=expected_commit,
        expected_task=provenance.get("task"),
        expected_result=provenance.get("result"),
        expected_provider=expected_provider,
        expected_model=expected_model,
        expected_run_id=run_id,
    )
    replay = verify_replay(
        records,
        expected_run_id=run_id, expected_tenant_id=tenant_id,
        expected_record_count=len(records), expected_tip_hash=records[-1]["record_hash"],
    )
    local_verified = (
        source_valid and igor.status == "VERIFIED"
        and replay["status"] == "VERIFIED"
        and fields.get("EXECUTION_ALLOWED") == "REVIEW"
        and canonical["HUMAN_GATE"] == "REVIEW"
    )

    if not local_verified:
        status = "BLOCKED"
    elif approval is not None:
        status = "APPROVED_FOR_REVIEW_ONLY"
    else:
        status = "REVIEW_REQUIRED"

    return {
        "schema": "ola.operation.v1",
        "operation_id": run_id,
        "correlation_id": run_id,
        "tenant_id": tenant_id,
        "actor": {"kind": "user", "subject_id": requester_id},
        "source_commit": provenance.get("commit"),
        "status": status,
        "verified": False,
        "system_acceptance": "NOT_VERIFIED",
        "production_authorized": False,
        "trust_scope": "local_ledger_consistency_only",
        "reviewer_id": approval.get("approver_id") if approval else None,
        "stages": {
            "operator": {"status": "AUTHENTICATED_API_KEY", "identity_scope": "tenant_api_key"},
            "nina": {"status": "RECORDED" if local_verified else "BLOCKED",
                     "policy_decision": declared_policy},
            "vantage": vantage,
            "execution": {"status": "RECORDED" if local_verified else "BLOCKED",
                          "mode": invocation,
                          "result_kind": "runtime_recorded_not_externally_attested"},
            "igor": {"status": "VERIFIED_LOCAL_EVIDENCE" if local_verified else "BLOCKED",
                     "checks": igor.checks},
            "replay": {"status": replay["status"]},
            "evidence_vault": {"status": "VERIFIED_LOCAL_CHAIN", "complete_tenant_chain": True},
            "human_gate": {"status": "APPROVED_FOR_REVIEW_ONLY" if approval
                           else "REVIEW_REQUIRED"},
        },
        "evidence": {
            "candidate_record_id": candidate_row.get("id"),
            "candidate_tip": candidate_row["record_hash"],
            "chain_tip": records[-1]["record_hash"],
            "tenant_event_count": len(records),
            "run_event_count": run_event_count,
            "chain_algorithm": "OLA-EVIDENCE-CHAIN-V2-SHA256",
        },
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
