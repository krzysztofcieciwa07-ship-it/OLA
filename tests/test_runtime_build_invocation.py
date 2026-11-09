"""Build-invocation identity must come from immutable image metadata."""
import json

from app.runtime_provenance import runtime_build_invocation


def test_runtime_build_invocation_reads_positive_id_and_attempt_from_image_metadata(tmp_path):
    path = tmp_path / "ola-build-info.json"
    path.write_text(json.dumps({
        "schema": "ola-build-info/v1",
        "source_commit": "a" * 40,
        "github_run_id": 40968975127,
        "github_run_attempt": 2,
    }), encoding="utf-8")

    assert runtime_build_invocation(build_info_path=path) == (40968975127, 2)


def test_runtime_build_invocation_fails_closed_when_metadata_is_missing_or_malformed(tmp_path):
    path = tmp_path / "ola-build-info.json"
    path.write_text(json.dumps({
        "schema": "ola-build-info/v1",
        "source_commit": "a" * 40,
    }), encoding="utf-8")
    assert runtime_build_invocation(build_info_path=path) is None

    path.write_text(json.dumps({
        "schema": "ola-build-info/v1",
        "source_commit": "a" * 40,
        "github_run_id": True,
        "github_run_attempt": 1,
    }), encoding="utf-8")
    assert runtime_build_invocation(build_info_path=path) is None

    path.write_text(json.dumps({
        "schema": "ola-build-info/v1",
        "source_commit": "a" * 40,
        "github_run_id": 40968975127,
        "github_run_attempt": 0,
    }), encoding="utf-8")
    assert runtime_build_invocation(build_info_path=path) is None
