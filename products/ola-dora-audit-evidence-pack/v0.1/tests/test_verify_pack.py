import copy
import json
import subprocess
import sys
import zipfile
import yaml
from jsonschema import Draft202012Validator
from scripts.build_manifest import build_manifest
from scripts.verify_pack import ROOT, canonical_json, sha256, validate_bundle
from scripts.build_pack import build_archive

BASE = json.loads((ROOT / "examples/unverified-demo-bundle.json").read_text(encoding="utf-8"))
CATALOGUE = yaml.safe_load((ROOT / "controls/dora/ict-change-management.yaml").read_text(encoding="utf-8"))


def valid_bundle():
    bundle = copy.deepcopy(BASE)
    release = bundle["release"]
    evidence, verdicts = [], []
    for control in CATALOGUE["controls"]:
        cid, ids = control["id"], []
        for i, item in enumerate(control["required_evidence"]):
            payload = {"fixture": True, "control_id": cid, "evidence_type": item["id"]}
            eid = f"fixture-{cid.lower()}-{i}"
            ids.append(eid)
            evidence.append({
                "schema_version":"ola.evidence.v0.1","evidence_id":eid,"control_id":cid,
                "evidence_type":item["id"],"tenant_id":bundle["tenant_id"],
                "source":{"system":item["source_types"][0],"record_id":eid,"uri":"https://example.invalid/fixture"},
                "collector":{"id":"test-fixture","version":"0.1.0"},
                "captured_at":"2026-11-12T12:00:00Z","payload":payload,
                "payload_digest":sha256(canonical_json(payload)),
                "binding":{"repository":release["repository"],"change_id":release["change_id"],"commit_sha":release["commit_sha"],"artifact_digest":release["artifact_digest"]}
            })
        verdicts.append({
            "control_id":cid,"status":"PASS","evidence_integrity":"VERIFIED","approval_status":"APPROVED",
            "evidence_ids":ids,
            "binding":{"repository":release["repository"],"change_id":release["change_id"],"commit_sha":release["commit_sha"],"artifact_digest":release["artifact_digest"]},
            "reason":"Synthetic fixture only; not customer evidence.",
            "reviewer":{"identity":"fixture-reviewer","role":"test","approved_at":"2026-11-12T12:01:00Z"}
        })
    bundle["evidence"], bundle["control_verdicts"] = evidence, verdicts
    return bundle


def test_demo_builds_schema_valid_not_ready_evidence_manifest():
    manifest = build_manifest(copy.deepcopy(BASE))
    schema = json.loads((ROOT / "schemas/evidence-manifest.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(manifest)
    assert manifest["schema_version"] == "ola.evidence-manifest.v0.1"
    assert manifest["evaluation"]["status"] == "NOT_READY"
    assert manifest["evaluation"]["ready"] is False
    assert manifest["summary"]["control_state_counts"]["UNKNOWN"] == 13
    assert manifest["summary"]["evidence_records"] == 0
    expected = sha256(canonical_json({k: v for k, v in manifest.items() if k != "manifest_digest"}))
    assert manifest["manifest_digest"] == expected


def test_complete_fixture_builds_ready_manifest_but_remains_synthetic():
    manifest = build_manifest(valid_bundle())
    schema = json.loads((ROOT / "schemas/evidence-manifest.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(manifest)
    assert manifest["evaluation"]["status"] == "READY"
    assert manifest["evaluation"]["ready"] is True
    assert manifest["summary"]["required_controls"] == 13
    assert manifest["summary"]["evidence_records"] > 0
    assert "not a legal opinion" in " ".join(manifest["limitations"]).lower()


def test_manifest_build_is_deterministic():
    first = build_manifest(copy.deepcopy(BASE))
    second = build_manifest(copy.deepcopy(BASE))
    assert first == second


def test_demo_is_valid_but_not_ready():
    result = validate_bundle(copy.deepcopy(BASE))
    assert result["valid_contract"] and not result["ready"]
    assert result["required_controls"] == 13
    assert result["state_counts"]["UNKNOWN"] == 13


def test_complete_synthetic_bundle_satisfies_only_local_contract():
    result = validate_bundle(valid_bundle())
    assert result["valid_contract"] and result["ready"]


def test_skipped_never_passes_even_with_approved_exception():
    bundle = valid_bundle()
    bundle["control_verdicts"][0]["status"] = "SKIPPED"
    assert not validate_bundle(bundle)["ready"]


def test_not_applicable_never_passes():
    bundle = valid_bundle()
    bundle["control_verdicts"][0]["status"] = "NOT_APPLICABLE"
    assert not validate_bundle(bundle)["ready"]


def test_tampered_payload_digest_blocks_pass():
    bundle = valid_bundle()
    bundle["evidence"][0]["payload"]["tampered"] = True
    result = validate_bundle(bundle)
    assert not result["ready"]
    assert any("evidence_integrity" in e or "verified digests" in e for e in result["errors"])


def test_orphaned_tampered_evidence_blocks_entire_bundle():
    bundle = valid_bundle()
    bundle["evidence"].append(copy.deepcopy(bundle["evidence"][0]))
    bundle["evidence"][-1]["evidence_id"] = "orphaned-tampered-record"
    bundle["evidence"][-1]["payload"]["tampered"] = True
    result = validate_bundle(bundle)
    assert not result["valid_contract"]
    assert any("payload_digest mismatch" in error for error in result["errors"])


def test_unapproved_source_type_blocks_evidence():
    bundle = valid_bundle()
    bundle["evidence"][0]["source"]["system"] = "unapproved_connector"
    result = validate_bundle(bundle)
    assert not result["ready"]
    assert any("source.system is not allowed" in error for error in result["errors"])


def test_commit_binding_mismatch_blocks_pass():
    bundle = valid_bundle()
    bundle["evidence"][0]["binding"]["commit_sha"] = "2" * 40
    result = validate_bundle(bundle)
    assert not result["ready"]
    assert any("commit_sha binding mismatch" in e for e in result["errors"])


def test_missing_required_evidence_type_blocks_pass():
    bundle = valid_bundle()
    bundle["control_verdicts"][0]["evidence_ids"].pop()
    result = validate_bundle(bundle)
    assert not result["ready"]
    assert any("missing required evidence types" in e for e in result["errors"])


def test_tenant_mismatch_blocks():
    bundle = valid_bundle()
    bundle["evidence"][0]["tenant_id"] = "other-tenant"
    result = validate_bundle(bundle)
    assert not result["ready"]
    assert any("tenant_id mismatch" in e for e in result["errors"])


def test_cross_control_evidence_reference_blocks_pass():
    bundle = valid_bundle()
    bundle["control_verdicts"][0]["evidence_ids"][0] = bundle["control_verdicts"][1]["evidence_ids"][0]
    assert not validate_bundle(bundle)["ready"]


def test_duplicate_control_verdict_invalidates_contract():
    bundle = valid_bundle()
    bundle["control_verdicts"].append(copy.deepcopy(bundle["control_verdicts"][0]))
    assert not validate_bundle(bundle)["valid_contract"]


def test_extracted_pack_runs_outside_repository_tree(tmp_path):
    archive = tmp_path / "consumer-pack.zip"
    extract_to = tmp_path / "independent-consumer"
    digest = build_archive(archive)
    assert len(digest) == 64
    with zipfile.ZipFile(archive) as package:
        package.extractall(extract_to)

    pack_root = extract_to / "ola-dora-audit-evidence-pack"
    validator = pack_root / "scripts" / "verify_pack.py"
    demo = pack_root / "examples" / "unverified-demo-bundle.json"
    completed = subprocess.run(
        [sys.executable, str(validator), str(demo)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    result = json.loads(completed.stdout)
    assert result["valid_contract"] is True
    assert result["ready"] is False
    assert result["required_controls"] == 13
    assert result["state_counts"]["UNKNOWN"] == 13


def test_deterministic_zip_excludes_cache_files(tmp_path):
    one, two = tmp_path / "one.zip", tmp_path / "two.zip"
    assert build_archive(one) == build_archive(two)
    import zipfile
    with zipfile.ZipFile(one) as archive:
        names = archive.namelist()
    assert names and not any("__pycache__" in n or ".pytest_cache" in n or n.endswith(".pyc") for n in names)
