"""Regression: Stripe status retrieval cannot accept caller-chosen URL components."""
import io
import http.client

import pytest

from app import revenue


def test_malformed_checkout_session_rejected_before_network(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_local_only")
    lookups = []
    monkeypatch.setattr(
        revenue.urllib.request, "urlopen",
        lambda *a, **kw: lookups.append((a, kw)) or io.BytesIO(b'{}'),
    )
    with pytest.raises(ValueError, match="Checkout Session"):
        revenue.retrieve_checkout("cs_test_valid@evil.invalid/?foo=bar")
    assert lookups == []


def test_session_request_uses_constant_stripe_host_without_redirects(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_local_only")
    requests = []

    class FakeStripeConnection:
        def __init__(self, host, timeout):
            requests.append(("host", host, timeout))

        def request(self, method, path, headers=None):
            requests.append(("request", method, path, headers))

        def getresponse(self):
            class Response:
                status = 200

                def read(self):
                    return b'{"id":"cs_test_valid123"}'
            return Response()

        def close(self):
            requests.append(("close",))

    def old_request_must_not_run(*_args, **_kwargs):
        pytest.fail("unsafe generic URL opener used for Stripe retrieval")

    monkeypatch.setattr(http.client, "HTTPSConnection", FakeStripeConnection)
    monkeypatch.setattr(revenue.urllib.request, "urlopen", old_request_must_not_run)
    result = revenue.retrieve_checkout("cs_test_valid123")
    assert result["id"] == "cs_test_valid123"
    assert requests[0] == ("host", "api.stripe.com", 30)
    assert requests[1][0:3] == ("request", "GET", "/v1/checkout/sessions/cs_test_valid123")
    assert requests[-1] == ("close",)
