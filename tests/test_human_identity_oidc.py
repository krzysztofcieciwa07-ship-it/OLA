"""OIDC provider and ID-token policy contract for Human Identity."""
import importlib
from importlib.util import find_spec
from types import SimpleNamespace

import pytest

from app.human_identity import oidc as _oidc_module


def test_human_identity_oidc_module_exists():
    assert find_spec("app.human_identity.oidc") is not None, (
        "OIDC operator adapter is missing"
    )


@pytest.fixture
def oidc_api():
    if find_spec("app.human_identity.oidc") is None:
        pytest.skip("OIDC operator adapter has not been implemented")
    return importlib.import_module("app.human_identity.oidc")


def _provider(**overrides):
    values = {
        "issuer": "https://identity.example.test",
        "client_id": "ola-operator-client",
        "mfa_acr_values_json": '["urn:ola:loa:2"]',
        "mfa_amr_values_json": '["otp","webauthn"]',
        "discovery_url": "https://identity.example.test/.well-known/openid-configuration",
        "client_secret_ref": "OIDC_TEST_CLIENT_SECRET",
        "redirect_uri": "https://ola.example.test/human/oidc/tenant-001/callback",
        "id_token_algorithm": "RS256",
        "enabled": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _claims(**overrides):
    values = {
        "iss": "https://identity.example.test",
        "sub": "subject-001",
        "aud": "ola-operator-client",
        "exp": 1_800_000_300,
        "iat": 1_800_000_000,
        "nonce": "expected-one-time-nonce",
        "auth_time": 1_800_000_000,
        "acr": "urn:ola:loa:2",
        "amr": ["pwd", "otp"],
    }
    values.update(overrides)
    return values


def test_valid_id_token_is_bound_to_issuer_audience_and_explicit_mfa(oidc_api):
    identity = oidc_api.validate_verified_id_token(
        _provider(),
        _claims(),
        signing_algorithm="RS256",
        nonce_verified=True,
        now=1_800_000_100,
    )

    assert identity.issuer == "https://identity.example.test"
    assert identity.subject == "subject-001"
    assert identity.auth_time == 1_800_000_000
    assert identity.mfa_verified is True


@pytest.mark.parametrize(
    "claim_overrides,algorithm",
    [
        ({"iss": "https://attacker.example"}, "RS256"),
        ({"aud": "another-client"}, "RS256"),
        ({}, "none"),
        ({}, "HS256"),
        ({"exp": 1_800_000_099}, "RS256"),
        ({"iat": 1_800_000_200}, "RS256"),
        ({"exp": 1_800_000_000}, "RS256"),
        ({"sub": ""}, "RS256"),
    ],
)
def test_invalid_issuer_audience_algorithm_or_time_is_rejected(
    oidc_api, claim_overrides, algorithm
):
    with pytest.raises(_oidc_module.OidcLoginRejected):
        oidc_api.validate_verified_id_token(
            _provider(),
            _claims(**claim_overrides),
            signing_algorithm=algorithm,
            nonce_verified=True,
            now=1_800_000_100,
        )


def test_nonce_must_have_been_validated_by_authlib_callback(oidc_api):
    with pytest.raises(_oidc_module.OidcLoginRejected):
        oidc_api.validate_verified_id_token(
            _provider(),
            _claims(),
            signing_algorithm="RS256",
            nonce_verified=False,
            now=1_800_000_100,
        )


def test_multiple_audiences_require_exact_authorized_party(oidc_api):
    with pytest.raises(_oidc_module.OidcLoginRejected):
        oidc_api.validate_verified_id_token(
            _provider(),
            _claims(aud=["ola-operator-client", "another-client"]),
            signing_algorithm="RS256",
            nonce_verified=True,
            now=1_800_000_100,
        )

    identity = oidc_api.validate_verified_id_token(
        _provider(),
        _claims(
            aud=["ola-operator-client", "another-client"],
            azp="ola-operator-client",
        ),
        signing_algorithm="RS256",
        nonce_verified=True,
        now=1_800_000_100,
    )
    assert identity.subject == "subject-001"


def test_mfa_is_false_unless_provider_policy_maps_acr_or_amr(oidc_api):
    identity = oidc_api.validate_verified_id_token(
        _provider(mfa_acr_values_json="[]", mfa_amr_values_json="[]"),
        _claims(acr="urn:vendor:password", amr=["pwd", "mfa"]),
        signing_algorithm="RS256",
        nonce_verified=True,
        now=1_800_000_100,
    )
    assert identity.mfa_verified is False


def test_auth_time_is_optional_for_normal_login_but_required_for_step_up(oidc_api):
    identity = oidc_api.validate_verified_id_token(
        _provider(),
        _claims(auth_time=None),
        signing_algorithm="RS256",
        nonce_verified=True,
        now=1_800_000_100,
        require_step_up=False,
    )
    assert identity.auth_time is None

    with pytest.raises(_oidc_module.OidcLoginRejected):
        oidc_api.validate_verified_id_token(
            _provider(),
            _claims(auth_time=None),
            signing_algorithm="RS256",
            nonce_verified=True,
            now=1_800_000_100,
            require_step_up=True,
        )


def test_step_up_auth_time_must_be_fresh_and_not_in_the_future(oidc_api):
    with pytest.raises(_oidc_module.OidcLoginRejected):
        oidc_api.validate_verified_id_token(
            _provider(),
            _claims(auth_time=1_800_000_000),
            signing_algorithm="RS256",
            nonce_verified=True,
            now=1_800_001_000,
            require_step_up=True,
            max_auth_age_seconds=300,
        )

    with pytest.raises(_oidc_module.OidcLoginRejected):
        oidc_api.validate_verified_id_token(
            _provider(),
            _claims(auth_time=1_800_000_200),
            signing_algorithm="RS256",
            nonce_verified=True,
            now=1_800_000_100,
            require_step_up=True,
            max_auth_age_seconds=300,
        )



def test_provider_config_is_tenant_bound_and_uses_exact_trusted_redirect():
    provider = _provider()
    config = _oidc_module.validate_provider_config(
        provider,
        tenant_id="tenant-001",
        deployment_profile="production",
        environ={"OLA_PUBLIC_BASE_URL": "https://ola.example.test"},
    )
    assert config["issuer"] == provider.issuer
    assert config["discovery_url"] == provider.discovery_url
    assert config["redirect_uri"] == provider.redirect_uri
    assert config["id_token_algorithm"] == "RS256"
    assert config["client_secret_ref"] == "OIDC_TEST_CLIENT_SECRET"


@pytest.mark.parametrize(
    "overrides,environ",
    [
        ({"issuer": "http://identity.example.test",
          "discovery_url": "http://identity.example.test/.well-known/openid-configuration"}, 
         {"OLA_PUBLIC_BASE_URL": "https://ola.example.test"}),
        ({"discovery_url": "https://attacker.example/.well-known/openid-configuration"},
         {"OLA_PUBLIC_BASE_URL": "https://ola.example.test"}),
        ({"redirect_uri": "https://attacker.example/callback"},
         {"OLA_PUBLIC_BASE_URL": "https://ola.example.test"}),
        ({"id_token_algorithm": "HS256"},
         {"OLA_PUBLIC_BASE_URL": "https://ola.example.test"}),
        ({"client_secret_ref": "../../secrets"},
         {"OLA_PUBLIC_BASE_URL": "https://ola.example.test"}),
        ({"enabled": False},
         {"OLA_PUBLIC_BASE_URL": "https://ola.example.test"}),
    ],
)
def test_untrusted_provider_issuer_redirect_or_secret_reference_is_rejected(overrides, environ):
    with pytest.raises(_oidc_module.OidcLoginRejected):
        _oidc_module.validate_provider_config(
            _provider(**overrides),
            tenant_id="tenant-001",
            deployment_profile="production",
            environ=environ,
        )


def test_secret_is_resolved_by_reference_not_stored_as_plaintext():
    secret = _oidc_module.resolve_client_secret(
        "OIDC_TEST_CLIENT_SECRET",
        environ={"OLA_SECRET_OIDC_TEST_CLIENT_SECRET": "secret-only-in-environment"},
    )
    assert secret == "secret-only-in-environment"
    with pytest.raises(_oidc_module.OidcLoginRejected):
        _oidc_module.resolve_client_secret(
            "OIDC_TEST_CLIENT_SECRET",
            environ={},
        )


def test_authlib_client_is_registered_with_openid_scope_and_pkce_s256():
    client, config = _oidc_module.create_oidc_client(
        _provider(),
        tenant_id="tenant-001",
        environ={
            "OLA_PUBLIC_BASE_URL": "https://ola.example.test",
            "OLA_SECRET_OIDC_TEST_CLIENT_SECRET": "test-secret-not-persisted",
        },
    )
    assert callable(client.authorize_redirect)
    assert callable(client.authorize_access_token)
    assert config["redirect_uri"] == "https://ola.example.test/human/oidc/tenant-001/callback"
