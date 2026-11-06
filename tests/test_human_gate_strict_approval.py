from app.human_gate import HumanGate, ReviewDecision


def test_false_string_never_authorizes():
    result = HumanGate.evaluate("VERIFIED", ReviewDecision("false", "reviewer", ""))
    assert result.status == "BLOCK"


def test_truthy_integer_never_authorizes():
    result = HumanGate.evaluate("VERIFIED", ReviewDecision(1, "reviewer", ""))
    assert result.status == "BLOCK"


def test_missing_or_invalid_actor_blocks():
    for actor in ("", "  ", None, 123):
        result = HumanGate.evaluate("VERIFIED", ReviewDecision(True, actor, ""))
        assert result.status == "BLOCK"


def test_unverified_candidate_cannot_be_promoted():
    result = HumanGate.evaluate("UNKNOWN", ReviewDecision(True, "reviewer", ""))
    assert result.status == "BLOCK"


def test_explicit_valid_approval():
    result = HumanGate.evaluate("VERIFIED", ReviewDecision(True, "reviewer", ""))
    assert result.status == "VERIFIED"


def test_invalid_review_object_blocks():
    assert HumanGate.evaluate("VERIFIED", None).status == "BLOCK"
