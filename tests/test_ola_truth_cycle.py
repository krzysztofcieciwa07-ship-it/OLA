import json
import subprocess

import pytest

from scripts import ola_truth_cycle as cycle


def _repo(tmp_path):
    source = tmp_path / "app"
    source.mkdir()
    (source / "module.py").write_text("value = 41\n", encoding="utf-8")
    return tmp_path


def test_real_source_changes_invalidate_the_digest(tmp_path):
    repo = _repo(tmp_path)
    before = cycle.collect_source(repo)
    (repo / "app" / "module.py").write_text("value = 42\n", encoding="utf-8")
    after = cycle.collect_source(repo)

    assert before["file_count"] == after["file_count"] == 1
    assert before["tree_sha256"] != after["tree_sha256"]


def test_source_hash_does_not_follow_external_symlinks(tmp_path):
    repo = _repo(tmp_path)
    outside = tmp_path / "real-but-external-to-source.txt"
    outside.write_text("EXTERNAL", encoding="utf-8")
    (repo / "app" / "outside.py").symlink_to(outside)

    source = cycle.collect_source(repo)
    assert source["file_count"] == 1
    assert source["excluded_symlink_count"] == 1
    assert source["excluded_symlinks"] == ["app/outside.py"]


def test_failing_tests_generate_specific_evidence_based_proposals(tmp_path):
    repo = _repo(tmp_path)
    source = cycle.collect_source(repo)
    git = {"commit": "a" * 40, "source_bound_to_commit": True}
    result = cycle.evaluate(source, source, git, {
        "status": "FAIL", "exit_code": 1,
        "failed_test_ids": ["test_module.test_real_output"],
    })

    assert result["production_decision"] == "NO_GO"
    assert result["mutation_applied"] is False
    assert result["rollback_ready"] is False
    assert result["proposals"][0] == {
        "priority": "P0", "action": "FIX_TEST", "proof": "test_module.test_real_output",
    }


def test_green_tests_never_promote_production(tmp_path):
    source = cycle.collect_source(_repo(tmp_path))
    decision = cycle.evaluate(source, source, {"source_bound_to_commit": True}, {"status": "PASS"})

    assert decision["local_test_status"] == "PASS"
    assert decision["production_decision"] == "NO_GO"
    assert decision["human_gate"] == "PENDING_HUMAN"
    assert decision["mutation_status"] == "PROPOSED_ONLY"


def test_source_mutation_during_tests_blocks_even_if_pytest_is_green(tmp_path):
    repo = _repo(tmp_path)
    before = cycle.collect_source(repo)
    (repo / "app" / "module.py").write_text("value = 99\n", encoding="utf-8")
    after = cycle.collect_source(repo)
    decision = cycle.evaluate(before, after, {"source_bound_to_commit": True}, {"status": "PASS"})

    assert decision["local_test_status"] == "BLOCK"
    assert decision["source_changed_during_test"] is True


def test_missing_tests_are_unknown_not_success(tmp_path):
    xml = tmp_path / "empty.xml"
    xml.write_text('<testsuites><testsuite tests="0" errors="0" failures="0" skipped="0"/></testsuites>')
    assert cycle._parse_junit(xml, 5, 0.1)["status"] == "UNKNOWN"


def test_all_skipped_tests_are_unknown_not_success(tmp_path):
    xml = tmp_path / "all_skipped.xml"
    xml.write_text('<testsuites><testsuite tests="5" errors="0" failures="0" skipped="5"/></testsuites>')
    assert cycle._parse_junit(xml, 0, 0.1)["status"] == "UNKNOWN"


def test_multiple_junit_suites_include_later_failures(tmp_path):
    xml = tmp_path / "two_suites.xml"
    xml.write_text('<testsuites><testsuite tests="1" errors="0" failures="0" skipped="0">'
                   '<testcase name="good" /></testsuite><testsuite tests="1" errors="0" '
                   'failures="1" skipped="0"><testcase name="bad"><failure /></testcase>'
                   '</testsuite></testsuites>')
    report = cycle._parse_junit(xml, 1, 0.2)
    assert report["status"] == "FAIL"
    assert report["tests"] == 2
    assert report["failed_test_ids"] == [".bad"]


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, timeout=10)


def _init_git(repo):
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=OLA Audit", "-c", "user.email=audit@example.invalid",
         "add", ".")
    _git(repo, "-c", "user.name=OLA Audit", "-c", "user.email=audit@example.invalid",
         "commit", "-qm", "initial source")


def test_git_binding_detects_ignored_file_even_if_git_status_is_clean(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("*.app\n", encoding="utf-8")
    _init_git(repo)
    assert cycle.inspect_git(repo, cycle.collect_source(repo))["source_bound_to_commit"]

    (repo / "app" / "hidden.app").write_text("ignored-but-tested", encoding="utf-8")
    result = cycle.inspect_git(repo, cycle.collect_source(repo))
    assert not result["source_bound_to_commit"]
    assert "app/hidden.app" in result["changed_source_paths"]


def test_git_binding_detects_staged_cross_directory_rename(tmp_path):
    repo = _repo(tmp_path)
    (repo / "scripts").mkdir()
    _init_git(repo)
    _git(repo, "mv", "app/module.py", "scripts/module.py")
    result = cycle.inspect_git(repo, cycle.collect_source(repo))
    assert not result["source_bound_to_commit"]
    assert "scripts/module.py" in result["changed_source_paths"]


def test_git_binding_rejects_unhashed_symlink_even_when_git_tracks_it(tmp_path):
    repo = _repo(tmp_path)
    outside = repo / "outside.txt"
    outside.write_text("can change without git diff", encoding="utf-8")
    (repo / "app" / "external.py").symlink_to(outside)
    _init_git(repo)
    assert cycle.inspect_git(repo, cycle.collect_source(repo))["source_bound_to_commit"] is False


def test_bounded_source_inventory_rejects_too_many_files_without_full_recursion(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(cycle, "MAX_FILES", 2)
    (repo / "app" / "second.py").write_text("2", encoding="utf-8")
    (repo / "app" / "third.py").write_text("3", encoding="utf-8")
    with pytest.raises(ValueError, match="file-count"):
        cycle.collect_source(repo)


def test_signed_only_by_checksum_reports_detect_tampering(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(cycle, "inspect_git", lambda _root, _source: {
        "commit": None, "source_bound_to_commit": False,
    })
    monkeypatch.setattr(cycle, "run_pytest", lambda _root, _timeout: {
        "status": "PASS", "tests": 2, "failures": 0, "errors": 0,
    })
    destination, envelope = cycle.write_cycle(repo, repo / "ola_truth_reports", timeout_seconds=9)

    assert cycle.verify_report(destination)
    assert envelope["report"]["decision"]["production_decision"] == "NO_GO"
    assert envelope["report"]["limits"]["report_authenticity"] == "SHA256_INTEGRITY_ONLY_NOT_SIGNED"
    document = json.loads(destination.read_text(encoding="utf-8"))
    document["report"]["decision"]["production_decision"] = "GO"
    destination.write_text(json.dumps(document), encoding="utf-8")

    assert not cycle.verify_report(destination)


def test_oversize_report_is_rejected_before_parsing(tmp_path):
    path = tmp_path / "oversize.json"
    path.write_bytes(b"X" * (cycle.MAX_REPORT_BYTES + 1))
    assert not cycle.verify_report(path)


def test_atomic_report_never_overwrites_existing_evidence(tmp_path):
    destination = tmp_path / "immutable.json"
    cycle._atomic_report(destination, {"version": 1})
    original = destination.read_bytes()
    with pytest.raises(FileExistsError):
        cycle._atomic_report(destination, {"version": 2})
    assert destination.read_bytes() == original
    assert list(tmp_path.glob(".ola_cycle_*.tmp")) == []


def test_local_pass_but_unbound_commit_exits_nonzero(tmp_path, monkeypatch, capsys):
    path = tmp_path / "report.json"
    monkeypatch.setattr(cycle, "write_cycle", lambda *_args, **_kwargs: (path, {
        "report_sha256": "dummy", "report": {
            "observer": {"tree_sha256": "abc"},
            "tests": {"status": "PASS"},
            "git": {"source_bound_to_commit": False},
            "decision": {"local_test_status": "PASS", "production_decision": "NO_GO"},
        },
    }))
    assert cycle.main(["--repo", str(tmp_path)]) == 1
    assert "NO_GO" in capsys.readouterr().out
