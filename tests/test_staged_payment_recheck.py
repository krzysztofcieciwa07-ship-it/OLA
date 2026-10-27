"""Operator-only Stripe snapshot before manual release; never delivery approval."""
import copy
import uuid

import pytest

from app import payment_recheck as check
from tests.test_delivery_artifacts import _setup, _stage
from tests.test_signed_delivery_reservation import _records, tenant_id


def _fixtures(tenant_id, tmp_path, monkeypatch, *, stage=True):
    manifest, reservation_id, file = _setup(tenant_id, tmp_path, monkeypatch)
    if stage:
        assert _stage(manifest, reservation_id, dry_run=False)["status"] == (
            "STAGED_AWAITING_PAYMENT_RECHECK"
        )
    monkeypatch.setenv("OLA_STRIPE_EXPECT_LIVEMODE", "0")
    session = {
        "id": manifest["session_id"], "object": "checkout.session",
        "status": "complete", "payment_status": "paid", "mode": "payment",
        "livemode": False, "currency": "eur", "amount_total": 9900,
        "payment_intent": "pi_test_123",
        "metadata": {"tenant_id": tenant_id, "task": "Audit this workflow",
                     "offer": "ola-execution-audit", "product": "OLA Execution Audit"},
    }
    intent = {
        "id": "pi_test_123", "object": "payment_intent", "status": "succeeded",
        "livemode": False, "currency": "eur", "amount_received": 9900,
        "latest_charge": "ch_test_123",
    }
    charge = {
        "id": "ch_test_123", "object": "charge", "payment_intent": "pi_test_123",
        "livemode": False, "currency": "eur", "amount": 9900,
        "amount_captured": 9900, "captured": True, "paid": True,
        "status": "succeeded", "refunded": False,
        "amount_refunded": 0, "disputed": False,
    }
    refunds = {"object": "list", "has_more": False, "data": []}
    disputes = {"object": "list", "has_more": False, "data": []}
    calls = []
    state = {"session": session, "payment_intents/pi_test_123": intent,
             "charges/ch_test_123": charge,
             "refunds?payment_intent=pi_test_123&limit=1": refunds,
             "disputes?payment_intent=pi_test_123&limit=1": disputes}

    def retrieve(session_id):
        calls.append(("checkout", session_id))
        return copy.deepcopy(state["session"])

    def get(path):
        calls.append(("get", path))
        return copy.deepcopy(state[path])

    monkeypatch.setattr(check, "retrieve_checkout", retrieve)
    monkeypatch.setattr(check, "_stripe_get", get)
    return manifest, reservation_id, file, state, calls


def _inspect(manifest, rid, *, tenant=None):
    return check.inspect_staged_payment(
        tenant or manifest["tenant_id"], manifest["session_id"], rid,
        "audit-report.pdf", manifest["recipient_sha256"],
    )


def test_clean_provider_snapshot_only_recommends_manual_review(
    tenant_id, tmp_path, monkeypatch,
):
    manifest, rid, _, _, calls = _fixtures(tenant_id, tmp_path, monkeypatch)
    before = len(_records(tenant_id))

    result = _inspect(manifest, rid)

    assert result == {
        "status": "PROVIDER_SNAPSHOT_CLEAR_MANUAL_REVIEW",
        "delivery_authorized": False, "payment_rechecked": False,
        "delivery_sent": False, "reservation_id": rid,
    }
    assert len(calls) == 5
    assert len(_records(tenant_id)) == before


@pytest.mark.parametrize("stage,wrong_tenant", [(False, False), (True, True)])
def test_unstaged_or_wrong_tenant_order_cannot_contact_stripe(
    tenant_id, tmp_path, monkeypatch, stage, wrong_tenant,
):
    manifest, rid, _, _, calls = _fixtures(
        tenant_id, tmp_path, monkeypatch, stage=stage,
    )
    result = _inspect(manifest, rid, tenant=str(uuid.uuid4()) if wrong_tenant else None)
    assert result["status"] == "BLOCKED"
    assert calls == []


@pytest.mark.parametrize("section,key,value", [
    ("session", "id", "cs_another"),
    ("session", "payment_status", "unpaid"),
    ("session", "amount_total", 1),
    ("session", "payment_intent", None),
    ("payment_intents/pi_test_123", "status", "processing"),
    ("payment_intents/pi_test_123", "amount_received", 9800),
    ("charges/ch_test_123", "paid", False),
    ("charges/ch_test_123", "captured", False),
    ("charges/ch_test_123", "disputed", True),
    ("charges/ch_test_123", "refunded", True),
    ("charges/ch_test_123", "amount_refunded", 100),
    ("charges/ch_test_123", "payment_intent", "pi_other"),
])
def test_provider_identity_or_payment_problem_blocks(
    tenant_id, tmp_path, monkeypatch, section, key, value,
):
    manifest, rid, _, state, _ = _fixtures(tenant_id, tmp_path, monkeypatch)
    state[section][key] = value
    assert _inspect(manifest, rid)["status"] == "BLOCKED"


@pytest.mark.parametrize("section", [
    "refunds?payment_intent=pi_test_123&limit=1",
    "disputes?payment_intent=pi_test_123&limit=1",
])
def test_any_refund_or_dispute_blocks_even_if_charge_snapshot_is_clean(
    tenant_id, tmp_path, monkeypatch, section,
):
    manifest, rid, _, state, _ = _fixtures(tenant_id, tmp_path, monkeypatch)
    state[section]["data"] = [{"id": "blocked_request"}]
    assert _inspect(manifest, rid)["status"] == "BLOCKED"


def test_incomplete_provider_list_is_not_treated_as_empty(
    tenant_id, tmp_path, monkeypatch,
):
    manifest, rid, _, state, _ = _fixtures(tenant_id, tmp_path, monkeypatch)
    state["refunds?payment_intent=pi_test_123&limit=1"]["has_more"] = True
    assert _inspect(manifest, rid)["status"] == "BLOCKED"


def test_provider_error_and_unknown_livemode_fail_closed(
    tenant_id, tmp_path, monkeypatch,
):
    manifest, rid, _, _, calls = _fixtures(tenant_id, tmp_path, monkeypatch)
    monkeypatch.delenv("OLA_STRIPE_EXPECT_LIVEMODE")
    assert _inspect(manifest, rid)["status"] == "BLOCKED"
    assert calls == []
    monkeypatch.setenv("OLA_STRIPE_EXPECT_LIVEMODE", "0")
    monkeypatch.setattr(check, "retrieve_checkout", lambda _: 1 / 0)
    assert _inspect(manifest, rid)["status"] == "BLOCKED"
