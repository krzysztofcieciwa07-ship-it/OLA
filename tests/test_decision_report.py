from app.decision_report import build_decision_report, evaluate_policy


def test_unknown_never_becomes_verified():
    result = evaluate_policy(
        nina_status="VERIFIED",
        igor_status="UNKNOWN",
        evidence_count=6,
        replay_status="VERIFIED",
        human_approved=True,
    )
    assert result.status == "BLOCK"


def test_policy_requires_replay():
    result = evaluate_policy(
        nina_status="VERIFIED",
        igor_status="VERIFIED",
        evidence_count=6,
        replay_status="UNKNOWN",
        human_approved=True,
    )
    assert result.status == "BLOCK"


def test_policy_candidate_is_verified_independently_of_human_gate():
    result = evaluate_policy(
        nina_status="VERIFIED",
        igor_status="VERIFIED",
        evidence_count=6,
        replay_status="PASS",
        human_approved=False,
    )
    assert result.status == "VERIFIED"


def test_report_is_sealed_with_sha256():
    report = build_decision_report(
        task_id="task-1",
        run_id="run-1",
        task="Calculate 17 * 23",
        nina={"status": "VERIFIED"},
        igor={"status": "VERIFIED"},
        replay={"status": "VERIFIED"},
        human_gate={"status": "BLOCK"},
        evidence_ids=["e1", "e2"],
        human_approved=False,
        human_actor="",
        human_reason="pending owner review",
    )
    assert report["schema"] == "ola.decision-report.v1"
    assert report["policy"]["status"] == "VERIFIED"
    assert len(report["report_sha256"]) == 64


def test_paid_decision_report_binds_order_id_before_sealing_digest():
    import hashlib
    from app.hashchain import canonical_json

    report = build_decision_report(
        task_id="task-paid-1",
        run_id="run-paid-1",
        task="Calculate a customer-approved amount",
        nina={"status": "VERIFIED"},
        igor={"status": "VERIFIED"},
        replay={"status": "VERIFIED"},
        human_gate={"status": "REVIEW"},
        evidence_ids=["e1", "e2"],
        human_approved=False,
        human_actor="pending-human-approval",
        human_reason="awaiting separate reviewer",
        order_id="order-paid-1",
    )
    body = dict(report)
    digest = body.pop("report_sha256")
    assert body["order_id"] == "order-paid-1"
    assert digest == hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
