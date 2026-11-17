from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tarfile
from pathlib import Path

from scripts.ola_watchdog_evidence import (
    IGOR_BUNDLE_FILES,
    NINA_FILES,
    verify_nested_artifact_copies,
    verify_nested_evidence,
)

SOURCE_SHA = "a" * 40
FLOW_RUN_ID = 321
NINA_DIGEST = "sha256:" + "1" * 64
RUN_ID = "nina-run-001"
TENANT_ID = "tenant-001"
MODEL = "qwen2.5:0.5b-instruct"
TASK = "Calculate 17 * 23 and return the exact verified result 391."
IMAGE_ID = "sha256:" + "a" * 64


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _manifest(base: Path, target: Path, names: set[str]) -> None:
    lines = []
    for name in sorted(names):
        lines.append(f"{hashlib.sha256((base / name).read_bytes()).hexdigest()}  {name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_nested(root: Path, source_sha: str = SOURCE_SHA) -> None:
    preflight = root / "downloaded" / "preflight"
    nina = root / "downloaded" / "ollama"
    igor = root / "downloaded" / "independent-igor"
    bundle = igor / "evidence-bundle"
    runtime = bundle / "runtime"

    preflight.mkdir(parents=True)
    (preflight / "source-provenance.txt").write_text(
        f"SOURCE_COMMIT={source_sha}\nSOURCE_BRANCH=main\nTRIGGER=schedule\nUTC=2026-11-17T00:00:00Z\n",
        encoding="utf-8",
    )
    (preflight / "nina-gate.log").write_text("................ [100%]\n", encoding="utf-8")
    (preflight / "igor-replay-gate.log").write_text("................ [100%]\n", encoding="utf-8")

    nina.mkdir(parents=True)
    db_path = nina / "nina-ollama-evidence.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TABLE evidence_records (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, "
            "seq INTEGER NOT NULL, record_type TEXT NOT NULL, payload_json TEXT NOT NULL, "
            "prev_hash TEXT NOT NULL, record_hash TEXT NOT NULL)"
        )
        for seq in range(6):
            db.execute(
                "INSERT INTO evidence_records VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"e{seq}", TENANT_ID, seq, f"agent.{seq}", "{}", "0" * 64, "1" * 64),
            )

    proof = {
        "commit": source_sha,
        "flow": ["NINA", "REAL_OLLAMA_LLM", "IGOR", "PROVENANCE", "REPLAY", "HUMAN_GATE"],
        "human_gate_status": "BLOCK",
        "igor_status": "VERIFIED",
        "llm_invocations": 6,
        "model": MODEL,
        "nina_status": "VERIFIED",
        "policy_status": "VERIFIED",
        "provenance_status": "VERIFIED",
        "provider": "ollama",
        "replay_status": "VERIFIED",
        "run_id": RUN_ID,
        "status": "REVIEW",
        "status_fields": {
            "EVIDENCE": "VERIFIED",
            "EXECUTION_ALLOWED": "REVIEW",
            "HUMAN_GATE": "REVIEW",
            "POLICY": "VERIFIED",
            "REPLAY_INTEGRITY": "VERIFIED",
            "RUNTIME": "VERIFIED",
        },
        "tenant_id": TENANT_ID,
    }
    context = {"run_id": RUN_ID, "tenant_id": TENANT_ID, "task": TASK}
    build = {"schema": "ola-build-info/v1", "source_commit": source_sha}
    models = {"models": [{"name": MODEL}]}
    provenance = (
        f"commit={source_sha}\nrun={FLOW_RUN_ID}\ntenant_id={TENANT_ID}\n"
        f"run_id={RUN_ID}\nprovider=ollama\nmodel={MODEL}\n"
    )
    _json(nina / "nina-igor-ollama-proof.json", proof)
    _json(nina / "nina-ollama-proof-context.json", context)
    _json(nina / "ola-build-info.json", build)
    _json(nina / "ollama-models.json", models)
    (nina / "provenance.txt").write_text(provenance, encoding="utf-8")
    (nina / "runtime-image-revision.txt").write_text(source_sha + "\n", encoding="utf-8")
    (nina / "runtime-image-id.txt").write_text(IMAGE_ID + "\n", encoding="utf-8")
    (nina / "ola-nina-ollama-runtime.log").write_text("ollama runtime completed\n", encoding="utf-8")
    _manifest(nina, nina / "evidence-files.sha256", NINA_FILES)

    for name in NINA_FILES:
        target = runtime / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(nina / name, target)
    (bundle / "integrity").mkdir(parents=True)
    shutil.copy2(nina / "evidence-files.sha256", bundle / "integrity" / "evidence-files.sha256")
    (bundle / "integrity" / "nina-artifact-api-digest.txt").write_text(NINA_DIGEST + "\n", encoding="utf-8")
    _json(bundle / "MANIFEST.json", {
        "schema": "ola-igor-evidence/v1",
        "source_commit": source_sha,
        "nina_run_id": FLOW_RUN_ID,
        "run_id": RUN_ID,
        "tenant_id": TENANT_ID,
        "provider": "ollama",
        "model": MODEL,
        "igor": "VERIFIED",
        "tamper": "BLOCK",
        "human_gate": "PENDING",
    })
    _json(bundle / "human" / "human-gate.json", {"status": "PENDING", "reason": "Human approval is not performed by CI automation."})
    _json(bundle / "tamper" / "tamper-verifier.log", {"status": "BLOCK", "reason": "V4 payload is not canonical"})
    _json(bundle / "verification" / "igor-result.json", {
        "verifier": "IGOR",
        "source_commit": source_sha,
        "nina_run_id": FLOW_RUN_ID,
        "nina_artifact_name": f"nina-igor-ollama-full-flow-{source_sha}",
        "status": "VERIFIED",
        "hash_chain": "VERIFIED",
        "evidence_count": 6,
        "replay": "VERIFIED",
        "tamper": "BLOCK",
        "human_gate": "PENDING",
        "provider": "ollama",
        "model": MODEL,
    })
    (bundle / "provenance").mkdir(parents=True)
    (bundle / "provenance" / "provenance.txt").write_text(provenance, encoding="utf-8")
    (bundle / "source").mkdir(parents=True)
    (bundle / "source" / "commit.txt").write_text(source_sha + "\n", encoding="utf-8")
    _json(bundle / "source" / "ola-build-info.json", build)
    (bundle / "source" / "runtime-image-id.txt").write_text(IMAGE_ID + "\n", encoding="utf-8")
    (bundle / "source" / "runtime-image-revision.txt").write_text(source_sha + "\n", encoding="utf-8")
    _manifest(igor, bundle / "integrity" / "bundle-files.sha256", IGOR_BUNDLE_FILES)

    tar_path = igor / "igor-ollama-evidence-bundle.tar.gz"
    with tarfile.open(tar_path, "w:gz") as archive:
        archive.add(bundle, arcname="evidence-bundle")
    _manifest(igor, igor / "igor-ollama-evidence-bundle.sha256", {"igor-ollama-evidence-bundle.tar.gz"})


def _refresh_igor_archive(root: Path) -> None:
    igor = root / "downloaded" / "independent-igor"
    bundle = igor / "evidence-bundle"
    _manifest(igor, bundle / "integrity" / "bundle-files.sha256", IGOR_BUNDLE_FILES)
    tar_path = igor / "igor-ollama-evidence-bundle.tar.gz"
    with tarfile.open(tar_path, "w:gz") as archive:
        archive.add(bundle, arcname="evidence-bundle")
    _manifest(igor, igor / "igor-ollama-evidence-bundle.sha256", {"igor-ollama-evidence-bundle.tar.gz"})


def test_nested_evidence_verifies_realistic_nina_and_igor_structure(tmp_path):
    _write_nested(tmp_path)

    ok, reason = verify_nested_evidence(tmp_path, SOURCE_SHA, FLOW_RUN_ID, NINA_DIGEST)

    assert ok is True
    assert reason == "verified"


def test_nested_evidence_rejects_missing_files_even_if_summary_can_be_valid(tmp_path):
    (tmp_path / "ola-auto-evidence.json").write_text('{"verified_claim":true}\n', encoding="utf-8")

    ok, reason = verify_nested_evidence(tmp_path, SOURCE_SHA, FLOW_RUN_ID, NINA_DIGEST)

    assert ok is False
    assert reason == "nested_evidence_missing"


def test_nested_evidence_rejects_forged_igor_result_after_manifests_are_rehashed(tmp_path):
    _write_nested(tmp_path)
    result_path = tmp_path / "downloaded/independent-igor/evidence-bundle/verification/igor-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["status"] = "BLOCK"
    _json(result_path, result)
    _refresh_igor_archive(tmp_path)

    ok, reason = verify_nested_evidence(tmp_path, SOURCE_SHA, FLOW_RUN_ID, NINA_DIGEST)

    assert ok is False
    assert reason == "igor_verifier_or_provenance_mismatch"


def test_nested_evidence_binds_nina_artifact_digest_to_igor_bundle(tmp_path):
    _write_nested(tmp_path)

    ok, reason = verify_nested_evidence(tmp_path, SOURCE_SHA, FLOW_RUN_ID, "sha256:" + "2" * 64)

    assert ok is False
    assert reason == "igor_nested_nina_copy_mismatch"


def test_nested_artifact_copies_require_exact_original_artifact_trees(tmp_path):
    _write_nested(tmp_path)
    root = tmp_path / "aggregator"
    root.mkdir()
    shutil.copytree(tmp_path / "downloaded", root / "downloaded")
    artifacts = []
    sources = {}
    for index, (label, name, relative) in enumerate((
        ("preflight", f"ola-preflight-evidence-{SOURCE_SHA}", "downloaded/preflight"),
        ("nina", f"nina-igor-ollama-full-flow-{SOURCE_SHA}", "downloaded/ollama"),
        ("igor", f"igor-independent-ollama-evidence-{SOURCE_SHA}", "downloaded/independent-igor"),
    ), start=1):
        source = tmp_path / f"source-{label}"
        shutil.copytree(root / relative, source)
        sources[index] = source
        artifacts.append({
            "id": index,
            "name": name,
            "digest": "sha256:" + str(index) * 64,
            "size_in_bytes": 100,
            "expired": False,
        })

    def fake_download(repository, artifact_id, digest, size, target):
        shutil.copytree(sources[artifact_id], target)
        return True, "verified"

    ok, reason, metadata = verify_nested_artifact_copies(
        "example/OLA", artifacts, root, SOURCE_SHA, tmp_path / "downloads", fake_download
    )
    assert ok is True
    assert reason == "verified"
    assert set(metadata) == {"preflight", "nina", "igor"}

    (root / "downloaded/ollama/provenance.txt").write_text("tampered\n", encoding="utf-8")
    ok, reason, _ = verify_nested_artifact_copies(
        "example/OLA", artifacts, root, SOURCE_SHA, tmp_path / "downloads-2", fake_download
    )
    assert ok is False
    assert reason == "nina_artifact_copy_mismatch"
