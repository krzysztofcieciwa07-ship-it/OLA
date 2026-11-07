import json

import http.client
import pytest

from app import revenue


class FakeResponse:
    status = 200

    def read(self):
        return json.dumps({"id": "cs_test_abc123", "livemode": False}).encode()


class FakeConnection:
    def __init__(self, host, timeout):
        self.host = host
        self.timeout = timeout
        self.request_args = None
        self.closed = False
        instances.append(self)

    def request(self, method, path, headers):
        self.request_args = (method, path, headers)

    def getresponse(self):
        return FakeResponse()

    def close(self):
        self.closed = True


instances = []


def test_retrieve_checkout_uses_fixed_stripe_host_and_validated_path(monkeypatch):
    instances.clear()
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_example")
    monkeypatch.setattr(http.client, "HTTPSConnection", FakeConnection)

    result = revenue.retrieve_checkout("cs_test_abc123")

    assert result == {"id": "cs_test_abc123", "livemode": False}
    connection = instances[-1]
    assert connection.host == "api.stripe.com"
    assert connection.timeout == 30
    method, path, headers = connection.request_args
    assert method == "GET"
    assert path == "/v1/checkout/sessions/cs_test_abc123?expand%5B%5D=line_items"
    assert headers == {"Authorization": "Bearer sk_test_example"}
    assert connection.closed is True


@pytest.mark.parametrize(
    "session_id",
    [
        "https://attacker.example/cs_test_abc123",
        "cs_live_abc123",
        "cs_test_abc/123",
        "cs_test_abc?next=https://attacker.example",
        None,
        123,
    ],
)
def test_retrieve_checkout_rejects_untrusted_session_path(monkeypatch, session_id):
    instances.clear()
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_example")
    monkeypatch.setattr(http.client, "HTTPSConnection", FakeConnection)

    with pytest.raises(ValueError):
        revenue.retrieve_checkout(session_id)

    assert instances == []
