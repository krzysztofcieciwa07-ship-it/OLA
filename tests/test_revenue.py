import pytest

from app.revenue import stripe_secret_key


def test_stripe_secret_key_accepts_test_mode_key(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_example")
    assert stripe_secret_key() == "sk_test_example"


@pytest.mark.parametrize("key", ["sk_live_example", "rk_live_example", ""])
def test_stripe_secret_key_rejects_live_or_missing_key(monkeypatch, key):
    monkeypatch.setenv("STRIPE_SECRET_KEY", key)
    with pytest.raises(RuntimeError):
        stripe_secret_key()


def test_stripe_secret_key_rejects_live_key_even_when_live_flag_is_set(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_example")
    monkeypatch.setenv("STRIPE_EXPECT_LIVEMODE", "true")
    with pytest.raises(RuntimeError):
        stripe_secret_key()


def test_create_checkout_sends_stable_stripe_idempotency_header(monkeypatch):
    import io
    import urllib.request

    from app.revenue import create_checkout

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_example")
    monkeypatch.setenv("OLA_STRIPE_PRICE_ID", "price_test_ola")
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"id":"cs_test_idempotent123","url":"https://checkout.stripe.test/session"}'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = create_checkout(
        "audit task",
        "http://localhost:8000/payment-success",
        "http://localhost:8000/",
        "tenant-test",
        idempotency_key="ola-checkout-order-123",
        order_id="order-123",
    )

    assert result["id"] == "cs_test_idempotent123"
    assert captured["request"].get_header("Idempotency-key") == "ola-checkout-order-123"
    from urllib.parse import parse_qs
    form = parse_qs(captured["request"].data.decode())
    assert form["client_reference_id"] == ["order-123"]
    assert form["metadata[order_id]"] == ["order-123"]
    assert captured["timeout"] == 30
