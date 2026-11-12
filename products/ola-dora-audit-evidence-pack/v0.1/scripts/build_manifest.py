from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any

import yaml
from scripts.verify_pack import ROOT, canonical_json, sha256, validate_bundle


def build_manifest(bundle: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic, source-bound manifest; never upgrades a non-pass."""
    validation = validate_bundle(bundle)
    release = bundle.get("release", {}) if isinstance(bundle, dict) else {}
    verdicts = bundle.get("control_verdicts", []) if isinstance(bundle, dict) else []
    verdict_by_id = {
        item.get("control_id"): item
        for item in verdicts
        if isinstance(item, dict) and isinstance(item.get("control_id"), str)
    }
    catalogue = yaml.safe_load((ROOT / "controls/dora/ict-change-management.yaml").read_text(encoding="utf-8"))
    evidence = bundle.get("evidence", []) if isinstance(bundle, dict) else []
    evidence_refs = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
        evidence_refs.append({
            "evidence_id": item.get("evidence_id"),
            "tenant_id": item.get("tenant_id"),
            "control_id": item.get("control_id"),
            "evidence_type": item.get("evidence_type"),
            "source_system": source.get("system"),
            "source_record_id": source.get("record_id"),
            "source_uri": source.get("uri"),
            "captured_at": item.get("captured_at"),
            "payload_digest": item.get("payload_digest"),
            "binding": item.get("binding", {}),
        })
    evidence_refs.sort(key=lambda x: (str(x.get("control_id")), str(x.get("evidence_id"))))

    controls = []
    for control in catalogue["controls"]:
        cid = control["id"]
        verdict = verdict_by_id.get(cid, {})
        controls.append({
            "control_id": cid,
            "status": verdict.get("status", "UNKNOWN"),
            "evidence_integrity": verdict.get("evidence_integrity", "UNVERIFIED"),
            "approval_status": verdict.get("approval_status", "PENDING"),
            "evidence_ids": sorted(verdict.get("evidence_ids", [])) if isinstance(verdict.get("evidence_ids"), list) and all(isinstance(x, str) for x in verdict.get("evidence_ids", [])) else [],
            "reason": verdict.get("reason", "No control verdict supplied.") if not verdict else verdict.get("reason", ""),
            "reviewer": verdict.get("reviewer", {}) if isinstance(verdict.get("reviewer", {}), dict) else {},
        })

    manifest = {
        "schema_version": "ola.evidence-manifest.v0.1",
        "pack": {
            "id": bundle.get("pack_id"),
            "version": bundle.get("pack_version"),
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
            "tenant_id": bundle.get("tenant_id"),
            "repository": release.get("repository"),
            "change_id": release.get("change_id"),
            "commit_sha": release.get("commit_sha"),
            "artifact_digest": release.get("artifact_digest"),
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
        "limitations": [
            "This manifest evaluates the supplied bundle against the pack contract only.",
            "It is not a legal opinion, certification, full DORA compliance assessment or guarantee of auditor acceptance.",
            "A digest proves byte consistency, not source truth, collection authority or role independence.",
            "Human review and authoritative customer records remain necessary.",
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
