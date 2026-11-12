from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from scripts.verify_pack import ROOT, canonical_json, sha256, validate_bundle

CONTROL_STATES = {"PASS", "FAIL", "PARTIAL", "BLOCKED", "UNKNOWN", "SKIPPED", "NOT_APPLICABLE"}
INTEGRITY_STATES = {"VERIFIED", "INVALID", "UNVERIFIED"}
APPROVAL_STATES = {"APPROVED", "PENDING", "REJECTED"}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def build_manifest(bundle: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic Evidence Manifest without upgrading unverified claims."""
    if not isinstance(bundle, dict):
        raise ValueError("bundle must be a JSON object")

    validation = validate_bundle(bundle)
    raw_release = _object(bundle.get("release"))
    raw_verdicts = bundle.get("control_verdicts", [])
    verdicts = raw_verdicts if isinstance(raw_verdicts, list) else []
    verdict_by_id = {
        item.get("control_id"): item
        for item in verdicts
        if isinstance(item, dict) and isinstance(item.get("control_id"), str)
    }
    catalogue = yaml.safe_load((ROOT / "controls/dora/ict-change-management.yaml").read_text(encoding="utf-8"))
    raw_evidence = bundle.get("evidence", [])
    evidence = raw_evidence if isinstance(raw_evidence, list) else []
    evidence_by_id: dict[str, dict] = {}
    evidence_refs: list[dict[str, Any]] = []

    for item in evidence:
        if not isinstance(item, dict):
            continue
        eid = _text(item.get("evidence_id"))
        if eid:
            evidence_by_id[eid] = item
        source = _object(item.get("source"))
        payload = _object(item.get("payload"))
        payload_digest = _text(item.get("payload_digest"))
        digest_status = "VERIFIED" if payload_digest == sha256(canonical_json(payload)) else "INVALID"
        binding = _object(item.get("binding"))
        evidence_refs.append({
            "evidence_id": eid,
            "tenant_id": _text(item.get("tenant_id")),
            "control_id": _text(item.get("control_id")),
            "evidence_type": _text(item.get("evidence_type")),
            "source_system": _text(source.get("system")),
            "source_record_id": _text(source.get("record_id")),
            "source_uri": _text(source.get("uri")),
            "captured_at": _text(item.get("captured_at")),
            "payload_digest": payload_digest,
            "payload_digest_status": digest_status,
            "binding": {
                "repository": _text(binding.get("repository")),
                "change_id": _text(binding.get("change_id")),
                "commit_sha": _text(binding.get("commit_sha")),
                "artifact_digest": _text(binding.get("artifact_digest")),
            },
        })
    evidence_refs.sort(key=lambda x: (str(x.get("control_id")), str(x.get("evidence_id"))))

    controls: list[dict[str, Any]] = []
    for control in catalogue["controls"]:
        cid = control["id"]
        required_types = sorted(item["id"] for item in control["required_evidence"])
        verdict = verdict_by_id.get(cid, {})
        raw_status = verdict.get("status", "UNKNOWN")
        reported_status = raw_status if raw_status in CONTROL_STATES else "UNKNOWN"
        integrity = verdict.get("evidence_integrity", "UNVERIFIED")
        evidence_integrity = integrity if integrity in INTEGRITY_STATES else "UNVERIFIED"
        approval = verdict.get("approval_status", "PENDING")
        approval_status = approval if approval in APPROVAL_STATES else "PENDING"

        raw_ids = verdict.get("evidence_ids", [])
        evidence_ids = sorted(set(x for x in raw_ids if isinstance(x, str))) if isinstance(raw_ids, list) else []
        linked_records = [
            evidence_by_id[eid]
            for eid in evidence_ids
            if eid in evidence_by_id and evidence_by_id[eid].get("control_id") == cid
        ]
        observed_types = {item.get("evidence_type") for item in linked_records}
        missing_types = sorted(set(required_types) - observed_types)

        # Never present an asserted PASS as verified when any contract-level error exists.
        effective_status = (
            "BLOCKED"
            if reported_status == "PASS" and not validation["valid_contract"]
            else reported_status
        )
        reason = _text(verdict.get("reason")) or ""
        if reported_status == "PASS" and effective_status == "BLOCKED":
            reason = "Submitted PASS could not be verified because the evidence bundle violates the pack contract."
        elif not verdict:
            reason = "No control verdict supplied."

        reviewer = _object(verdict.get("reviewer"))
        controls.append({
            "control_id": cid,
            "status": effective_status,
            "reported_status": reported_status,
            "evidence_integrity": evidence_integrity,
            "approval_status": approval_status,
            "required_evidence_types": required_types,
            "missing_evidence_types": missing_types,
            "evidence_ids": evidence_ids,
            "reason": reason,
            "reviewer": {
                "identity": _text(reviewer.get("identity")),
                "role": _text(reviewer.get("role")),
                "approved_at": _text(reviewer.get("approved_at")),
            },
        })

    manifest = {
        "schema_version": "ola.evidence-manifest.v0.1",
        "pack": {
            "id": _text(bundle.get("pack_id")),
            "version": _text(bundle.get("pack_version")),
            "status": "DRAFT",
        },
        "evaluation": {
            "status": validation["status"],
            "valid_contract": validation["valid_contract"],
            "ready": validation["ready"],
            "scope": validation["evaluation_scope"],
            "policy": validation["policy"],
            "errors": validation["errors"],
        },
        "source_binding": {
            "tenant_id": _text(bundle.get("tenant_id")),
            "repository": _text(raw_release.get("repository")),
            "change_id": _text(raw_release.get("change_id")),
            "commit_sha": _text(raw_release.get("commit_sha")),
            "artifact_digest": _text(raw_release.get("artifact_digest")),
            "input_bundle_digest": sha256(canonical_json(bundle)),
        },
        "summary": {
            "required_controls": validation["required_controls"],
            "control_verdicts_received": validation["control_verdicts_received"],
            "evidence_records": validation["evidence_records"],
            "control_state_counts": validation["state_counts"],
        },
        "controls": controls,
        "evidence_references": evidence_refs,
        "attestation": {
            "customer_manifest_status": "NOT_IMPLEMENTED_IN_V0.1",
            "pack_archive_attestation": "SEPARATE_BUILD_PROVENANCE_ONLY",
        },
        "limitations": [
            "This manifest evaluates the supplied bundle against the pack contract only.",
            "It is not a legal opinion, certification, full DORA compliance assessment or guarantee of auditor acceptance.",
            "A digest proves byte consistency, not source truth, collection authority or role independence.",
            "Human review and authoritative customer records remain necessary.",
            "Customer Evidence Manifest signing/attestation is not implemented in v0.1.",
            "SKIPPED and NOT_APPLICABLE are never PASS; UNKNOWN is never promoted.",
        ],
    }
    manifest["manifest_digest"] = sha256(canonical_json(manifest))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a source-bound OLA Evidence Manifest")
    parser.add_argument("bundle", type=Path, help="Input JSON evidence bundle")
    parser.add_argument("--output", type=Path, required=True, help="Output manifest JSON path")
    args = parser.parse_args()
    try:
        bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
        manifest = build_manifest(bundle)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({
        "manifest": str(args.output),
        "status": manifest["evaluation"]["status"],
        "ready": manifest["evaluation"]["ready"],
        "digest": manifest["manifest_digest"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
