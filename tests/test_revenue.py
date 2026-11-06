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
