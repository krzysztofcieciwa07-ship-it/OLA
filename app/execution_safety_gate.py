from dataclasses import dataclass
from typing import Any, Callable, FrozenSet, Optional


@dataclass(frozen=True)
class ExecutionDecision:
    status: str
    policy: str = "deny-by-default"
    side_effect_count: int = 0
    required_approval: Optional[str] = None
    result: Any = None


class ExecutionSafetyGate:
    """Fail-closed gate; a caller-provided boolean never authorizes risky effects.

    High/critical execution stays in REVIEW until a separate authenticated
    approval authority is integrated. This class does not issue approvals.
    """

    ALLOWED_RISK_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})

    def __init__(self, allowed_actions: Optional[set[str]] = None):
        self._allowed_actions: FrozenSet[str] = frozenset(allowed_actions or set())

    def execute(
        self,
        *,
        agent_id: str,
        action: str,
        effect: Callable[[], Any],
        risk: str = "LOW",
        human_approved: bool = False,
    ) -> ExecutionDecision:
        # Backward-compatible but deprecated: this untrusted flag cannot serve
        # as proof of approval. The external approval protocol is not yet wired.
        _ = human_approved
        if not isinstance(agent_id, str) or not agent_id.strip():
            return ExecutionDecision(status="BLOCK")
        if not isinstance(risk, str) or risk.upper() not in self.ALLOWED_RISK_LEVELS:
            return ExecutionDecision(status="BLOCK")
        # Preserve the established REVIEW contract for all high-risk requests:
        # never execute them, even if an action is not on the allowlist.
        if risk.upper() in {"HIGH", "CRITICAL"}:
            return ExecutionDecision(
                status="REVIEW",
                required_approval="HUMAN_OWNER",
            )
        if not isinstance(action, str) or action not in self._allowed_actions:
            return ExecutionDecision(status="BLOCK")

        result = effect()
        return ExecutionDecision(
            status="ALLOW",
            side_effect_count=1,
            result=result,
        )
