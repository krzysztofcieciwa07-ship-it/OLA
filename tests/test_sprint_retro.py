"""Sprint retro integration contract: same DAG runtime and independent IGOR."""
import threading
import uuid

import pytest

from app.main import append_record, read_tenant_evidence
from app.sprint_retro import run_sprint_retro, RetroBlocked


CYCLE = "cycle-test-2026w42"
START = "2026-10-05T00:00:00Z"
END = "2026-10-12T00:00:00Z"


def source_items():
    tickets = [
        {"id": f"LIN-{i}", "title": f"Task {i}", "url": f"https://linear.app/demo/issue/LIN-{i}",
         "outcome": "shipped" if i % 2 else "slipped",
         "cycle_time_hours": 12 * i, "rescoped": i == 3}
        for i in range(1, 5)
    ]
    messages = [
        {"url": f"https://app.slack.com/archives/C123/p172000000000000{i}",
         "text": ("blocked by API" if i == 1 else "nice shipped 🎉"),
         "reactions": ["tada"] if i > 1 else []}
        for i in range(1, 5)
    ]
    return tickets, messages


def compose(tickets, messages):
    linear = [t["url"] for t in tickets]
    slack = [m["url"] for m in messages]
    return {
        "went_well": [{"text": f"Shipped work referenced by {i}",
                        "refs": [linear[i % 4], slack[1]]} for i in range(3)],
        "dragged": [{"text": f"Investigate delay {i}",
                      "refs": [linear[(i + 1) % 4], slack[0]]} for i in range(3)],
        "try_next_sprint": [{"text": f"Try earlier escalation {i}",
                             "refs": [linear[i % 4], slack[0]]} for i in range(3)],
        "process_change": "Escalate blockers in the team channel within one working day",
        "confidence": 0.65,
    }


def test_one_markdown_document_parallel_sources_and_igor(monkeypatch):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "retro-ci-head")
    tickets, messages = source_items()
    barrier = threading.Barrier(2, timeout=4)

    def linear(cycle_id):
        assert cycle_id == CYCLE
        barrier.wait()
        return {"cycle_id": CYCLE, "closed": True, "tickets": tickets}

    def slack(channel, start, end):
        assert (channel, start, end) == ("C123", START, END)
        barrier.wait()
        return {"channel_id": "C123", "messages": messages}

    tenant = "retro-" + str(uuid.uuid4())
    out = run_sprint_retro(tenant_id=tenant, requester_id="requester",
        cycle_id=CYCLE, channel_id="C123", start=START, end=END,
        linear_reader=linear, slack_reader=slack, synthesizer=compose,
        append=append_record, fetch_records=read_tenant_evidence)
    assert out["status"] == "COMPLETED_UNVERIFIED"
    assert out["igor"]["status"] == "VERIFIED", out
    assert out["human_gate"] == "NOT_APPROVED"
    assert out["verified"] is False
    assert out["document"].count("## Went well") == 1
    assert out["document"].count("## Dragged") == 1
    assert out["document"].count("## Try next sprint") == 1
    assert out["document"].count("](https://") >= 9
    assert out["document_sha256"]
    assert out["igor"]["verified_nodes"] == 4


def test_missing_connectors_fail_closed_before_writes():
    writes = []
    with pytest.raises(RetroBlocked, match="connectors"):
        run_sprint_retro(tenant_id="test", requester_id="x", cycle_id=CYCLE,
            channel_id="C123", start=START, end=END,
            append=lambda *args: writes.append(args), fetch_records=lambda _: [])
    assert writes == []


@pytest.mark.parametrize("modify", ["not_closed", "fake_link", "missing_cycle"])
def test_bad_sources_or_uncited_claim_never_returns_document(monkeypatch, modify):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "retro-ci-head")
    tickets, messages = source_items()

    def linear(cycle_id):
        return {"cycle_id": "wrong" if modify == "missing_cycle" else CYCLE,
                "closed": modify != "not_closed", "tickets": tickets}

    def synth(t, m):
        output = compose(t, m)
        if modify == "fake_link":
            output["went_well"][0]["refs"] = ["https://linear.app/demo/issue/LIN-FAKE"]
        return output

    with pytest.raises(RetroBlocked):
        run_sprint_retro(tenant_id="retro-" + str(uuid.uuid4()),
            requester_id="requester", cycle_id=CYCLE, channel_id="C123",
            start=START, end=END, linear_reader=linear,
            slack_reader=lambda channel, start, end: {"channel_id": channel, "messages": messages},
            synthesizer=synth, append=append_record, fetch_records=read_tenant_evidence)


def test_document_never_promoted_when_igor_rejects_trace(monkeypatch):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "retro-ci-head")
    tickets, messages = source_items()
    with pytest.raises(RetroBlocked, match="IGOR"):
        run_sprint_retro(tenant_id="retro-" + str(uuid.uuid4()),
            requester_id="requester", cycle_id=CYCLE, channel_id="C123",
            start=START, end=END,
            linear_reader=lambda _: {"cycle_id": CYCLE, "closed": True, "tickets": tickets},
            slack_reader=lambda *_: {"channel_id": "C123", "messages": messages},
            synthesizer=compose, append=append_record,
            fetch_records=lambda _: [])
