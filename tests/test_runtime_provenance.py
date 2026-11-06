"""Build-time source provenance must override caller-controlled environment."""
import json

from app.runtime_provenance import runtime_source_commit


def test_build_info_wins_over_spoofed_runtime_environment(monkeypatch, tmp_path):
    expected = "a" * 40
    path = tmp_path / "ola-build-info.json"
    path.write_text(json.dumps({"schema": "ola-build-info/v1", "source_commit": expected}))
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "b" * 40)
    assert runtime_source_commit(require_build_info=True, build_info_path=path) == expected


def test_strict_mode_blocks_missing_build_info_even_if_environment_is_set(monkeypatch, tmp_path):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "c" * 40)
    assert runtime_source_commit(require_build_info=True, build_info_path=tmp_path / "missing.json") is None


def test_strict_mode_blocks_malformed_build_info(monkeypatch, tmp_path):
    path = tmp_path / "ola-build-info.json"
    path.write_text('{"schema":"ola-build-info/v1","source_commit":"not-a-sha"}')
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "d" * 40)
    assert runtime_source_commit(require_build_info=True, build_info_path=path) is None


def test_legacy_environment_is_only_non_strict_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "e" * 40)
    assert runtime_source_commit(require_build_info=False, build_info_path=tmp_path / "missing.json") == "e" * 40
