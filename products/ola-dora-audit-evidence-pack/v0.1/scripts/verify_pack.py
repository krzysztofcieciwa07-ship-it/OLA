from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
HEX40 = re.compile(r"^[a-f0-9]{40}$")
SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def validate_bundle(bundle: dict) -> dict:
    errors: list[str] = []
    catalogue = yaml.safe_load((ROOT / "controls/dora/ict-change-management.yaml").read_text(encoding="utf-8"))
    controls = catalogue["controls"]
    required = {c["id"]: {e["id"] for e in c["required_evidence"]} for c in controls}
    source_types = {c["id"]: {e["id"]: set(e["source_types"]) for e in c["required_evidence"]} for c in controls}
    ev_schema = json.loads((ROOT / "schemas/evidence.schema.json").read_text(encoding="utf-8"))
    vd_schema = json.loads((ROOT / "schemas/control-verdict.schema.json").read_text(encoding="utf-8"))
    ev_validator = Draft202012Validator(ev_schema, format_checker=FormatChecker())
    vd_validator = Draft202012Validator(vd_schema, format_checker=FormatChecker())

    if not isinstance(bundle, dict):
        raise ValueError("bundle must be a JSON object")
    if bundle.get("schema_version") != "ola.dora.audit-bundle.v0.1":
        errors.append("unsupported bundle schema_version")
    if bundle.get("pack_id") != catalogue["pack_id"] or bundle.get("pack_version") != catalogue["pack_version"]:
        errors.append("pack identity/version mismatch")
    tenant = bundle.get("tenant_id")
    if not isinstance(tenant, str) or not tenant.strip():
        errors.append("tenant_id is required")
    release = bundle.get("release") if isinstance(bundle.get("release"), dict) else {}
    repository, change_id = release.get("repository"), release.get("change_id")
    commit_sha, artifact_digest = release.get("commit_sha"), release.get("artifact_digest")
    if not isinstance(repository, str) or not repository.strip():
        errors.append("release.repository is required")
    if not isinstance(change_id, str) or not change_id.strip():
        errors.append("release.change_id is required")
    if not isinstance(commit_sha, str) or not HEX40.fullmatch(commit_sha):
        errors.append("release.commit_sha must be a full 40-character lowercase SHA")
    if not isinstance(artifact_digest, str) or not SHA256.fullmatch(artifact_digest):
        errors.append("release.artifact_digest must be sha256:<64 lowercase hex>")

    evidence = bundle.get("evidence", [])
    if not isinstance(evidence, list):
        errors.append("evidence must be an array")
        evidence = []
    evidence_by_id, integrity = {}, {}
    for index, record in enumerate(evidence):
        if not isinstance(record, dict):
            errors.append(f"evidence[{index}] must be an object")
            continue
        for issue in ev_validator.iter_errors(record):
            errors.append(f"evidence[{index}] schema: {issue.message}")
        eid = record.get("evidence_id")
        if not isinstance(eid, str) or not eid:
            continue
        if eid in evidence_by_id:
            errors.append(f"duplicate evidence_id: {eid}")
            continue
        evidence_by_id[eid] = record
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        integrity[eid] = "VERIFIED" if record.get("payload_digest") == sha256(canonical_json(payload)) else "INVALID"
        if integrity[eid] != "VERIFIED":
            errors.append(f"evidence {eid}: payload_digest mismatch; evidence integrity is INVALID")
        if record.get("tenant_id") != tenant:
            errors.append(f"evidence {eid}: tenant_id mismatch")
        binding = record.get("binding", {})
        for field, expected in (("repository", repository), ("change_id", change_id),
                                ("commit_sha", commit_sha), ("artifact_digest", artifact_digest)):
            if binding.get(field) != expected:
                errors.append(f"evidence {eid}: {field} binding mismatch")
        cid, etype = record.get("control_id"), record.get("evidence_type")
        if cid not in required or etype not in required[cid]:
            errors.append(f"evidence {eid}: unknown control/evidence type")
        else:
            allowed = source_types[cid][etype]
            observed_source = record.get("source", {}).get("system")
            if observed_source not in allowed:
                errors.append(f"evidence {eid}: source.system is not allowed for {cid}/{etype}")

    verdicts = bundle.get("control_verdicts", [])
    if not isinstance(verdicts, list):
        errors.append("control_verdicts must be an array")
        verdicts = []
    verdict_by_id = {}
    for index, verdict in enumerate(verdicts):
        if not isinstance(verdict, dict):
            errors.append(f"control_verdicts[{index}] must be an object")
            continue
        for issue in vd_validator.iter_errors(verdict):
            errors.append(f"control_verdicts[{index}] schema: {issue.message}")
        cid = verdict.get("control_id")
        if cid not in required:
            errors.append(f"unknown control_id: {cid}")
            continue
        if cid in verdict_by_id:
            errors.append(f"duplicate control verdict: {cid}")
            continue
        verdict_by_id[cid] = verdict
        binding = verdict.get("binding", {})
        for field, expected in (("repository", repository), ("change_id", change_id),
                                ("commit_sha", commit_sha), ("artifact_digest", artifact_digest)):
            if binding.get(field) != expected:
                errors.append(f"{cid}: {field} binding mismatch")
        ids = verdict.get("evidence_ids", [])
        if not isinstance(ids, list):
            errors.append(f"{cid}: evidence_ids must be an array")
            ids = []
        records = []
        for eid in ids:
            record = evidence_by_id.get(eid)
            if record is None:
                errors.append(f"{cid}: referenced evidence {eid} is missing")
                continue
            if record.get("control_id") != cid:
                errors.append(f"{cid}: evidence {eid} belongs to another control")
                continue
            records.append(record)
        observed = "VERIFIED" if records and len(records) == len(ids) and all(integrity.get(r["evidence_id"]) == "VERIFIED" for r in records) else "INVALID" if any(integrity.get(r.get("evidence_id")) == "INVALID" for r in records) else "UNVERIFIED"
        if verdict.get("evidence_integrity") != observed:
            errors.append(f"{cid}: evidence_integrity must be {observed}")
        status = verdict.get("status")
        if status == "PASS":
            missing_types = sorted(required[cid] - {r.get("evidence_type") for r in records})
            if missing_types:
                errors.append(f"{cid}: PASS missing required evidence types: {', '.join(missing_types)}")
            if observed != "VERIFIED":
                errors.append(f"{cid}: PASS requires verified digests")
            if verdict.get("approval_status") != "APPROVED":
                errors.append(f"{cid}: PASS requires APPROVED")
            if not verdict.get("reviewer", {}).get("identity") or not verdict.get("reviewer", {}).get("role"):
                errors.append(f"{cid}: PASS requires reviewer identity and role")
        elif status == "SKIPPED":
            if not verdict.get("reason") or verdict.get("approval_status") != "APPROVED":
                errors.append(f"{cid}: SKIPPED requires reason and approved exception; it never passes")
        elif status == "NOT_APPLICABLE":
            if not verdict.get("reason") or verdict.get("approval_status") != "APPROVED":
                errors.append(f"{cid}: NOT_APPLICABLE requires reason and approval; it never passes")

    missing = sorted(set(required) - set(verdict_by_id))
    if missing:
        errors.append("missing control verdicts: " + ", ".join(missing))
    states = ["PASS", "FAIL", "PARTIAL", "BLOCKED", "UNKNOWN", "SKIPPED", "NOT_APPLICABLE"]
    all_pass = len(verdict_by_id) == len(required) and all(
        verdict_by_id.get(cid, {}).get("status") == "PASS"
        and verdict_by_id.get(cid, {}).get("evidence_integrity") == "VERIFIED"
        and verdict_by_id.get(cid, {}).get("approval_status") == "APPROVED"
        for cid in required
    )
    return {
        "valid_contract": not errors,
        "ready": not errors and all_pass,
        "status": "READY" if not errors and all_pass else "NOT_READY",
        "evaluation_scope": "local bundle contract only; not legal compliance or auditor acceptance",
        "required_controls": len(required),
        "control_verdicts_received": len(verdict_by_id),
        "evidence_records": len(evidence_by_id),
        "state_counts": {s: sum(1 for v in verdict_by_id.values() if v.get("status") == s) for s in states},
        "errors": errors,
        "policy": "SKIPPED != PASS; NOT_APPLICABLE != PASS; UNKNOWN never promoted",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an OLA DORA evidence bundle")
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        result = validate_bundle(json.loads(args.bundle.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid_contract"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
