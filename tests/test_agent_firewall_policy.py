from pathlib import Path

from app.agent_firewall.policy import FirewallAction, PolicyEngine


def _policy(tmp_path: Path, *, rules=None, scoring=None, thresholds=None):
    rules = rules or [
        {"id": "staging-restart", "action_type": "systemd.restart",
         "environment": "staging", "decision": "ALLOW"},
        {"id": "production-restart", "action_type": "systemd.restart",
         "environment": "production", "decision": "REVIEW"},
    ]
    scoring = scoring or {
        "base": 10, "systemd_restart": 15,
        "production": 30, "critical_target": 35,
    }
    thresholds = thresholds or {"allow_below": 40, "block_at": 90}
    rows = [
        '[meta]',
        'version = "agent-firewall-v0.2.0"',
        f'allow_below = {thresholds["allow_below"]}',
        f'block_at = {thresholds["block_at"]}',
        '',
        '[scoring]',
        f'base = {scoring["base"]}',
        f'systemd_restart = {scoring["systemd_restart"]}',
        f'production = {scoring["production"]}',
        f'critical_target = {scoring["critical_target"]}',
    ]
    for rule in rules:
        rows.extend([
            '',
            '[[rules]]',
            f'id = "{rule["id"]}"',
            f'action_type = "{rule["action_type"]}"',
            f'environment = "{rule["environment"]}"',
            f'decision = "{rule["decision"]}"',
        ])
        if "target_id" in rule:
            rows.append(f'target_id = "{rule["target_id"]}"')
    path = tmp_path / "policy.toml"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_staging_restart_below_allow_threshold_is_allowed(tmp_path):
    engine = PolicyEngine(_policy(tmp_path))
    result = engine.evaluate(FirewallAction("systemd.restart", "staging"))

    assert result.decision == "ALLOW"
    assert result.risk == 25
    assert result.reason_code == "POLICY_MATCH"
    assert result.policy_version == "agent-firewall-v0.2.0"


def test_production_restart_requires_review(tmp_path):
    engine = PolicyEngine(_policy(tmp_path))
    result = engine.evaluate(FirewallAction("systemd.restart", "production"))

    assert result.decision == "REVIEW"
    assert result.risk == 55
    assert result.reason_code == "POLICY_MATCH"


def test_production_critical_restart_at_block_threshold_is_blocked(tmp_path):
    engine = PolicyEngine(_policy(tmp_path))
    result = engine.evaluate(
        FirewallAction("systemd.restart", "production", target_critical=True)
    )

    assert result.decision == "BLOCK"
    assert result.risk == 90
    assert result.reason_code == "RISK_BLOCK_THRESHOLD"


def test_threshold_boundary_is_inclusive_and_deterministic(tmp_path):
    path = _policy(
        tmp_path,
        scoring={"base": 10, "systemd_restart": 15,
                 "production": 0, "critical_target": 15},
    )
    result = PolicyEngine(path).evaluate(
        FirewallAction("systemd.restart", "staging", target_critical=True)
    )

    assert result.risk == 40
    assert result.decision == "REVIEW"


def test_no_matching_policy_is_default_deny(tmp_path):
    engine = PolicyEngine(_policy(tmp_path))
    result = engine.evaluate(FirewallAction("systemd.restart", "development"))

    assert result.decision == "BLOCK"
    assert result.reason_code == "NO_POLICY"


def test_multiple_matching_rules_choose_the_most_restrictive(tmp_path):
    path = _policy(
        tmp_path,
        rules=[
            {"id": "allow", "action_type": "systemd.restart",
             "environment": "staging", "decision": "ALLOW"},
            {"id": "block", "action_type": "systemd.restart",
             "environment": "staging", "decision": "BLOCK"},
        ],
    )
    result = PolicyEngine(path).evaluate(FirewallAction("systemd.restart", "staging"))

    assert result.decision == "BLOCK"
    assert result.matched_rule_ids == ("allow", "block")


def test_shell_execution_is_never_allowed_by_a_policy_rule(tmp_path):
    path = _policy(
        tmp_path,
        rules=[
            {"id": "bad-shell-rule", "action_type": "shell.execute",
             "environment": "staging", "decision": "ALLOW"},
        ],
    )
    result = PolicyEngine(path).evaluate(FirewallAction("shell.execute", "staging"))

    assert result.decision == "BLOCK"
    assert result.reason_code == "ACTION_NOT_ALLOWLISTED"


def test_missing_policy_store_is_blocked(tmp_path):
    result = PolicyEngine(tmp_path / "missing-policy.toml").evaluate(
        FirewallAction("systemd.restart", "staging")
    )

    assert result.decision == "BLOCK"
    assert result.reason_code == "POLICY_UNAVAILABLE"
