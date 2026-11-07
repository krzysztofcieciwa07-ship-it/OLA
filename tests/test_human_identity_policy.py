"""Regression contract for the persistent Human Gate identity policy."""
from importlib.util import find_spec


def test_human_identity_policy_module_exists_before_human_gate_wiring():
    spec = find_spec("app.human_identity.policy")
    assert spec is not None, (
        "Human Gate still has no persistent identity-policy module; "
        "do not wire OIDC until the downgrade-resistant policy exists"
    )
