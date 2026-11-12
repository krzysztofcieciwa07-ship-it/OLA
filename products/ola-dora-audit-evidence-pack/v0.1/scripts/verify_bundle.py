#!/usr/bin/env python3
"""Fail-closed validator and SHA-256-bound Evidence Manifest generator."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "controls" / "controls.json"
CONTROL_STATES = {"PASS", "FAIL", "PARTIAL", "BLOCKED", "UNKNOWN", "SKIPPED", "NOT_APPLICABLE"}
INTEGRITY_STATES = {"VERIFIED", "INVALID", "UNVERIFIED"}
APPROVAL_STATES = {"APPROVED", "PENDING", "REJECTED"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_catalogue(path: Path = CATALOGUE) -> dict[str, dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    controls = document.get("controls")
    if not isinstance(controls, list) or not controls:
        raise ValueError("control catalogue must contain a non-empty controls array")
    result = {}
    for control in controls:
        control_id = control.get("id")
        if not isinstance(control_id, str) or control_id in result:
            raise ValueError("control catalogue contains a missing or duplicate id")
        if not isinstance(control.get("required_evidence"), list):
            raise ValueError(f"{control_id}: required_evidence must be an array")
        result[control_id] = control
    return result


def validate_bundle(bundle: dict[str, Any], catalogue: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    catalogue = catalogue or load_catalogue()
    required = ("repository", "change_id", "commit_sha", "artifact_digest", "controls")
    missing_root = [key for key in required if key not in bundle]
    if missing_root:
        raise ValueError("missing bundle fields: " + ", ".join(missing_root))
    if not isinstance(bundle["repository"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", bundle["repository"]):
        raise ValueError("repository must be owner/name")
    if not isinstance(bundle["change_id"], str) or not bundle["change_id"].strip():
        raise ValueError("change_id must be a non-empty string")
    if not isinstance(bundle["commit_sha"], str) or not SHA_RE.fullmatch(bundle["commit_sha"]):
        raise ValueError("commit_sha must be the exact 40-character lowercase Git SHA")
    if not isinstance(bundle["artifact_digest"], str) or not DIGEST_RE.fullmatch(bundle["artifact_digest"]):
        raise ValueError("artifact_digest must be sha256:<64 lowercase hex>")
    supplied = bundle["controls"]
    if not isinstance(supplied, list):
        raise ValueError("controls must be an array")
    by_id = {}
    for item in supplied:
        if not isinstance(item, dict) or not isinstance(item.get("control_id"), str):
            raise ValueError("each control entry must have a control_id")
        cid = item["control_id"]
        if cid not in catalogue:
            raise ValueError(f"unknown control_id: {cid}")
        if cid in by_id:
            raise ValueError(f"duplicate control_id: {cid}")
        by_id[cid] = item

    results = []
    counts = {state: 0 for state in sorted(CONTROL_STATES)}
    integrity_counts = {state: 0 for state in sorted(INTEGRITY_STATES)}
    approval_counts = {state: 0 for state in sorted(APPROVAL_STATES)}

    for cid, control in catalogue.items():
        item = by_id.get(cid)
        if item is None:
            status, integrity, approval = "UNKNOWN", "UNVERIFIED", "PENDING"
            evidence, missing_evidence, issues = [], list(control["required_evidence"]), ["control result missing"]
        else:
            status = item.get("status", "UNKNOWN")
            if status not in CONTROL_STATES:
                status = "BLOCKED"
            approval = item.get("approval_status", "PENDING")
            if approval not in APPROVAL_STATES:
                approval = "REJECTED"
            evidence = item.get("evidence", [])
            if not isinstance(evidence, list):
                evidence = []
            evidence_types = {e.get("type") for e in evidence if isinstance(e, dict)}
            missing_evidence = sorted(set(control["required_evidence"]) - evidence_types)
            issues = []
            invalid_digest = False
            for record in evidence:
                if not isinstance(record, dict) or not isinstance(record.get("type"), str) or "payload" not in record:
                    invalid_digest = True
                    issues.append("malformed evidence record")
                    continue
                if record.get("sha256") != canonical_digest(record["payload"]):
                    invalid_digest = True
                    issues.append("evidence payload digest mismatch: " + record["type"])
            if invalid_digest:
                integrity = "INVALID"
                status = "FAIL" if status == "PASS" else status
            elif missing_evidence:
                integrity = "UNVERIFIED"
                if status == "PASS":
                    status = "PARTIAL"
                issues.append("required evidence missing")
            else:
                integrity = "VERIFIED" if evidence else "UNVERIFIED"
            if status == "PASS" and approval != "APPROVED":
                status = "PARTIAL"
                issues.append("approval is not APPROVED")
            if status == "SKIPPED" and not isinstance(item.get("exception_reason"), str):
                issues.append("SKIPPED has no recorded exception reason")
        counts[status] += 1
        integrity_counts[integrity] += 1
        approval_counts[approval] += 1
        results.append({
            "control_id": cid,
            "title": control["title"],
            "status": status,
            "evidence_integrity": integrity,
            "approval_status": approval,
            "evidence": [{"type": e.get("type"), "sha256": e.get("sha256")} for e in evidence if isinstance(e, dict)],
            "missing_evidence": missing_evidence,
            "issues": issues
        })

    ready = all(r["status"] == "PASS" and r["evidence_integrity"] == "VERIFIED" and r["approval_status"] == "APPROVED" for r in results)
    manifest = {
        "schema": "ola-evidence-manifest-v0.1",
        "pack_version": "0.1.0-draft",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "repository": bundle["repository"],
            "change_id": bundle["change_id"],
            "commit_sha": bundle["commit_sha"],
            "artifact_digest": bundle["artifact_digest"]
        },
        "controls": results,
        "summary": {
            "status": "READY" if ready else "NOT_READY",
            "control_counts": counts,
            "evidence_integrity_counts": integrity_counts,
            "approval_counts": approval_counts
        },
        "attestation": {"status": "NOT_ISSUED", "note": "manifest digest is not a digital signature"}
    }
    manifest["manifest_digest"] = canonical_digest(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path, default=Path("evidence-manifest.json"))
    args = parser.parse_args()
    try:
        bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
        if bundle.get("schema") != "ola-evidence-bundle-v0.1":
            raise ValueError("unsupported evidence bundle schema")
        manifest = validate_bundle(bundle)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(manifest["summary"], indent=2))
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"INVALID_BUNDLE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
