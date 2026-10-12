from app.execution_safety_gate import ExecutionSafetyGate


def test_unknown_risk_never_executes():
    effects = []
    gate = ExecutionSafetyGate({"send"})
    for risk in ("BLOCK", "MEDIUM", "", None, 4):
        decision = gate.execute(agent_id="NINA", action="send", effect=lambda: effects.append("executed"), risk=risk, human_approved=True)
        assert decision.status == "BLOCK"
    assert effects == []


def test_high_risk_requires_approval():
    effects = []
    gate = ExecutionSafetyGate({"send"})
    decision = gate.execute(agent_id="NINA", action="send", effect=lambda: effects.append(1), risk="HIGH")
    assert decision.status == "REVIEW"
    assert effects == []


def test_unknown_action_stays_blocked_even_if_approved():
    effects = []
    decision = ExecutionSafetyGate().execute(agent_id="NINA", action="send", effect=lambda: effects.append(1), risk="HIGH", human_approved=True)
    assert decision.status == "BLOCK"
    assert effects == []
