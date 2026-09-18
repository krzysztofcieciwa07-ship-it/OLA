from .human_gate import HumanGate, ReviewDecision


class NinaIgorChain:
    """Terminal decision boundary: NINA proposes, IGOR verifies, human confirms."""

    @staticmethod
    def finalize(nina_status: str, igor_status: str, review: ReviewDecision):
        if nina_status != "VERIFIED":
            return {"status": "BLOCK", "reason": f"nina status is {nina_status}"}
        if igor_status == "UNKNOWN":
            return {"status": "BLOCK", "reason": "igor verification is UNKNOWN"}
        if igor_status != "VERIFIED":
            return {"status": "BLOCK", "reason": f"igor verification is {igor_status}"}
        gate = HumanGate.evaluate(igor_status, review)
        return {"status": gate.status, "reason": gate.reason}
