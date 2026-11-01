"""Regression: Checkout Session lookup never accepts arbitrary URL components."""
import io
import http.client

import pytest

from app import revenue


def test_malformed_checkout_session_rejected_before_network(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_local_only")
    calls = []
    monkeypatch.setattr(
        revenue.urllib.request, "urlopen",
        lambda *a, **kw: calls.append(("unsafe", a, kw)) or io.BytesIO(b'{}'),
    )
    monkeypatch.setattr(
        revenue, "StripeClient",
        lambda *_: calls.append(("sdk",)) or object(),
    )
    with pytest.raises(ValueError, match="Checkout Session"):
        revenue.retrieve_checkout("cs_test_valid@evil.invalid/?foo=bar")
    assert calls == []


def test_session_retrieval_uses_only_pinned_official_stripe_sdk(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_local_only")
    calls = []

    class SessionService:
        def retrieve(self, session_id):
            calls.append(("retrieve", session_id))
            return {"id": session_id, "metadata": {"tenant_id": "test"}}

    class StripeClientMock:
        def __init__(self, api_key):
            calls.append(("client", api_key))
            self.v1 = type("V1", (), {})()
            self.v1.checkout = type("Checkout", (), {})()
            self.v1.checkout.sessions = SessionService()

    def unsafe_network(*_args, **_kwargs):
        pytest.fail("application must not build Stripe status network URLs")

    monkeypatch.setattr(revenue, "StripeClient", StripeClientMock)
    monkeypatch.setattr(revenue.urllib.request, "urlopen", unsafe_network)
    monkeypatch.setattr(http.client, "HTTPSConnection", unsafe_network)
    result = revenue.retrieve_checkout("cs_test_valid123")
    assert result["id"] == "cs_test_valid123"
    assert calls == [
        ("client", "sk_test_local_only"),
        ("retrieve", "cs_test_valid123"),
    ]
