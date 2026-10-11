import subprocess
import pytest
from scripts.commit_integrity_guard import verify


def test_missing_allowlist_blocks():
    with pytest.raises(ValueError, match="allowlist"):
        verify("origin/main", "HEAD", set())


def test_malformed_fingerprint_blocks():
    with pytest.raises(ValueError, match="allowlist"):
        verify("origin/main", "HEAD", {"NOT_A_FINGERPRINT"})


def test_no_commits_blocks(monkeypatch):
    def fake_git(*args):
        if args[0] == "rev-parse":
            return "a" * 40
        if args[0] == "rev-list":
            return ""
        raise AssertionError(args)
    monkeypatch.setattr("scripts.commit_integrity_guard.git", fake_git)
    with pytest.raises(ValueError, match="no new commits"):
        verify("base", "head", {"A" * 40})


def test_untrusted_signer_blocks(monkeypatch):
    def fake_git(*args):
        if args[0] == "rev-parse":
            return "a" * 40
        if args[0] == "rev-list":
            return "b" * 40
        if args[0] == "log":
            return "G;" + "B" * 40
        raise AssertionError(args)
    monkeypatch.setattr("scripts.commit_integrity_guard.git", fake_git)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="untrusted"):
        verify("base", "head", {"A" * 40})
