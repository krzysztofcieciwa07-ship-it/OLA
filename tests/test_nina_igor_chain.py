from app.human_gate import HumanGate, ReviewDecision
from app.nina_igor import NinaIgorChain


def test_chain_blocks_when_igor_is_unknown():
    chain = NinaIgorChain()
    result = chain.finalize(
        nina_status="VERIFIED",
        igor_status="UNKNOWN",
        review=ReviewDecision(True, "reviewer-1", "reviewed"),
    )
    assert result["status"] == "BLOCK"
    assert result["reason"] == "igor verification is UNKNOWN"


def test_chain_requires_igor_before_human_gate():
    chain = NinaIgorChain()
    result = chain.finalize(
        nina_status="VERIFIED",
        igor_status="VERIFIED",
        review=ReviewDecision(True, "reviewer-1", "reviewed"),
    )
    assert result["status"] == "VERIFIED"


def test_chain_rejects_human_review():
    chain = NinaIgorChain()
    result = chain.finalize(
        nina_status="VERIFIED",
        igor_status="VERIFIED",
        review=ReviewDecision(False, "reviewer-1", "unsafe"),
    )
    assert result["status"] == "BLOCK"
