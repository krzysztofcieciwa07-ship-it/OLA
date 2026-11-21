import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import approval_identity as ai


@pytest.fixture(scope="module")
def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key()
    numbers = public.public_numbers()
    def b64int(n):
        raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    jwk = {"kty": "RSA", "kid": "fixture-kid", "use": "sig", "alg": "RS256",
           "n": b64int(numbers.n), "e": b64int(numbers.e)}
    return private, public, jwk


@pytest.fixture
def env():
    return {
        "OLA_APPROVAL_OIDC_ISSUER": "https://id.example.test/issuer",
        "OLA_APPROVAL_OIDC_AUDIENCE": "ola-api",
        "OLA_APPROVAL_OIDC_JWKS_URL": "https://id.example.test/issuer/jwks",
        "OLA_APPROVAL_OIDC_JWKS_HOST_ALLOWLIST": "id.example.test",
        "OLA_APPROVAL_OIDC_TENANT_CLAIM": "ola_tenant_id",
    }


def token(key, **overrides):
    now = int(time.time())
    payload = {
        "iss": "https://id.example.test/issuer",
        "aud": "ola-api",
        "sub": "person-123",
        "ola_tenant_id": "tenant-abc",
        "iat": now,
        "exp": now + 60,
    }
    payload.update(overrides)
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "fixture-kid"})


def mock_fetch(monkeypatch, jwk):
    payload = {"keys": [jwk]}
    monkeypatch.setattr(ai, "_get_jwks", lambda url, force_refresh=False: payload)


def test_verified_subject_signature_and_claims(monkeypatch, env, keypair):
    mock_fetch(monkeypatch, keypair[2])
    result = ai.verify_subject_token(token(keypair[0]), environ=env)
    assert result == ai.VerifiedSubject("https://id.example.test/issuer", "person-123", "tenant-abc")


def test_bad_signature_rejected(monkeypatch, env, keypair):
    mock_fetch(monkeypatch, keypair[2])
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ai.ApprovalIdentityError):
        ai.verify_subject_token(token(wrong), environ=env)


@pytest.mark.parametrize("override", [
    {"iss": "https://evil.example.test/issuer"},
    {"aud": "other"},
    {"exp": int(time.time()) - 1},
    {"sub": ""},
    {"ola_tenant_id": ""},
    {"sub": 123},
    {"ola_tenant_id": 123},
])
def test_invalid_claims_fail_closed(monkeypatch, env, keypair, override):
    mock_fetch(monkeypatch, keypair[2])
    with pytest.raises(ai.ApprovalIdentityError):
        ai.verify_subject_token(token(keypair[0], **override), environ=env)


def test_missing_required_claim_rejected(monkeypatch, env, keypair):
    mock_fetch(monkeypatch, keypair[2])
    payload = {"iss": env["OLA_APPROVAL_OIDC_ISSUER"], "aud": env["OLA_APPROVAL_OIDC_AUDIENCE"],
               "sub": "person-123", "ola_tenant_id": "tenant-abc", "exp": int(time.time()) + 60}
    missing_iat = jwt.encode(payload, keypair[0], algorithm="RS256", headers={"kid": "fixture-kid"})
    with pytest.raises(ai.ApprovalIdentityError):
        ai.verify_subject_token(missing_iat, environ=env)


def test_non_rs256_header_rejected(monkeypatch, env):
    payload = {"iss": env["OLA_APPROVAL_OIDC_ISSUER"], "aud": env["OLA_APPROVAL_OIDC_AUDIENCE"],
               "sub": "person-123", "ola_tenant_id": "tenant-abc", "iat": int(time.time()),
               "exp": int(time.time()) + 60}
    token_hs = jwt.encode(payload, "test-only-secret-key-with-32-bytes-minimum", algorithm="HS256")
    monkeypatch.setattr(ai, "_get_jwks", lambda *a, **k: pytest.fail("JWKS must not be called"))
    with pytest.raises(ai.ApprovalIdentityError):
        ai.verify_subject_token(token_hs, environ=env)


def test_missing_config_blocks(monkeypatch):
    monkeypatch.setattr(ai, "_get_jwks", lambda *a, **k: pytest.fail("JWKS must not be called"))
    with pytest.raises(ai.ApprovalIdentityError):
        ai.verify_subject_token("x", environ={})


@pytest.mark.parametrize("bad_url", [
    "http://id.example.test/jwks",
    "https://evil.example.test/jwks",
    "https://id.example.test:8443/jwks",
    "https://user@id.example.test/jwks",
    "https://id.example.test/jwks?redirect=1",
])
def test_jwks_url_not_allowlisted_blocks(monkeypatch, env, bad_url):
    env = dict(env, OLA_APPROVAL_OIDC_JWKS_URL=bad_url)
    monkeypatch.setattr(ai, "_get_jwks", lambda *a, **k: pytest.fail("JWKS must not be called"))
    with pytest.raises(ai.ApprovalIdentityError):
        ai.verify_subject_token("x", environ=env)


def test_oversized_token_rejected(monkeypatch, env):
    monkeypatch.setattr(ai, "_get_jwks", lambda *a, **k: pytest.fail("JWKS must not be called"))
    with pytest.raises(ai.ApprovalIdentityError):
        ai.verify_subject_token("x" * 8193, environ=env)


def test_invalid_tenant_claim_name_blocks(monkeypatch, env):
    env = dict(env, OLA_APPROVAL_OIDC_TENANT_CLAIM="bad.claim")
    monkeypatch.setattr(ai, "_get_jwks", lambda *a, **k: pytest.fail("JWKS must not be called"))
    with pytest.raises(ai.ApprovalIdentityError):
        ai.verify_subject_token("x", environ=env)


def test_ambiguous_or_wrong_jwk_rejected(monkeypatch, env, keypair):
    payload = {"keys": [keypair[2], keypair[2]]}
    monkeypatch.setattr(ai, "_get_jwks", lambda url, force_refresh=False: payload)
    with pytest.raises(ai.ApprovalIdentityError):
        ai.verify_subject_token(token(keypair[0]), environ=env)


def test_jwks_fetch_has_bounded_no_redirect_http_contract(monkeypatch):
    class Response:
        status_code = 200
        headers = {"content-length": "11"}
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def iter_bytes(self): yield b'{"keys":[]}'
    class Client:
        def __init__(self, *, timeout, follow_redirects, trust_env):
            assert timeout == 3.0 and follow_redirects is False and trust_env is False
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def stream(self, method, url):
            assert method == "GET" and url == "https://id.example.test/issuer/jwks"
            return Response()
    monkeypatch.setattr(ai.httpx, "Client", Client)
    assert ai._fetch_jwks("https://id.example.test/issuer/jwks") == {"keys": []}


def test_jwks_fetch_rejects_redirect(monkeypatch):
    class Response:
        status_code = 302
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def iter_bytes(self): yield b'{}'
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def stream(self, *args): return Response()
    monkeypatch.setattr(ai.httpx, "Client", Client)
    with pytest.raises(ai.ApprovalIdentityError):
        ai._fetch_jwks("https://id.example.test/issuer/jwks")


def test_jwks_fetch_rejects_oversize(monkeypatch):
    class Response:
        status_code = 200
        headers = {"content-length": "65537"}
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def iter_bytes(self): yield b'{}'
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def stream(self, *args): return Response()
    monkeypatch.setattr(ai.httpx, "Client", Client)
    with pytest.raises(ai.ApprovalIdentityError):
        ai._fetch_jwks("https://id.example.test/issuer/jwks")


def test_unknown_kid_refresh_is_bounded_to_one(monkeypatch, env, keypair):
    calls = []
    empty = {"keys": []}
    valid = {"keys": [keypair[2]]}
    def fake_get(url, force_refresh=False):
        calls.append(force_refresh)
        return valid if force_refresh else empty
    monkeypatch.setattr(ai, "_get_jwks", fake_get)
    result = ai.verify_subject_token(token(keypair[0]), environ=env)
    assert result.subject == "person-123"
    assert calls == [False, True]


def test_weak_rsa_key_is_rejected():
    weak = rsa.generate_private_key(public_exponent=65537, key_size=1024).public_key()
    numbers = weak.public_numbers()
    def b64int(n):
        raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    weak_jwk = {"kty": "RSA", "kid": "weak", "use": "sig", "alg": "RS256",
                "n": b64int(numbers.n), "e": b64int(numbers.e)}
    assert ai._key_for_kid({"keys": [weak_jwk]}, "weak") is None


@pytest.mark.parametrize("key_ops", [
    ["sign"],
    [],
    ["verify", "sign"],
    ["verify", "verify"],
    "verify",
])
def test_jwk_key_ops_must_be_verify_only(keypair, key_ops):
    candidate = dict(keypair[2], key_ops=key_ops)
    assert ai._key_for_kid({"keys": [candidate]}, "fixture-kid") is None


def test_jwk_verify_only_key_ops_is_accepted(keypair):
    candidate = dict(keypair[2], key_ops=["verify"])
    assert ai._key_for_kid({"keys": [candidate]}, "fixture-kid") is not None


@pytest.mark.parametrize("private_parameter", ["d", "p", "q", "dp", "dq", "qi", "oth"])
def test_jwk_private_rsa_material_is_rejected(keypair, private_parameter):
    candidate = dict(keypair[2], **{private_parameter: "private-material"})
    assert ai._key_for_kid({"keys": [candidate]}, "fixture-kid") is None
