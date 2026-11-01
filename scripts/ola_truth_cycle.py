"""Evidence-backed, fail-closed OLA diagnostic cycle.

This is a local observer and test-driven proposal generator, NOT an AI planner,
automatic code mutator, release approval, or rollback implementation.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from uuid import uuid4
from xml.etree import ElementTree


SOURCE_DIRS = ("app", "tests", "scripts", ".github/workflows", "web", "revenue", "workstation")
ROOT_FILES = ("requirements.txt", "pyproject.toml", "Dockerfile", "evidence_graph.py",
              "conftest.py", "pytest.ini", "tox.ini", "setup.cfg")
IGNORED_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "node_modules"}
MAX_FILES = 3000
MAX_FILE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 50_000_000
MAX_REPORT_BYTES = 1_000_000


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def collect_source(root):
    """Hash a bounded, explicitly documented source scope without following links."""
    root = Path(root).resolve(strict=True)
    paths = []
    symlinks = []
    for dirname in SOURCE_DIRS:
        directory = root / dirname
        if directory.is_dir() and not directory.is_symlink():
            for directory_path, dirs, files in os.walk(directory, topdown=True, followlinks=False):
                symlinks.extend((Path(directory_path) / name).relative_to(root).as_posix()
                                for name in dirs if (Path(directory_path) / name).is_symlink())
                dirs[:] = [name for name in dirs if name not in IGNORED_DIRS
                           and not (Path(directory_path) / name).is_symlink()]
                for filename in files:
                    path = Path(directory_path) / filename
                    if path.is_symlink():
                        symlinks.append(path.relative_to(root).as_posix())
                    elif not filename.endswith((".pyc", ".db")):
                        paths.append(path)
                        if len(paths) > MAX_FILES:
                            raise ValueError("source scope exceeds file-count limit")
    for name in ROOT_FILES:
        path = root / name
        if path.is_symlink():
            symlinks.append(name)
        elif path.is_file():
            paths.append(path)
    paths = sorted(set(paths), key=lambda item: item.relative_to(root).as_posix())
    if len(paths) > MAX_FILES:
        raise ValueError("source scope exceeds file-count limit")

    total_bytes = 0
    entries = []
    for path in paths:
        rel = path.relative_to(root).as_posix()
        with path.open("rb") as stream:
            content = stream.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise ValueError(f"source file exceeds size limit: {rel}")
        total_bytes += len(content)
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError("source scope exceeds total-byte limit")
        digest = hashlib.sha256(content).hexdigest()
        entries.append({"path": rel, "sha256": digest})

    if not entries:
        raise ValueError("no source files in the configured scope")
    return {
        "scope": list(SOURCE_DIRS) + list(ROOT_FILES),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "excluded_symlinks": sorted(symlinks)[:40],
        "excluded_symlink_count": len(symlinks),
        "source_paths": [entry["path"] for entry in entries],
        "tree_sha256": hashlib.sha256(_canonical(entries)).hexdigest(),
    }


def _git(root, *args):
    try:
        process = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True,
            timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return process.stdout.strip() if process.returncode == 0 else None


def _git_paths(root, *args):
    try:
        process = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if process.returncode != 0 or len(process.stdout) > 2_000_000:
        return None
    return {part.decode("utf-8", errors="surrogateescape")
            for part in process.stdout.split(b"\x00") if part}


def inspect_git(root, source=None):
    """Bind *every hashed file* to HEAD, including Git-ignored source files."""
    sha = _git(root, "rev-parse", "HEAD")
    if not sha:
        return {"commit": None, "source_bound_to_commit": False, "reason": "git commit unavailable"}
    if source is None:
        source = collect_source(root)
    scope = list(SOURCE_DIRS) + list(ROOT_FILES)
    tracked = _git_paths(root, "ls-files", "-z", "--", *scope)
    modified = _git_paths(root, "diff", "--name-only", "--no-renames", "-z", "HEAD", "--", *scope)
    if tracked is None or modified is None:
        return {"commit": sha, "source_bound_to_commit": False, "reason": "git source inventory unavailable"}
    untracked_hashed = set(source["source_paths"]) - tracked
    relevant = sorted(untracked_hashed | modified)
    has_symlinks = bool(source["excluded_symlink_count"])
    return {
        "commit": sha,
        "source_bound_to_commit": not relevant and not has_symlinks,
        "changed_source_paths": relevant[:40],
        "change_count": len(relevant),
        "unhashed_symlink_count": source["excluded_symlink_count"],
    }


def _parse_junit(path, exit_code, elapsed):
    if not path.is_file() or path.stat().st_size > 5_000_000:
        return {"status": "UNKNOWN", "reason": "missing or oversized JUnit evidence", "exit_code": exit_code}
    try:
        root = ElementTree.parse(path).getroot()
        suites = list(root.findall("testsuite")) if root.tag == "testsuites" else [root]
        if not suites or any(suite.tag != "testsuite" for suite in suites):
            raise ValueError("no testsuite element")
        counts = {key: sum(int(suite.get(key, "0")) for suite in suites)
                  for key in ("tests", "failures", "errors", "skipped")}
        failed = [f"{case.get('classname', '')}.{case.get('name', '')}" for suite in suites
                  for case in suite.iter("testcase")
                  if case.find("failure") is not None or case.find("error") is not None]
    except (ValueError, ElementTree.ParseError, OSError) as exc:
        return {"status": "UNKNOWN", "reason": f"invalid JUnit evidence: {type(exc).__name__}", "exit_code": exit_code}
    if counts["tests"] <= counts["skipped"]:
        status = "UNKNOWN"
    elif exit_code == 0 and counts["failures"] == 0 and counts["errors"] == 0:
        status = "PASS"
    else:
        status = "FAIL"
    return {
        "status": status, "exit_code": exit_code, "elapsed_seconds": round(elapsed, 3),
        **counts, "failed_test_ids": failed[:25], "failure_ids_truncated": len(failed) > 25,
    }


def run_pytest(root, timeout_seconds=180):
    """Run known test command only; do not forward payment/model API credentials."""
    if not 1 <= timeout_seconds <= 3600:
        raise ValueError("timeout must be between 1 and 3600 seconds")
    # Only runtime plumbing crosses into the test process. No ambient service
    # credentials or unrelated OLA production settings are inherited.
    inherited = ("PATH", "VIRTUAL_ENV", "TMPDIR", "TEMP", "TMP",
                 "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT", "WINDIR")
    env = {name: os.environ[name] for name in inherited if name in os.environ}
    env.update({"OLA_LLM_PROVIDER": "none", "OLA_LLM_MODE": "deterministic"})
    with tempfile.TemporaryDirectory(prefix="ola_truth_junit_") as temporary:
        result_path = Path(temporary) / "results.xml"
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "pytest", "-q", f"--junitxml={result_path}"],
                cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=(os.name == "posix"),
            )
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait()
            return {"status": "UNKNOWN", "reason": "pytest timed out", "timeout_seconds": timeout_seconds}
        except OSError as exc:
            return {"status": "UNKNOWN", "reason": f"pytest could not start: {type(exc).__name__}"}
        return _parse_junit(result_path, exit_code, time.monotonic() - started)


def evaluate(source_before, source_after, git, tests):
    changed_during_test = source_before["tree_sha256"] != source_after["tree_sha256"]
    proposals = []
    if changed_during_test:
        proposals.append({"priority": "P0", "action": "INVESTIGATE_TEST_SOURCE_MUTATION", "proof": "source tree digest changed"})
    if tests["status"] == "FAIL":
        for failed in tests.get("failed_test_ids", []):
            proposals.append({"priority": "P0", "action": "FIX_TEST", "proof": failed})
        if not tests.get("failed_test_ids"):
            proposals.append({"priority": "P0", "action": "INVESTIGATE_PYTEST_FAILURE", "proof": f"exit={tests.get('exit_code')}"})
    elif tests["status"] == "UNKNOWN":
        proposals.append({"priority": "P0", "action": "RESTORE_TEST_EVIDENCE", "proof": tests.get("reason", "no valid test proof")})
    if not git["source_bound_to_commit"]:
        proposals.append({"priority": "P1", "action": "REVIEW_AND_BIND_SOURCE", "proof": "tested tree is not a clean identified commit"})
    if not proposals:
        proposals.append({"priority": "P1", "action": "VERIFY_ON_EXACT_SHA_IN_CI", "proof": "local tests alone do not authorize release"})

    return {
        "local_test_status": "PASS" if tests["status"] == "PASS" and not changed_during_test else "BLOCK",
        "source_changed_during_test": changed_during_test,
        "production_decision": "NO_GO",
        "human_gate": "PENDING_HUMAN",
        "mutation_status": "PROPOSED_ONLY",
        "mutation_applied": False,
        "rollback_ready": False,
        "snapshot_type": "SOURCE_DIGEST_ONLY_NOT_A_BACKUP",
        "proposals": proposals,
    }


def _atomic_report(path, document):
    raw = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("report exceeds bounded size limit")
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".ola_cycle_", suffix=".tmp")
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # atomic visibility, never overwrite an existing report
    finally:
        temporary.unlink(missing_ok=True)


def write_cycle(root, output_dir, *, timeout_seconds=180):
    root = Path(root).resolve(strict=True)
    before = collect_source(root)
    git = inspect_git(root, before)
    tests = run_pytest(root, timeout_seconds)
    after = collect_source(root)
    decision = evaluate(before, after, git, tests)
    report = {
        "schema": "ola.truth-cycle.v1",
        "cycle_id": str(uuid4()),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "observer": before, "source_after_tests": after,
        "git": git, "tests": tests, "decision": decision,
        "limits": {
            "analysis": "deterministic rules based on observed tests; no LLM planning",
            "factual_answer_verification": "NOT_PERFORMED",
            "production_claim": "NEVER_AUTOMATICALLY_APPROVED",
            "report_authenticity": "SHA256_INTEGRITY_ONLY_NOT_SIGNED",
        },
    }
    envelope = {"report": report, "report_sha256": hashlib.sha256(_canonical(report)).hexdigest()}
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"cycle_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{report['cycle_id']}.json"
    destination = output_dir / name
    _atomic_report(destination, envelope)
    return destination, envelope


def verify_report(path):
    try:
        location = Path(path)
        if location.stat().st_size > MAX_REPORT_BYTES:
            return False
        document = json.loads(location.read_text(encoding="utf-8"))
        if set(document) != {"report", "report_sha256"} or not isinstance(document["report"], dict):
            return False
        return hashlib.sha256(_canonical(document["report"])).hexdigest() == document["report_sha256"]
    except (OSError, ValueError, TypeError, KeyError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="OLA truth-bound local diagnostic cycle")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--verify-report", type=Path)
    args = parser.parse_args(argv)
    if args.verify_report:
        ok = verify_report(args.verify_report)
        print("REPORT_INTEGRITY=PASS" if ok else "REPORT_INTEGRITY=FAIL")
        return 0 if ok else 1
    try:
        destination, envelope = write_cycle(
            args.repo, args.output_dir or args.repo / "ola_truth_reports",
            timeout_seconds=args.timeout,
        )
    except (OSError, ValueError) as exc:
        print(f"CYCLE=BLOCK reason={type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    report = envelope["report"]
    print(json.dumps({
        "report_path": str(destination), "report_sha256": envelope["report_sha256"],
        "source_tree_sha256": report["observer"]["tree_sha256"],
        "tests": report["tests"], "decision": report["decision"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if (report["decision"]["local_test_status"] == "PASS"
                 and report["git"]["source_bound_to_commit"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
