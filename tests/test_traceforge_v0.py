from pathlib import Path

from traceforge.engine import TraceForgeEngine


def test_vertical_slice_acquire_verify_replay_recover(tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("reproducible knowledge\n", encoding="utf-8")

    engine = TraceForgeEngine(tmp_path / "tf")
    result = engine.acquire(
        query="find canonical source",
        source=source,
        route="local_file",
        failed_routes=["missing-cache"],
    )

    assert result["status"] == "OBSERVED"
    assert result["search_dna"]["query"] == "find canonical source"
    assert result["search_dna"]["successful_routes"] == ["local_file"]
    assert result["search_dna"]["failed_routes"] == ["missing-cache"]

    verified = engine.verify(result["artifact_id"])
    assert verified["status"] == "VERIFIED"
    assert verified["source_hash"] == verified["artifact_hash"]

    graph = engine.graph()
    edges = {(e["from"], e["relation"], e["to"]) for e in graph["edges"]}
    assert (result["trace_id"], "FOUND_BY", result["artifact_id"]) in edges
    assert (result["source_id"], "PRODUCES", result["artifact_id"]) in edges
    assert (result["artifact_id"], "SUPPORTED_BY", result["evidence_id"]) in edges

    replay = engine.replay()
    assert replay["status"] == "VERIFIED"
    assert replay["event_count"] >= 2

    artifact_path = Path(result["artifact_path"])
    artifact_path.unlink()
    assert not artifact_path.exists()

    recovered = engine.recover(result["artifact_id"])
    assert recovered["status"] == "VERIFIED"
    assert recovered["recovered_hash"] == result["sha256"]
    assert artifact_path.read_text(encoding="utf-8") == "reproducible knowledge\n"

    final_replay = engine.replay()
    assert final_replay["status"] == "VERIFIED"
    assert final_replay["event_count"] > replay["event_count"]


def test_tampered_artifact_is_blocked(tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("trusted", encoding="utf-8")
    engine = TraceForgeEngine(tmp_path / "tf")
    result = engine.acquire(query="trusted input", source=source, route="local_file")

    Path(result["artifact_path"]).write_text("tampered", encoding="utf-8")
    verdict = engine.verify(result["artifact_id"])

    assert verdict["status"] == "BLOCKED"
    assert verdict["reason"] == "artifact hash mismatch"


def test_recovery_fails_closed_if_source_changed(tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("v1", encoding="utf-8")
    engine = TraceForgeEngine(tmp_path / "tf")
    result = engine.acquire(query="recover me", source=source, route="local_file")

    Path(result["artifact_path"]).unlink()
    source.write_text("v2", encoding="utf-8")

    recovered = engine.recover(result["artifact_id"])
    assert recovered["status"] == "BLOCKED"
    assert recovered["reason"] == "source hash mismatch"
    assert not Path(result["artifact_path"]).exists()


def test_export_package_contains_replayable_manifest(tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("package me", encoding="utf-8")
    engine = TraceForgeEngine(tmp_path / "tf")
    result = engine.acquire(query="package", source=source, route="local_file")
    assert engine.verify(result["artifact_id"])["status"] == "VERIFIED"

    package = engine.export_package()
    manifest = package["manifest"]

    assert manifest["schema_version"] == "traceforge/v0"
    assert manifest["artifact_count"] == 1
    assert manifest["trace_count"] >= 1
    assert manifest["evidence_count"] >= 1
    assert manifest["event_chain_status"] == "VERIFIED"
    assert manifest["event_tip_hash"] == engine.replay()["tip_hash"]
    assert Path(package["manifest_path"]).exists()
    assert Path(package["graph_path"]).exists()
