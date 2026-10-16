"""Reject signed-but-wrong source claims after cryptographic verification."""
from copy import deepcopy
import subprocess

import pytest

from scripts.verify_supply_chain_source import (
    PREDICATE, SLSA, STATEMENT, expected_binding, record_checkout, verify_source,
)

ENV = {"SOURCE_SHA": "a" * 40, "GITHUB_SHA": "b" * 40,
       "GITHUB_REPOSITORY": "owner/repo", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}
DIGEST = "c" * 64


def report(kind, predicate):
    return [{"verificationResult": {"statement": {
        "_type": STATEMENT, "predicateType": kind,
        "subject": [{"name": "ola-image.tar", "digest": {"sha256": DIGEST}}],
        "predicate": predicate,
    }}}]


def reports():
    return (report(SLSA, {"buildDefinition": {"resolvedDependencies": [
        {"digest": {"gitCommit": ENV["GITHUB_SHA"]}}]}}),
        report(PREDICATE, expected_binding(ENV)))


def test_pr_head_and_event_commit_are_separate_verified_claims():
    result = verify_source(*reports(), DIGEST, ENV)
    assert result["source_sha"] == ENV["SOURCE_SHA"]
    assert result["workflow_event_sha"] == ENV["GITHUB_SHA"]
    assert result["source_binding"] == "VERIFIED"


@pytest.mark.parametrize("part,key,value", [
    ("source", "commit", ENV["GITHUB_SHA"]),
    ("source", "repository", "attacker/repo"),
    ("workflow", "event_commit", ENV["SOURCE_SHA"]),
    ("workflow", "run_id", "122"),
    ("workflow", "run_attempt", "1"),
])
def test_substitution_and_replayed_execution_are_rejected(part, key, value):
    provenance, binding = reports()
    binding[0]["verificationResult"]["statement"]["predicate"][part][key] = value
    with pytest.raises(ValueError, match="context mismatch"):
        verify_source(provenance, binding, DIGEST, ENV)


@pytest.mark.parametrize("which,field,value", [
    (0, "_type", "wrong"), (1, "predicateType", SLSA),
    (0, "subject", []), (1, "subject", [{"digest": {"sha256": "d" * 64}}]),
    (0, "predicate", {}),
])
def test_missing_or_mismatched_attestation_is_rejected(which, field, value):
    data = list(reports())
    data[which][0]["verificationResult"]["statement"][field] = value
    with pytest.raises(ValueError):
        verify_source(*data, DIGEST, ENV)


def test_missing_source_binding_cannot_be_replaced_by_slsa():
    with pytest.raises(ValueError, match="no verified"):
        verify_source(reports()[0], [], DIGEST, ENV)


def test_record_checks_actual_git_checkout_and_tracked_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()
    git("init", "-q")
    (tmp_path / "source").write_text("original\n")
    git("add", "source")
    git("-c", "user.name=Test", "-c", "user.email=test@example.com",
        "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    env = deepcopy(ENV)
    env["SOURCE_SHA"] = git("rev-parse", "HEAD")
    assert record_checkout(env) == expected_binding(env)
    with pytest.raises(ValueError, match="checkout does not match"):
        record_checkout(ENV)
    (tmp_path / "source").write_text("tampered\n")
    with pytest.raises(ValueError, match="modified"):
        record_checkout(env)
