"""Provider-neutral customer recipient authentication boundary.

The default adapter reuses the tenant's OIDC Human Identity session. External
passkey/WebAuthn providers may be injected later, but must resolve to an
already-provisioned OLA principal. They never supply roles or person_ref.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.human_identity.membership import (
    HumanMembershipRejected,
    require_human_operator,
    resolve_human_principal_context,
)


@dataclass(frozen=True)
class RecipientAuthentication:
    tenant_id: str
    principal_id: str
    auth_time: int
    mfa_verified: bool


@runtime_checkable
class RecipientAuthProvider(Protocol):
    def authenticate(self, request) -> RecipientAuthentication: ...


class OIDCRecipientAuthProvider:
    """Current working adapter: OIDC session with recipient role and fresh MFA."""

    def authenticate(self, request) -> RecipientAuthentication:
        context = require_human_operator(request, required_role="recipient", max_auth_age_seconds=300)
        if type(context.auth_time) is not int:
            raise HumanMembershipRejected(403, "recipient step-up authentication time is missing")
        return RecipientAuthentication(
            tenant_id=context.tenant_id,
            principal_id=context.principal_id,
            auth_time=context.auth_time,
            mfa_verified=context.mfa_verified,
        )


def authenticate_customer_recipient(request) -> object:
    """Authenticate using an injected provider, then re-resolve all OLA privileges."""
    provider = getattr(request.app.state, "customer_bundle_recipient_auth_provider", None)
    if provider is None:
        provider = OIDCRecipientAuthProvider()
    authenticate = getattr(provider, "authenticate", None)
    if not callable(authenticate):
        raise HumanMembershipRejected(503, "customer recipient authentication provider is invalid")
    try:
        authentication = authenticate(request)
    except HumanMembershipRejected:
        raise
    except Exception as exc:
        raise HumanMembershipRejected(401, "customer recipient authentication failed") from exc
    if not isinstance(authentication, RecipientAuthentication):
        raise HumanMembershipRejected(401, "recipient provider returned an invalid authentication context")
    if (
        not isinstance(authentication.tenant_id, str) or not authentication.tenant_id
        or not isinstance(authentication.principal_id, str) or not authentication.principal_id
        or type(authentication.auth_time) is not int
        or authentication.mfa_verified is not True
    ):
        raise HumanMembershipRejected(403, "recipient requires a valid principal and fresh MFA")
    now = int(time.time())
    if authentication.auth_time > now or now - authentication.auth_time > 300:
        raise HumanMembershipRejected(403, "fresh recipient MFA step-up is required")
    context = resolve_human_principal_context(
        tenant_id=authentication.tenant_id,
        principal_id=authentication.principal_id,
        auth_time=authentication.auth_time,
        mfa_verified=authentication.mfa_verified,
    )
    if "recipient" not in context.roles:
        raise HumanMembershipRejected(403, "active recipient membership is required")
    return context
