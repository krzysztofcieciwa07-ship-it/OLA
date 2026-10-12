from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewDecision:
    approved: bool
    actor: str
    reason: str


@dataclass(frozen=True)
class GateResult:
    status: str
    reason: str


class HumanGate:
    @staticmethod
    def evaluate(candidate_status: str, decision: ReviewDecision) -> GateResult:
        # Only a literal boolean approval from an identified reviewer counts.
        # Strings such as "false" and integers such as 1 must not authorize.
        if not isinstance(decision, ReviewDecision):
            return GateResult("BLOCK", "review decision is invalid")
        if not isinstance(decision.actor, str) or not decision.actor.strip():
            return GateResult("BLOCK", "review actor is required")
        if type(decision.approved) is not bool:
            return GateResult("BLOCK", "review approval must be boolean")
        if decision.approved is not True:
            return GateResult("BLOCK", decision.reason if isinstance(decision.reason, str) and decision.reason else "review rejected")
        if candidate_status != "VERIFIED":
            return GateResult("BLOCK", f"cannot promote {candidate_status} to VERIFIED")
        return GateResult("VERIFIED", "human review confirmed verified candidate")
