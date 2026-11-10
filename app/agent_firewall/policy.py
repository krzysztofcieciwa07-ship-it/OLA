"""Deterministic, versioned policy evaluation for OLA Agent Firewall v0.2."""

from dataclasses import dataclass


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
    def __init__(self, policy_path):
        self.policy_path = policy_path

    def evaluate(self, action: FirewallAction) -> PolicyResult:
        # Intentionally incomplete contract seam: tests must fail until the
        # deterministic policy implementation is added.
        return PolicyResult(
            decision="UNKNOWN",
            risk=None,
            reason_code="NOT_IMPLEMENTED",
            policy_version="unknown",
        )
