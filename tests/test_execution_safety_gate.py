import pytest


def test_unknown_action_is_blocked_without_side_effect():
    from app.execution_safety_gate import ExecutionSafetyGate

    gate = ExecutionSafetyGate()
    effects = []

    decision = gate.execute(
        agent_id="agent-001",
        action="delete_external_data",
        effect=lambda: effects.append("MUST_NOT_RUN"),
    )

    assert decision.status == "BLOCK"
    assert decision.policy == "deny-by-default"
    assert decision.side_effect_count == 0
    assert effects == []


def test_high_risk_action_requires_human_owner():
    from app.execution_safety_gate import ExecutionSafetyGate

    gate = ExecutionSafetyGate()
    effects = []

    decision = gate.execute(
        agent_id="agent-001",
        action="send_external_message",
        effect=lambda: effects.append("MUST_NOT_RUN"),
        risk="HIGH",
        human_approved=False,
    )

    assert decision.status == "REVIEW"
    assert decision.required_approval == "HUMAN_OWNER"
    assert decision.side_effect_count == 0
    assert effects == []


def test_explicitly_allowed_action_executes_once_and_is_observable():
    from app.execution_safety_gate import ExecutionSafetyGate

    gate = ExecutionSafetyGate(allowed_actions={"read_local_evidence"})
    effects = []

    decision = gate.execute(
        agent_id="agent-001",
        action="read_local_evidence",
        effect=lambda: effects.append("EXECUTED") or "evidence",
    )

    assert decision.status == "ALLOW"
    assert decision.side_effect_count == 1
    assert effects == ["EXECUTED"]
    assert decision.result == "evidence"
