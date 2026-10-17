"""Contract tests: Intercom -> parallel repro + code search -> IGOR -> Jira handoff."""
import hashlib
import threading
import uuid

import pytest

from app.main import append_record, read_tenant_evidence
from app.support_escalator import EscalationBlocked, run_support_escalation, publish_escalation


def conversation():
    return {
        "id": "conv-4512",
        "url": "https://app.intercom.com/a/inbox/demo/inbox/shared/all/conversation/conv-4512",
        "customer": {"plan_tier": "Team"},
        "subject": "Checkout endpoint fails on expired token",
        "description": "Customer reports a 500 instead of the expected 401.",
        "environment": {"os": "Windows 11", "app_version": "1.4.2"},
        "steps": ["POST /api/checkout with an expired token", "Inspect status code"],
        "support_notes": "Confirmed a customer-impacting issue; logs stored separately",
        "attachments": [{"kind": "log", "sha256": hashlib.sha256(b"log bytes").hexdigest()}],
    }


def repro(_):
    return {
        "reproduced": True, "attempts": ["pytest -q tests/test_checkout_expired.py"],
        "trigger": "POST /api/checkout with expired test token",
        "expected": "401", "observed": "500",
        "environment": "isolated-container", "evidence_sha256": hashlib.sha256(b"repro-log").hexdigest(),
    }


def code_search(_):
    return {
        "component": "app/checkout.py",
        "refs": [{"url": "https://github.com/example/OLA/blob/abc123/app/checkout.py#L42",
                  "path": "app/checkout.py"}],
    }


def test_bounded_parallel_repro_and_code_search_with_igor(monkeypatch):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "escalator-test-sha")
    barrier = threading.Barrier(2, timeout=3)
    touched = []

    def reproduce(c):
        touched.append("repro")
        barrier.wait()
        return repro(c)

    def search(c):
        touched.append("search")
        barrier.wait()
        return code_search(c)

    tenant = "escalation-" + str(uuid.uuid4())
    result = run_support_escalation(
        tenant_id=tenant, requester_id="support-agent",
        conversation_id="conv-4512", intercom_reader=lambda cid: conversation(),
        repro_runner=reproduce, code_searcher=search,
        append=append_record, fetch_records=read_tenant_evidence)
    assert sorted(touched) == ["repro", "search"]
    assert result["status"] == "REPRODUCED_DRAFT_UNAPPROVED"
    assert result["igor"]["status"] == "VERIFIED", result
    assert result["igor"]["parallel_overlap_ns"] > 0
    assert result["human_gate"] == "NOT_APPROVED"
    assert result["production_authorized"] is False
    assert result["jira_draft"]["summary"]
    assert "conv-4512" in result["jira_draft"]["description"]
    assert "pytest -q" in result["jira_draft"]["description"]
    assert result["correlation_id"].startswith("ola-support-escalation-")
    assert result["jira_draft"]["suspected_component"] == "app/checkout.py"


def test_cannot_reproduce_reports_attempts_and_never_files(monkeypatch):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "escalator-test-sha")
    submitted = []
    tenant = "escalation-" + str(uuid.uuid4())
    result = run_support_escalation(
        tenant_id=tenant, requester_id="support-agent", conversation_id="conv-4512",
        intercom_reader=lambda cid: conversation(),
        repro_runner=lambda _: {"reproduced": False, "attempts": ["pytest -q tests/test_checkout_expired.py"],
                                "observed": "cannot reproduce under test fixture"},
        code_searcher=code_search, append=append_record,
        fetch_records=read_tenant_evidence)
    assert result["status"] == "CANNOT_REPRODUCE"
    assert result["tried"] == ["pytest -q tests/test_checkout_expired.py"]
    assert result["jira_draft"] is None
    with pytest.raises(EscalationBlocked):
        publish_escalation(result, authorized=True, jira_create_or_get=lambda *a: submitted.append(a))
    assert not submitted


def test_missing_intercom_or_repro_provider_blocks_before_evidence():
    writes = []
    with pytest.raises(EscalationBlocked, match="connectors"):
        run_support_escalation(tenant_id="t", requester_id="agent",
            conversation_id="conv-4512", append=lambda *a: writes.append(a),
            fetch_records=lambda t: [])
    assert writes == []


def test_no_external_writes_without_authorization(monkeypatch):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "escalator-test-sha")
    result = run_support_escalation(
        tenant_id="escalation-" + str(uuid.uuid4()), requester_id="support",
        conversation_id="conv-4512", intercom_reader=lambda _: conversation(),
        repro_runner=repro, code_searcher=code_search,
        append=append_record, fetch_records=read_tenant_evidence)
    called = []
    with pytest.raises(EscalationBlocked, match="authorization"):
        publish_escalation(result, jira_create_or_get=lambda *a: called.append(a),
                           slack_post_once=lambda *a: called.append(a),
                           intercom_note_once=lambda *a: called.append(a),
                           intercom_mark_once=lambda *a: called.append(a))
    assert called == []


def test_authorized_publish_is_idempotent_and_ordered(monkeypatch):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "escalator-test-sha")
    candidate = run_support_escalation(
        tenant_id="escalation-" + str(uuid.uuid4()), requester_id="support",
        conversation_id="conv-4512", intercom_reader=lambda _: conversation(),
        repro_runner=repro, code_searcher=code_search,
        append=append_record, fetch_records=read_tenant_evidence)
    events = []
    def jira(key, fields):
        events.append(("jira", key))
        return {"key": "ENG-381", "url": "https://demo.atlassian.net/browse/ENG-381"}
    def slack(key, payload):
        events.append(("slack", key))
        return {"id": "C123/abc"}
    def note(key, payload):
        events.append(("note", key))
        return {"id": "note-123"}
    def mark(key, payload):
        events.append(("mark", key))
        return {"status": "escalated"}
    result = publish_escalation(candidate, authorized=True, jira_create_or_get=jira,
        slack_post_once=slack, intercom_note_once=note, intercom_mark_once=mark)
    assert result["status"] == "ESCALATED_RECORDED_UNATTESTED"
    assert [ev[0] for ev in events] == ["jira", "slack", "note", "mark"]
    assert all(ev[1].startswith(candidate["correlation_id"]) for ev in events)
    assert result["jira"]["key"] == "ENG-381"


@pytest.mark.parametrize("modify", ["id", "link", "attempts", "trigger"])
def test_invalid_source_or_repro_proof_fails_closed(monkeypatch, modify):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "escalator-test-sha")
    conv = conversation()
    outcome = repro(None)
    if modify == "id":
        conv["id"] = "other"
    elif modify == "link":
        conv["url"] = "http://example.com/fake"
    elif modify == "attempts":
        outcome["attempts"] = []
    else:
        outcome["trigger"] = ""
    with pytest.raises(EscalationBlocked):
        run_support_escalation(tenant_id="escalation-" + str(uuid.uuid4()),
            requester_id="support", conversation_id="conv-4512",
            intercom_reader=lambda _: conv, repro_runner=lambda _: outcome,
            code_searcher=code_search, append=append_record,
            fetch_records=read_tenant_evidence)


def test_igor_missing_records_never_returns_candidate(monkeypatch):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "escalator-test-sha")
    with pytest.raises(EscalationBlocked, match="IGOR"):
        run_support_escalation(tenant_id="escalation-" + str(uuid.uuid4()),
            requester_id="support", conversation_id="conv-4512",
            intercom_reader=lambda _: conversation(), repro_runner=repro,
            code_searcher=code_search, append=append_record,
            fetch_records=lambda _: [])
