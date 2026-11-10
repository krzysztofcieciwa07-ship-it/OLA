"""Deterministic, versioned policy evaluation for OLA Agent Firewall v0.2."""

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any


_DECISION_RANK = {"ALLOW": 0, "REVIEW": 1, "BLOCK": 2}
_ALLOWED_ACTIONS = frozenset({"systemd.restart"})
_REQUIRED_SCORING_FIELDS = ("base", "systemd_restart", "production", "critical_target")


@dataclass(frozen=True)
class FirewallAction:
    action_type: str
    environment: str
    target_critical: bool = False
    target_id: str = "target"
    unit: str = "ola-api.service"


@dataclass(frozen=True)
class PolicyResult:
    decision: str
    risk: int | None
    reason_code: str
    policy_version: str
    matched_rule_ids: tuple[str, ...] = ()


class PolicyEngine:
    """Load a bounded TOML policy and apply deterministic additive scoring.

    Missing, malformed, or unsupported policy data always yields BLOCK.
    A rule's decision is a minimum restriction; overlapping rules combine by
    BLOCK > REVIEW > ALLOW. No model or external service participates.
    """

    def __init__(self, policy_path: str | Path):
        self.policy_path = Path(policy_path)
        self._policy: dict[str, Any] | None = None
        self._load()

    def _load(self) -> None:
        try:
            raw = self.policy_path.read_bytes()
            if not raw or len(raw) > 64 * 1024:
                raise ValueError("policy size is invalid")
            parsed = tomllib.loads(raw.decode("utf-8"))
            meta = parsed["meta"]
            scoring = parsed["scoring"]
            rules = parsed["rules"]
            version = meta["version"]
            allow_below = meta["allow_below"]
            block_at = meta["block_at"]

            if not isinstance(version, str) or not version.strip() or len(version) > 128:
                raise ValueError("policy version is invalid")
            if type(allow_below) is not int or type(block_at) is not int:
                raise ValueError("policy thresholds must be integers")
            if not 0 <= allow_below < block_at <= 100:
                raise ValueError("policy thresholds must satisfy 0 <= allow_below < block_at <= 100")
            if not isinstance(scoring, dict):
                raise ValueError("scoring section is invalid")
            normalized_scoring = {}
            for field in _REQUIRED_SCORING_FIELDS:
                value = scoring[field]
                if type(value) is not int or value < 0 or value > 100:
                    raise ValueError(f"scoring weight {field} is invalid")
                normalized_scoring[field] = value

            if not isinstance(rules, list):
                raise ValueError("rules must be an array of tables")
            normalized_rules = []
            seen_ids = set()
            for rule in rules:
                if not isinstance(rule, dict):
                    raise ValueError("policy rule must be a table")
                rule_id = rule.get("id")
                action_type = rule.get("action_type")
                environment = rule.get("environment")
                decision = rule.get("decision")
                target_id = rule.get("target_id")
                unit = rule.get("unit")
                if not isinstance(rule_id, str) or not rule_id.strip() or len(rule_id) > 128:
                    raise ValueError("policy rule id is invalid")
                if rule_id in seen_ids:
                    raise ValueError("policy rule ids must be unique")
                seen_ids.add(rule_id)
                if not isinstance(action_type, str) or not isinstance(environment, str):
                    raise ValueError("policy rule action and environment are required")
                if decision not in _DECISION_RANK:
                    raise ValueError("policy rule decision is invalid")
                if target_id is not None and not isinstance(target_id, str):
                    raise ValueError("policy rule target_id is invalid")
                if unit is not None and not isinstance(unit, str):
                    raise ValueError("policy rule unit is invalid")
                normalized_rules.append({
                    "id": rule_id, "action_type": action_type,
                    "environment": environment, "decision": decision,
                    "target_id": target_id, "unit": unit,
                })

            self._policy = {
                "version": version, "allow_below": allow_below,
                "block_at": block_at, "scoring": normalized_scoring,
                "rules": normalized_rules,
            }
        except (OSError, UnicodeDecodeError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError):
            self._policy = None

    def evaluate(self, action: FirewallAction) -> PolicyResult:
        if self._policy is None:
            return PolicyResult("BLOCK", None, "POLICY_UNAVAILABLE", "unavailable")
        version = self._policy["version"]

        if not isinstance(action, FirewallAction):
            return PolicyResult("BLOCK", None, "INVALID_ACTION", version)
        if not isinstance(action.action_type, str) or action.action_type not in _ALLOWED_ACTIONS:
            return PolicyResult("BLOCK", None, "ACTION_NOT_ALLOWLISTED", version)
        if not isinstance(action.environment, str) or action.environment not in {"staging", "production"}:
            return PolicyResult("BLOCK", None, "NO_POLICY", version)
        if type(action.target_critical) is not bool:
            decision = "BLOCK" if action.environment == "production" else "REVIEW"
            return PolicyResult(decision, None, "RISK_SCORING_FAILED", version)

        matches = [
            rule for rule in self._policy["rules"]
            if rule["action_type"] == action.action_type
            and rule["environment"] == action.environment
            and (rule["target_id"] is None or rule["target_id"] == action.target_id)
            and (rule["unit"] is None or rule["unit"] == action.unit)
        ]
        if not matches:
            return PolicyResult("BLOCK", None, "NO_POLICY", version)

        scoring = self._policy["scoring"]
        try:
            risk = scoring["base"] + scoring["systemd_restart"]
            if action.environment == "production":
                risk += scoring["production"]
            if action.target_critical:
                risk += scoring["critical_target"]
            risk = min(100, risk)
        except Exception:
            decision = "BLOCK" if action.environment == "production" else "REVIEW"
            return PolicyResult(decision, None, "RISK_SCORING_FAILED", version)

        if risk >= self._policy["block_at"]:
            risk_decision, risk_reason = "BLOCK", "RISK_BLOCK_THRESHOLD"
        elif risk >= self._policy["allow_below"]:
            risk_decision, risk_reason = "REVIEW", "RISK_REVIEW_THRESHOLD"
        else:
            risk_decision, risk_reason = "ALLOW", "POLICY_MATCH"

        policy_decision = max(
            (rule["decision"] for rule in matches),
            key=lambda item: _DECISION_RANK[item],
        )
        decision = max(
            (risk_decision, policy_decision),
            key=lambda item: _DECISION_RANK[item],
        )
        if decision == "BLOCK" and risk_decision != "BLOCK":
            reason = "POLICY_RESTRICTED"
        elif decision == "REVIEW" and risk_decision == "ALLOW":
            reason = "POLICY_RESTRICTED"
        else:
            reason = risk_reason

        return PolicyResult(
            decision=decision,
            risk=risk,
            reason_code=reason,
            policy_version=version,
            matched_rule_ids=tuple(sorted(rule["id"] for rule in matches)),
        )
