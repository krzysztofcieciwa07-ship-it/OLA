from app.human_gate import HumanGate, ReviewDecision


def test_verified_candidate_requires_explicit_review():
    result = HumanGate.evaluate("VERIFIED", ReviewDecision(True, "reviewer-1", "reviewed"))
    assert result.status == "VERIFIED"


def test_review_cannot_promote_unknown():
    result = HumanGate.evaluate("UNKNOWN", ReviewDecision(True, "reviewer-1", "reviewed"))
    assert result.status == "BLOCK"


def test_rejection_blocks():
    result = HumanGate.evaluate("VERIFIED", ReviewDecision(False, "reviewer-1", "rejected"))
    assert result.status == "BLOCK"
