"""OIDC provider and ID-token policy contract for Human Identity."""
import importlib
from importlib.util import find_spec
from types import SimpleNamespace

import pytest


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
    "claim_overrides,algorithm,nonce",
    [
        ({"iss": "https://attacker.example"}, "RS256", "expected-one-time-nonce"),
        ({"aud": "another-client"}, "RS256", "expected-one-time-nonce"),
        ({"nonce": "replayed-or-mismatched"}, "RS256", "expected-one-time-nonce"),
        ({}, "none", "expected-one-time-nonce"),
        ({}, "HS256", "expected-one-time-nonce"),
        ({"exp": 1_800_000_099}, "RS256", "expected-one-time-nonce"),
        ({"iat": 1_800_000_200}, "RS256", "expected-one-time-nonce"),
        ({"exp": 1_800_000_000}, "RS256", "expected-one-time-nonce"),
        ({"sub": ""}, "RS256", "expected-one-time-nonce"),
    ],
)
def test_invalid_issuer_audience_algorithm_or_time_is_rejected(
    oidc_api, claim_overrides, algorithm, nonce
):
    with pytest.raises(oidc_api.OidcLoginRejected):
        oidc_api.validate_verified_id_token(
            _provider(),
            _claims(**claim_overrides),
            signing_algorithm=algorithm,
            nonce_verified=(nonce == "expected-one-time-nonce"),
            now=1_800_000_100,
        )


def test_nonce_must_have_been_validated_by_authlib_callback(oidc_api):
    with pytest.raises(oidc_api.OidcLoginRejected):
        oidc_api.validate_verified_id_token(
            _provider(),
            _claims(),
            signing_algorithm="RS256",
            nonce_verified=False,
            now=1_800_000_100,
        )


def test_multiple_audiences_require_exact_authorized_party(oidc_api):
    with pytest.raises(oidc_api.OidcLoginRejected):
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

    with pytest.raises(oidc_api.OidcLoginRejected):
        oidc_api.validate_verified_id_token(
            _provider(),
            _claims(auth_time=None),
            signing_algorithm="RS256",
            nonce_verified=True,
            now=1_800_000_100,
            require_step_up=True,
        )


def test_step_up_auth_time_must_be_fresh_and_not_in_the_future(oidc_api):
    with pytest.raises(oidc_api.OidcLoginRejected):
        oidc_api.validate_verified_id_token(
            _provider(),
            _claims(auth_time=1_800_000_000),
            signing_algorithm="RS256",
            nonce_verified=True,
            now=1_800_001_000,
            require_step_up=True,
            max_auth_age_seconds=300,
        )

    with pytest.raises(oidc_api.OidcLoginRejected):
        oidc_api.validate_verified_id_token(
            _provider(),
            _claims(auth_time=1_800_000_200),
            signing_algorithm="RS256",
            nonce_verified=True,
            now=1_800_000_100,
            require_step_up=True,
            max_auth_age_seconds=300,
        )
