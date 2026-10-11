import io
import json
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app import revenue
from app.main import app


@pytest.mark.parametrize("session_id", [
    "", "..", "../charges", "cs_test_../charges", "cs_test_%2e%2e", "cs_test_a/b",
    "cs_test_a?expand[]=customer", "cs_test_a#fragment", "cs_test_a\\b", "cs_test_a\r\nX: y",
    "https://attacker.invalid/", "//attacker.invalid/", "cs_test_ą", "cs_test_a\n",
    "cs_" + "a" * 253, None, 1,
])
def test_malformed_session_is_rejected_before_secret_or_network(monkeypatch, session_id):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.setattr(revenue, "_stripe_open", lambda req: pytest.fail("network must not be reached"))
    with pytest.raises(revenue.InvalidCheckoutSessionId):
        revenue.retrieve_checkout(session_id)


@pytest.mark.parametrize("session_id", ["cs_test_ABC123", "cs_live_abc123", "cs_" + "a" * 252])
def test_valid_id_uses_fixed_stripe_endpoint(monkeypatch, session_id):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "fake-test-only-secret")
    requests = []
    def open_request(req):
        requests.append(req)
        return io.BytesIO(json.dumps({"id": session_id}).encode())
    monkeypatch.setattr(revenue, "_stripe_open", open_request)
    assert revenue.retrieve_checkout(session_id) == {"id": session_id}
    assert requests[0].full_url == "https://api.stripe.com/v1/checkout/sessions/" + session_id
    assert requests[0].get_method() == "GET"


def test_creation_preserves_stripe_payment_fields(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "fake-test-only-secret")
    monkeypatch.setenv("OLA_STRIPE_PRICE_ID", "price_test")
    requests = []
    def open_request(req):
        requests.append(req)
        return io.BytesIO(b'{"id":"cs_test_created"}')
    monkeypatch.setattr(revenue, "_stripe_open", open_request)
    assert revenue.create_checkout("a task", "https://ola.invalid/success", "https://ola.invalid/", "tenant-1")["id"] == "cs_test_created"
    assert requests[0].full_url == "https://api.stripe.com/v1/checkout/sessions"
    assert requests[0].get_method() == "POST"
    assert b"metadata%5Btenant_id%5D=tenant-1" in requests[0].data


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("destination", ["https://attacker.invalid/", "https://api.stripe.com/v1/other"])
def test_authenticated_stripe_requests_never_follow_redirects(code, destination):
    # Exercise the real urllib opener/redirect chain with an in-memory HTTPS
    # transport. A second request would forward the bearer credential.
    class Transport(urllib.request.HTTPSHandler):
        calls = 0
        def https_open(self, req):
            self.calls += 1
            response = urllib.response.addinfourl(io.BytesIO(b""), {"Location": destination}, req.full_url, code)
            response.msg = "Redirect"
            return response
    transport = Transport()
    opener = urllib.request.build_opener(revenue._NoStripeRedirects(), transport)
    request = urllib.request.Request("https://api.stripe.com/v1/checkout/sessions/cs_test_a",
                                     headers={"Authorization": "Bearer fake-test-only-secret"})
    with pytest.raises(urllib.error.HTTPError) as error:
        opener.open(request)
    assert error.value.code == code
    assert transport.calls == 1


def test_public_endpoint_returns_bad_request_for_invalid_session(monkeypatch):
    monkeypatch.setattr(revenue, "_stripe_open", lambda req: pytest.fail("network must not be reached"))
    response = TestClient(app).get("/payment-success", params={"session_id": "../charges"})
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid checkout session id"}
