"""Offline contract primitives for OLA Signed Approval Record v1.

This module is deliberately NOT wired into an API route, database model, worker,
or production signer. It defines deterministic bytes and fail-closed semantic
checks so implementation can be independently reviewed before any migration.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import unicodedata
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from urllib.parse import urlsplit

DOMAIN_SEPARATOR = b"OLA-SIGNED-APPROVAL\x00v1\x00"
IDENTITY_DOMAIN = b"OLA-OIDC-SUBJECT-FINGERPRINT\x00v1\x00"
SESSION_DOMAIN = b"OLA-OIDC-SESSION-FINGERPRINT\x00v1\x00"
MAX_CANONICAL_BYTES = 65_536
MAX_JSON_DEPTH = 16
MAX_JSON_NODES = 4_096
MAX_SAFE_INTEGER = (1 << 53) - 1
MAX_APPROVAL_TTL_SECONDS = 300
MAX_AUTH_AGE_SECONDS = 300
CLOCK_SKEW_SECONDS = 30
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
KEY_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class ApprovalContractError(ValueError):
    """The candidate approval payload violates the v1 contract."""


def _text(value: object, name: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ApprovalContractError(f"{name} is invalid")
    if unicodedata.normalize("NFC", value) != value:
        raise ApprovalContractError(f"{name} must be NFC-normalized")
    if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ApprovalContractError(f"{name} contains forbidden characters")
    return value


def _uuid(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ApprovalContractError(f"{name} must be a UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise ApprovalContractError(f"{name} must be a UUID") from None
    normalized = str(parsed)
    if value != normalized:
        raise ApprovalContractError(f"{name} must use canonical lowercase UUID form")
    return normalized


def _validate_https_issuer(value: object, name: str) -> str:
    value = _text(value, name, max_length=512)
    if any(char.isspace() for char in value):
        raise ApprovalContractError(f"{name} is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ApprovalContractError(f"{name} is invalid") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in (None, 443)
    ):
        raise ApprovalContractError(f"{name} must be an exact HTTPS issuer URL")
    return value


def _framed(parts: tuple[bytes, ...]) -> bytes:
    """Encode fields unambiguously; concatenation cannot create delimiter collisions."""
    return b"".join(len(part).to_bytes(4, "big") + part for part in parts)


def oidc_subject_fingerprint(
    key: bytes,
    key_id: str,
    tenant_id: str,
    issuer: str,
    subject: str,
) -> dict[str, str]:
    """Return a tenant-scoped pseudonymous key for the exact verified (iss, sub).

    The caller must first verify the JWT signature, issuer, audience, time and
    claim shape. Roles and tenant membership are deliberately not derived here.
    The supplied key is a dedicated identity-fingerprint key, not an API key,
    Evidence V4 key, Stripe secret, or OIDC signing key.
    """
    if not isinstance(key, bytes) or len(key) < 32:
        raise ApprovalContractError("identity fingerprint key must contain at least 32 bytes")
    if not KEY_ID_RE.fullmatch(key_id or ""):
        raise ApprovalContractError("identity fingerprint key id is invalid")
    tenant = _uuid(tenant_id, "tenant_id")
    issuer = _text(issuer, "issuer", max_length=512)
    subject = _text(subject, "subject", max_length=256)
    try:
        parsed = urlsplit(issuer)
        port = parsed.port
    except ValueError:
        raise ApprovalContractError("issuer URL is invalid") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in (None, 443)
    ):
        raise ApprovalContractError("issuer must be an exact HTTPS OIDC issuer URL")
    material = IDENTITY_DOMAIN + _framed((
        tenant.encode("utf-8"),
        issuer.encode("utf-8"),
        subject.encode("utf-8"),
    ))
    digest = hmac.new(key, material, hashlib.sha256).hexdigest()
    return {
        "algorithm": "HMAC-SHA-256",
        "key_id": key_id,
        "value": digest,
    }



def oidc_session_fingerprint(
    key: bytes,
    key_id: str,
    tenant_id: str,
    issuer: str,
    subject: str,
    session_id: str,
) -> dict[str, str]:
    """Return a tenant-, issuer-, subject- and session-scoped pseudonymous key.

    This value binds an approval's reviewer step-up to the live OIDC session.
    It is domain-separated from the persistent subject fingerprint and never
    stores the raw session identifier.
    """
    if not isinstance(key, bytes) or len(key) < 32:
        raise ApprovalContractError("session fingerprint key must contain at least 32 bytes")
    if not KEY_ID_RE.fullmatch(key_id or ""):
        raise ApprovalContractError("session fingerprint key id is invalid")
    tenant = _uuid(tenant_id, "tenant_id")
    issuer = _validate_https_issuer(issuer, "issuer")
    subject = _text(subject, "subject", max_length=256)
    session = _text(session_id, "session_id", max_length=256)
    material = SESSION_DOMAIN + _framed((
        tenant.encode("utf-8"),
        issuer.encode("utf-8"),
        subject.encode("utf-8"),
        session.encode("utf-8"),
    ))
    digest = hmac.new(key, material, hashlib.sha256).hexdigest()
    return {
        "algorithm": "HMAC-SHA-256",
        "key_id": key_id,
        "value": digest,
    }


def _validate_json_value(value: object, *, depth: int, counter: list[int]) -> None:
    counter[0] += 1
    if counter[0] > MAX_JSON_NODES:
        raise ApprovalContractError("canonical payload exceeds node limit")
    if depth > MAX_JSON_DEPTH:
        raise ApprovalContractError("canonical payload exceeds nesting limit")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise ApprovalContractError("integer exceeds interoperable JSON safe range")
        return
    if isinstance(value, float):
        raise ApprovalContractError("floating point values are forbidden in signed payloads")
    if isinstance(value, str):
        _text(value, "JSON string", max_length=MAX_CANONICAL_BYTES)
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, depth=depth + 1, counter=counter)
        return
    if isinstance(value, dict):
        normalized_keys: set[str] = set()
        for key, item in value.items():
            if not isinstance(key, str):
                raise ApprovalContractError("JSON object keys must be strings")
            _text(key, "JSON object key", max_length=256)
            if key in normalized_keys:
                raise ApprovalContractError("JSON object contains duplicate normalized keys")
            normalized_keys.add(key)
            _validate_json_value(item, depth=depth + 1, counter=counter)
        return
    raise ApprovalContractError("canonical payload contains a non-JSON value")


def canonical_payload_bytes(payload: dict) -> bytes:
    """Serialize only the unsigned payload using the OLA v1 canonical profile.

    Floats, non-NFC text, unsafe integers, non-string object keys and overlarge
    documents are rejected instead of relying on language-specific encodings.
    The signature envelope must never be passed to this function.
    """
    if not isinstance(payload, dict):
        raise ApprovalContractError("approval payload must be an object")
    if "signature" in payload:
        raise ApprovalContractError("signature envelope must not be inside signed payload")
    if payload.get("schema") != "ola.signed-approval/v1":
        raise ApprovalContractError("unsupported signed approval schema")
    _validate_json_value(payload, depth=0, counter=[0])
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise ApprovalContractError("approval payload cannot be canonically serialized") from None
    if len(encoded) > MAX_CANONICAL_BYTES:
        raise ApprovalContractError("canonical payload exceeds byte limit")
    return encoded


def signing_input(payload: dict) -> bytes:
    """Bytes to sign with the dedicated OLA Ed25519 signing key."""
    return DOMAIN_SEPARATOR + canonical_payload_bytes(payload)


def verify_signed_approval_envelope(
    envelope: object,
    trusted_public_keys: Mapping[str, bytes | Ed25519PublicKey],
) -> bool:
    """Verify an Ed25519 envelope against an explicit trusted key-id map.

    This verifies only the cryptographic signature over the canonical,
    domain-separated payload. Callers must separately validate the JSON Schema,
    approval semantics, current membership/policy, nonce, expiry and target
    state before authorizing any effect. No key discovery or network access is
    performed here.
    """
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
        raise ApprovalContractError("signed approval envelope shape is invalid")

    signature_record = envelope.get("signature")
    if not isinstance(signature_record, dict) or set(signature_record) != {
        "algorithm", "key_id", "value"
    }:
        raise ApprovalContractError("signed approval signature record shape is invalid")
    if signature_record.get("algorithm") != "Ed25519":
        raise ApprovalContractError("unsupported signed approval signature algorithm")

    key_id = signature_record.get("key_id")
    value = signature_record.get("value")
    if not isinstance(key_id, str) or KEY_ID_RE.fullmatch(key_id) is None:
        raise ApprovalContractError("signed approval key id is invalid")
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{86}", value) is None
    ):
        raise ApprovalContractError("signed approval signature encoding is invalid")
    if not isinstance(trusted_public_keys, Mapping):
        raise ApprovalContractError("trusted approval public-key map is invalid")
    if key_id not in trusted_public_keys:
        raise ApprovalContractError("signed approval key id is not trusted")

    configured_key = trusted_public_keys[key_id]
    if isinstance(configured_key, Ed25519PublicKey):
        public_key = configured_key
    elif isinstance(configured_key, bytes) and len(configured_key) == 32:
        try:
            public_key = Ed25519PublicKey.from_public_bytes(configured_key)
        except ValueError:
            raise ApprovalContractError("trusted Ed25519 public key is invalid") from None
    else:
        raise ApprovalContractError("trusted Ed25519 public key must be 32 raw bytes")

    try:
        signature = base64.b64decode(value + "==", altchars=b"-_", validate=True)
        if (
            len(signature) != 64
            or base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii") != value
        ):
            raise ApprovalContractError("signed approval signature encoding is non-canonical")
        public_key.verify(signature, signing_input(envelope["payload"]))
    except ApprovalContractError:
        raise
    except (InvalidSignature, binascii.Error, TypeError, ValueError, UnicodeError):
        raise ApprovalContractError("signed approval signature verification failed") from None
    return True


def payload_sha256(payload: dict) -> str:
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def _parse_utc(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ApprovalContractError(f"{name} must be an RFC3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ApprovalContractError(f"{name} is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ApprovalContractError(f"{name} must be UTC")
    return parsed.astimezone(timezone.utc)


def validate_approval_semantics(
    payload: dict,
    *,
    now: datetime | None = None,
) -> None:
    """Check cross-field authorization invariants after JSON Schema validation.

    This does not verify a signature, authenticate a person, query membership,
    consume a nonce, write evidence, or authorize an external effect.
    """
    if not isinstance(payload, dict):
        raise ApprovalContractError("approval payload must be an object")
    if payload.get("schema") != "ola.signed-approval/v1":
        raise ApprovalContractError("unsupported signed approval schema")

    tenant_id = _uuid(payload.get("tenant_id"), "tenant_id")
    _uuid(payload.get("approval_id"), "approval_id")
    _uuid(payload.get("operation_id"), "operation_id")
    _uuid(payload.get("nonce"), "nonce")

    decision = payload.get("decision")
    if not isinstance(decision, str) or decision not in {"ALLOW", "REFUSE", "UNRESOLVED", "INCOMPARABLE"}:
        raise ApprovalContractError("decision is invalid")
    if type(payload.get("effect_authorized")) is not bool:
        raise ApprovalContractError("effect_authorized must be a boolean")
    if payload["effect_authorized"] is not (decision == "ALLOW"):
        raise ApprovalContractError("only ALLOW may authorize the exact recorded effect")
    if payload.get("execution_observed") != "NOT_STARTED":
        raise ApprovalContractError("approval cannot claim that execution has already occurred")

    request = payload.get("request")
    effect = payload.get("effect")
    if not isinstance(request, dict) or not isinstance(effect, dict):
        raise ApprovalContractError("request and effect objects are required")
    action = request.get("action")
    if action == "EXECUTE_PAID_ORDER":
        if (
            request.get("resource_type") != "checkout_order"
            or effect.get("action") != "QUEUE_SINGLE_EXECUTION"
            or effect.get("target_id") != request.get("resource_id")
        ):
            raise ApprovalContractError("paid-order approval is not bound to one order and one queued execution")
    elif action == "APPROVE_CUSTOMER_REPORT":
        if (
            request.get("resource_type") != "customer_report"
            or effect.get("action") != "RELEASE_REPORT_TO_ORIGINAL_REQUESTER"
            or effect.get("target_id") != request.get("resource_id")
        ):
            raise ApprovalContractError("report approval is not bound to one report and its original requester")
    else:
        raise ApprovalContractError("unsupported action")

    author = payload.get("author")
    reviewer = payload.get("reviewer")
    prior = payload.get("prior_approvers")
    if not isinstance(author, dict) or not isinstance(reviewer, dict) or not isinstance(prior, list):
        raise ApprovalContractError("author, reviewer and prior_approvers are required")
    author_id = _uuid(author.get("principal_id"), "author.principal_id")
    reviewer_id = _uuid(reviewer.get("principal_id"), "reviewer.principal_id")
    if author_id == reviewer_id:
        raise ApprovalContractError("request author cannot approve their own action")
    if author.get("role") != "requester":
        raise ApprovalContractError("author must have the persisted requester role")

    prior_ids: list[str] = []
    for index, approver in enumerate(prior):
        if not isinstance(approver, dict):
            raise ApprovalContractError("prior approver entry is invalid")
        prior_id = _uuid(approver.get("principal_id"), f"prior_approvers[{index}].principal_id")
        if prior_id in prior_ids:
            raise ApprovalContractError("prior approver principals must be unique")
        prior_ids.append(prior_id)
        if prior_id in {author_id, reviewer_id}:
            raise ApprovalContractError("author and final reviewer must be distinct from prior approvers")

    if action == "EXECUTE_PAID_ORDER":
        if reviewer.get("role") != "execution_approver" or prior:
            raise ApprovalContractError("paid-order action requires one independent execution_approver")
    else:
        if reviewer.get("role") != "report_reviewer":
            raise ApprovalContractError("report action requires a report_reviewer")
        if len(prior) != 1 or prior[0].get("role") != "execution_approver":
            raise ApprovalContractError("report review must be independent from one recorded execution approver")

    for label, actor in (("author", author), ("reviewer", reviewer), *[
        (f"prior_approvers[{index}]", item) for index, item in enumerate(prior)
    ]):
        if actor.get("tenant_id") != tenant_id:
            raise ApprovalContractError(f"{label} membership is not bound to the record tenant")
        fingerprint = actor.get("subject_fingerprint")
        if not isinstance(fingerprint, str) or SHA256_RE.fullmatch(fingerprint) is None:
            raise ApprovalContractError(f"{label} subject fingerprint is invalid")
        if not KEY_ID_RE.fullmatch(actor.get("fingerprint_key_id", "") or ""):
            raise ApprovalContractError(f"{label} fingerprint key id is invalid")
        _validate_https_issuer(actor.get("issuer"), f"{label}.issuer")
        membership_version = actor.get("membership_version")
        if (
            not isinstance(membership_version, int)
            or isinstance(membership_version, bool)
            or membership_version < 1
        ):
            raise ApprovalContractError(f"{label} membership version is invalid")

    request_digest = request.get("sha256")
    if not isinstance(request_digest, str) or SHA256_RE.fullmatch(request_digest) is None:
        raise ApprovalContractError("request sha256 is invalid")
    effect_digest = effect.get("target_sha256")
    if not isinstance(effect_digest, str) or SHA256_RE.fullmatch(effect_digest) is None:
        raise ApprovalContractError("effect target sha256 is invalid")
    if effect_digest != request_digest:
        raise ApprovalContractError("effect target sha256 must match the request digest")

    policy = payload.get("policy")
    if not isinstance(policy, dict) or not isinstance(policy.get("version"), str):
        raise ApprovalContractError("policy version is required")
    if not isinstance(policy.get("sha256"), str) or SHA256_RE.fullmatch(policy["sha256"]) is None:
        raise ApprovalContractError("policy sha256 is invalid")

    runtime = payload.get("runtime")
    if not isinstance(runtime, dict) or not isinstance(runtime.get("source_commit"), str):
        raise ApprovalContractError("runtime source commit is required")
    if SHA1_RE.fullmatch(runtime["source_commit"]) is None:
        raise ApprovalContractError("runtime source commit must be a full Git SHA")

    evidence = payload.get("evidence")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("records"), list) or not evidence["records"]:
        raise ApprovalContractError("one or more evidence references are required")
    if not isinstance(evidence.get("tip_hash"), str) or SHA256_RE.fullmatch(evidence["tip_hash"]) is None:
        raise ApprovalContractError("evidence tip hash is invalid")
    evidence_ids: set[str] = set()
    previous_sequence = -1
    for index, record in enumerate(evidence["records"]):
        if not isinstance(record, dict):
            raise ApprovalContractError("evidence reference is invalid")
        record_id = _uuid(record.get("id"), f"evidence.records[{index}].id")
        if record_id in evidence_ids:
            raise ApprovalContractError("evidence record references must be unique")
        evidence_ids.add(record_id)
        sequence = record.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= previous_sequence:
            raise ApprovalContractError("evidence sequence must be strictly increasing")
        previous_sequence = sequence
        if not isinstance(record.get("record_hash"), str) or SHA256_RE.fullmatch(record["record_hash"]) is None:
            raise ApprovalContractError("evidence record hash is invalid")
    if evidence["records"][-1].get("record_hash") != evidence["tip_hash"]:
        raise ApprovalContractError("evidence tip must equal the final referenced record hash")

    authentication = payload.get("reviewer_authentication")
    if not isinstance(authentication, dict):
        raise ApprovalContractError("reviewer step-up authentication evidence is required")
    if not isinstance(authentication.get("acr"), str) or not authentication["acr"]:
        raise ApprovalContractError("reviewer authentication acr is required")
    amr = authentication.get("amr")
    if not isinstance(amr, list) or not amr or any(not isinstance(item, str) or not item for item in amr):
        raise ApprovalContractError("reviewer authentication amr is required")
    if len(set(amr)) != len(amr):
        raise ApprovalContractError("reviewer authentication amr values must be unique")
    if not isinstance(authentication.get("session_fingerprint"), str) or SHA256_RE.fullmatch(authentication["session_fingerprint"]) is None:
        raise ApprovalContractError("reviewer session fingerprint is invalid")

    issued_at = _parse_utc(payload.get("issued_at"), "issued_at")
    expires_at = _parse_utc(payload.get("expires_at"), "expires_at")
    auth_time = _parse_utc(authentication.get("auth_time"), "reviewer_authentication.auth_time")
    if expires_at <= issued_at:
        raise ApprovalContractError("approval expiry must follow issue time")
    ttl = (expires_at - issued_at).total_seconds()
    if ttl > MAX_APPROVAL_TTL_SECONDS:
        raise ApprovalContractError("approval lifetime exceeds the v1 five-minute maximum")
    if auth_time > issued_at:
        raise ApprovalContractError("reviewer authentication cannot occur after the approval")
    if (issued_at - auth_time).total_seconds() > MAX_AUTH_AGE_SECONDS:
        raise ApprovalContractError("reviewer step-up authentication is too old")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() != timedelta(0):
        raise ApprovalContractError("validation clock must be timezone-aware UTC")
    if (issued_at - current.astimezone(timezone.utc)).total_seconds() > CLOCK_SKEW_SECONDS:
        raise ApprovalContractError("approval issue time is too far in the future")

    closure = payload.get("closure")
    if not isinstance(closure, dict) or any(
        closure.get(name) != "OPEN"
        for name in ("operational", "epistemic", "remedial")
    ):
        raise ApprovalContractError("approval record cannot self-assert closure")


def approval_is_current(payload: dict, *, now: datetime | None = None) -> bool:
    """Return whether an otherwise verified approval is inside its time window.

    Callers must separately verify the Ed25519 signature, current membership,
    current policy, unused nonce and target/evidence binding before any effect.
    """
    issued_at = _parse_utc(payload.get("issued_at"), "issued_at")
    expires_at = _parse_utc(payload.get("expires_at"), "expires_at")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() != timedelta(0):
        raise ApprovalContractError("validation clock must be timezone-aware UTC")
    current = current.astimezone(timezone.utc)
    return issued_at <= current < expires_at
