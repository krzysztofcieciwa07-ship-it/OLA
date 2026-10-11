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
    """Fail-closed execution gate: unknown actions and risks never execute."""

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
        _ = agent_id
        if not isinstance(risk, str) or risk.upper() not in {"LOW", "HIGH"}:
            return ExecutionDecision(status="BLOCK")
        # Preserve the existing human-approval contract, even for actions
        # which would subsequently be rejected by the allowlist.
        if risk.upper() == "HIGH" and not human_approved:
            return ExecutionDecision(status="REVIEW", required_approval="HUMAN_OWNER")
        if not isinstance(action, str) or action not in self._allowed_actions:
            return ExecutionDecision(status="BLOCK")
        if not callable(effect):
            return ExecutionDecision(status="BLOCK")
        return ExecutionDecision(status="ALLOW", side_effect_count=1, result=effect())
