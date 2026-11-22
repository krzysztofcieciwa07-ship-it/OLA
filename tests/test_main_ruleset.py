"""Regression contract for the GitHub main protection handoff."""
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts" / "apply_main_ruleset.py"
spec = importlib.util.spec_from_file_location("main_ruleset", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_policy_is_active_nobypass_main_only():
    p = module.policy()
    assert p["target"] == "branch"
    assert p["enforcement"] == "active"
    assert p["bypass_actors"] == []
    assert p["conditions"]["ref_name"] == {
        "include": ["refs/heads/main"],
        "exclude": [],
    }
    assert {
        "required_signatures", "pull_request", "required_status_checks",
        "non_fast_forward", "deletion",
    } <= {rule["type"] for rule in p["rules"]}


def test_policy_requires_exact_verified_check_contexts_from_actions_app():
    rules = {rule["type"]: rule for rule in module.policy()["rules"]}
    review = rules["pull_request"]["parameters"]
    assert review["required_approving_review_count"] == 1
    assert review["dismiss_stale_reviews_on_push"]
    assert review["require_last_push_approval"]
    assert review["required_review_thread_resolution"]

    checks = rules["required_status_checks"]["parameters"]
    assert checks["strict_required_status_checks_policy"]
    entries = checks["required_status_checks"]
    assert "human-gate-approval" in module.CHECKS
    assert len(entries) == len(module.CHECKS)
    assert {entry["context"] for entry in entries} == set(module.CHECKS)
    assert all(
        entry["integration_id"] == module.GITHUB_ACTIONS_INTEGRATION_ID
        for entry in entries
    )
    assert "CodeQL" not in {entry["context"] for entry in entries}
    assert "CodeQL / actions" in {entry["context"] for entry in entries}


def _check(context, sha, conclusion="success", app_id=None):
    return {
        "name": context,
        "head_sha": sha,
        "status": "completed",
        "conclusion": conclusion,
        "app": {"id": app_id if app_id is not None else module.GITHUB_ACTIONS_INTEGRATION_ID},
        "completed_at": "2026-11-05T06:00:00Z",
        "id": 1,
    }


def test_check_preflight_accepts_all_required_contexts_on_exact_sha():
    sha = "a" * 40
    payload = {"check_runs": [_check(name, sha) for name in module.CHECKS]}
    result = module.validate_check_runs(payload, sha)
    assert result == {"sha": sha, "passed_contexts": len(module.CHECKS)}


def test_check_preflight_rejects_a_missing_context():
    sha = "a" * 40
    payload = {"check_runs": [_check(name, sha) for name in module.CHECKS[:-1]]}
    with pytest.raises(RuntimeError, match="missing"):
        module.validate_check_runs(payload, sha)


def test_check_preflight_rejects_wrong_source_or_app():
    sha = "a" * 40
    payload = [_check(name, sha) for name in module.CHECKS]
    payload[0]["head_sha"] = "b" * 40
    with pytest.raises(RuntimeError, match="missing"):
        module.validate_check_runs({"check_runs": payload}, sha)

    payload[0] = _check(module.CHECKS[0], sha, app_id=99999)
    with pytest.raises(RuntimeError, match="missing"):
        module.validate_check_runs({"check_runs": payload}, sha)


def test_check_preflight_rejects_latest_failed_duplicate():
    sha = "a" * 40
    payload = [_check(name, sha) for name in module.CHECKS]
    payload.append({
        **_check(module.CHECKS[0], sha, conclusion="failure"),
        "completed_at": "2026-11-05T06:01:00Z",
        "id": 2,
    })
    with pytest.raises(RuntimeError, match="blocked"):
        module.validate_check_runs({"check_runs": payload}, sha)


def test_never_mutates_without_explicit_apply(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["apply_main_ruleset.py"])
    monkeypatch.setattr(
        module,
        "apply",
        lambda: (_ for _ in ()).throw(AssertionError("MUTATION")),
    )
    assert module.main() == 0
    assert '"status": "DRY_RUN_ONLY"' in capsys.readouterr().out

def test_policy_requires_codeowner_review_for_main():
    rules = {rule["type"]: rule for rule in module.policy()["rules"]}
    assert rules["pull_request"]["parameters"]["require_code_owner_review"] is True


def _codeowners_text(owner, reviewer=None):
    owners = f"@{owner}" + (f" @{reviewer}" if reviewer else "")
    return (
        f"* {owners}\n"
        f"/.github/ {owners}\n"
        f"/scripts/ {owners}\n"
        f"/app/ {owners}\n"
    )


def test_independent_codeowners_rejects_owner_only_mapping():
    with pytest.raises(RuntimeError, match="independent write-enabled CODEOWNER"):
        module.validate_independent_codeowners(
            _codeowners_text("krzysztofcieciwa07-ship-it"),
            owner_login="krzysztofcieciwa07-ship-it",
            permissions={"krzysztofcieciwa07-ship-it": "admin"},
        )


def test_independent_codeowners_rejects_read_only_reviewer():
    with pytest.raises(RuntimeError, match="write permission"):
        module.validate_independent_codeowners(
            _codeowners_text("krzysztofcieciwa07-ship-it", "reviewer"),
            owner_login="krzysztofcieciwa07-ship-it",
            permissions={"krzysztofcieciwa07-ship-it": "admin", "reviewer": "read"},
        )


def test_independent_codeowners_accepts_distinct_write_enabled_reviewer():
    result = module.validate_independent_codeowners(
        _codeowners_text("krzysztofcieciwa07-ship-it", "reviewer"),
        owner_login="krzysztofcieciwa07-ship-it",
        permissions={"krzysztofcieciwa07-ship-it": "admin", "reviewer": "write"},
    )
    assert result == ["reviewer"]


def test_verify_ruleset_rejects_missing_codeowner_review_rule():
    detail = module.policy()
    detail["id"] = 123
    detail["rules"] = [
        {**rule, "parameters": {**rule.get("parameters", {}), "require_code_owner_review": False}}
        if rule["type"] == "pull_request" else rule
        for rule in detail["rules"]
    ]
    with pytest.raises(RuntimeError, match="CODEOWNERS review"):
        module.verify_ruleset(detail, detail["rules"], "a" * 40)

def test_verify_ruleset_rejects_effective_missing_codeowner_review():
    detail = module.policy()
    detail["id"] = 123
    effective_rules = [
        {**rule, "parameters": {**rule.get("parameters", {}), "require_code_owner_review": False}}
        if rule["type"] == "pull_request" else rule
        for rule in detail["rules"]
    ]
    with pytest.raises(RuntimeError, match="effective ruleset does not require CODEOWNERS review"):
        module.verify_ruleset(detail, effective_rules, "a" * 40)


def test_verify_ruleset_accepts_matching_stored_and_effective_codeowner_rules():
    detail = module.policy()
    detail["id"] = 123
    result = module.verify_ruleset(detail, detail["rules"], "a" * 40)
    assert result["status"] == "VERIFIED"
    assert result["main_sha"] == "a" * 40