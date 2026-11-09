"""Contract tests for the Ed25519 authenticated agent invocation boundary."""

import base64
import json
import secrets
import time
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app import main
from app.database import SessionLocal
from app.models import ApiKey, Tenant
from app.api_key_hashing import api_key_fingerprint
from app.secure_bridge import build_signing_message


PATH = "/api/v1/secure-bridge/invoke"
AUDIENCE = "ola-secure-agent-runtime"


def _seed_tenant():
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="secure-bridge-test"))
        db.commit()
    return tenant_id


def _public_key_b64(private_key):
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def _configure_key(monkeypatch, tenant_id, private_key, *, scopes=None, key_id="agent-key-1"):
    registry = [{
        "key_id": key_id,
        "tenant_id": tenant_id,
        "agent_id": "agent-001",
        "public_key_b64": _public_key_b64(private_key),
        "scopes": scopes if scopes is not None else ["agent:run"],
    }]
    monkeypatch.setenv("OLA_SECURE_BRIDGE_KEYS_JSON", json.dumps(registry))
    monkeypatch.setenv("OLA_SECURE_BRIDGE_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("OLA_SECURE_BRIDGE_CLOCK_SKEW_SECONDS", "60")
    monkeypatch.delenv("OLA_SECURE_BRIDGE_REVOKED_KEY_IDS", raising=False)


def _signed_request(private_key, *, key_id="agent-key-1", body=None, timestamp=None,
                    nonce=None, audience=AUDIENCE, path=PATH):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    nonce = nonce or secrets.token_hex(32)
    body_bytes = body if isinstance(body, bytes) else json.dumps(
        body if body is not None else {
            "action": "agent.run",
            "payload": {"task": "verify secure agent invocation"},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    message = build_signing_message(
        key_id=key_id,
        timestamp=timestamp,
        nonce=nonce,
        method="POST",
        path=path,
        audience=audience,
        body=body_bytes,
    )
    signature = private_key.sign(message).hex()
    return body_bytes, nonce, {
        "content-type": "application/json",
        "x-key-id": key_id,
        "x-timestamp": timestamp,
        "x-nonce": nonce,
        "x-signature-ed25519": signature,
    }


def _fake_execution(monkeypatch):
    calls = []

    def fake_run(tenant_id, task):
        calls.append((tenant_id, task))
        return {
            "status": "VERIFIED",
            "run_id": "run-secure-bridge-test",
            "evidence_ids": ["evidence-1"],
            "evidence_count": 1,
        }

    monkeypatch.setattr(main, "run_agent_task", fake_run)
    return calls


def test_valid_ed25519_request_executes_only_the_allowlisted_agent_action(monkeypatch):
    tenant_id = _seed_tenant()
    private_key = Ed25519PrivateKey.generate()
    _configure_key(monkeypatch, tenant_id, private_key)
    calls = _fake_execution(monkeypatch)
    body, _nonce, headers = _signed_request(private_key)

    response = TestClient(main.app).post(PATH, content=body, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "VERIFIED"
    assert response.json()["execution"]["run_id"] == "run-secure-bridge-test"
    assert calls == [(tenant_id, "verify secure agent invocation")]


def test_replaying_the_same_signed_nonce_is_rejected_across_clients(monkeypatch):
    tenant_id = _seed_tenant()
    private_key = Ed25519PrivateKey.generate()
    _configure_key(monkeypatch, tenant_id, private_key)
    calls = _fake_execution(monkeypatch)
    body, _nonce, headers = _signed_request(private_key)

    first = TestClient(main.app).post(PATH, content=body, headers=headers)
    second = TestClient(main.app).post(PATH, content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "request nonce already used"
    assert len(calls) == 1


def test_signature_binds_exact_raw_body_and_rejects_tampering(monkeypatch):
    tenant_id = _seed_tenant()
    private_key = Ed25519PrivateKey.generate()
    _configure_key(monkeypatch, tenant_id, private_key)
    calls = _fake_execution(monkeypatch)
    body, _nonce, headers = _signed_request(private_key)
    changed_body = body.replace(b"verify secure agent invocation", b"tampered invocation")

    response = TestClient(main.app).post(PATH, content=changed_body, headers=headers)

    assert response.status_code == 401
    assert calls == []


def test_timestamp_must_be_canonical_and_inside_configured_clock_window(monkeypatch):
    tenant_id = _seed_tenant()
    private_key = Ed25519PrivateKey.generate()
    _configure_key(monkeypatch, tenant_id, private_key)
    calls = _fake_execution(monkeypatch)
    stale = int(time.time()) - 300
    body, _nonce, headers = _signed_request(private_key, timestamp=stale)

    response = TestClient(main.app).post(PATH, content=body, headers=headers)

    assert response.status_code == 401
    assert calls == []


def test_unknown_revoked_or_malformed_signing_keys_fail_closed(monkeypatch):
    tenant_id = _seed_tenant()
    private_key = Ed25519PrivateKey.generate()
    _configure_key(monkeypatch, tenant_id, private_key)
    calls = _fake_execution(monkeypatch)
    body, _nonce, headers = _signed_request(private_key)
    monkeypatch.setenv("OLA_SECURE_BRIDGE_REVOKED_KEY_IDS", "agent-key-1")

    revoked = TestClient(main.app).post(PATH, content=body, headers=headers)
    assert revoked.status_code == 401

    monkeypatch.delenv("OLA_SECURE_BRIDGE_REVOKED_KEY_IDS")
    malformed = dict(headers)
    malformed["x-signature-ed25519"] = "ab" * 63 + "zz"
    invalid = TestClient(main.app).post(PATH, content=body, headers=malformed)

    assert invalid.status_code == 401
    assert calls == []


def test_scope_mismatch_never_executes(monkeypatch):
    tenant_id = _seed_tenant()
    private_key = Ed25519PrivateKey.generate()
    _configure_key(monkeypatch, tenant_id, private_key, scopes=["evidence:read"])
    calls = _fake_execution(monkeypatch)
    body, _nonce, headers = _signed_request(private_key)

    response = TestClient(main.app).post(PATH, content=body, headers=headers)

    assert response.status_code == 403
    assert calls == []


def test_unknown_actions_never_execute(monkeypatch):
    tenant_id = _seed_tenant()
    private_key = Ed25519PrivateKey.generate()
    _configure_key(monkeypatch, tenant_id, private_key)
    calls = _fake_execution(monkeypatch)
    body, _nonce, headers = _signed_request(
        private_key,
        body={"action": "admin.delete", "payload": {"task": "delete all"}},
    )

    response = TestClient(main.app).post(PATH, content=body, headers=headers)

    assert response.status_code == 403
    assert calls == []


def test_untrusted_signatures_cannot_quarantine_a_real_agent_key(monkeypatch):
    tenant_id = _seed_tenant()
    trusted_private_key = Ed25519PrivateKey.generate()
    attacker_private_key = Ed25519PrivateKey.generate()
    _configure_key(monkeypatch, tenant_id, trusted_private_key)
    calls = _fake_execution(monkeypatch)

    client = TestClient(main.app)
    for _ in range(2):
        body, _nonce, forged_headers = _signed_request(attacker_private_key)
        rejected = client.post(PATH, content=body, headers=forged_headers)
        assert rejected.status_code == 401

    body, _nonce, trusted_headers = _signed_request(trusted_private_key)
    accepted = client.post(PATH, content=body, headers=trusted_headers)

    assert accepted.status_code == 200
    assert len(calls) == 1


def test_signature_is_bound_to_method_path_and_audience(monkeypatch):
    tenant_id = _seed_tenant()
    private_key = Ed25519PrivateKey.generate()
    _configure_key(monkeypatch, tenant_id, private_key)
    calls = _fake_execution(monkeypatch)
    body, _nonce, wrong_path_headers = _signed_request(private_key, path="/other/path")
    wrong_path = TestClient(main.app).post(PATH, content=body, headers=wrong_path_headers)

    body, _nonce, wrong_audience_headers = _signed_request(private_key, audience="wrong-audience")
    wrong_audience = TestClient(main.app).post(PATH, content=body, headers=wrong_audience_headers)

    assert wrong_path.status_code == 401
    assert wrong_audience.status_code == 401
    assert calls == []


def test_nonce_store_unavailability_fails_closed_without_execution(monkeypatch):
    tenant_id = _seed_tenant()
    private_key = Ed25519PrivateKey.generate()
    _configure_key(monkeypatch, tenant_id, private_key)
    calls = _fake_execution(monkeypatch)

    from app import secure_bridge
    monkeypatch.setattr(
        secure_bridge, "consume_nonce",
        lambda **_kwargs: (_ for _ in ()).throw(secure_bridge.NonceStoreUnavailable()),
    )
    body, _nonce, headers = _signed_request(private_key)

    response = TestClient(main.app).post(PATH, content=body, headers=headers)

    assert response.status_code == 503
    assert calls == []



def test_tenant_api_cannot_forge_secure_bridge_internal_evidence():
    tenant_id = _seed_tenant()
    api_key = "secure-bridge-evidence-customer-key"
    with SessionLocal() as db:
        db.add(ApiKey(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=api_key_fingerprint(api_key),
        ))
        db.commit()

    response = TestClient(main.app).post(
        "/evidence",
        headers={"X-API-Key": api_key},
        json={
            "record_type": "secure_bridge.request_authenticated",
            "payload": {
                "request_id": "forged-request",
                "key_id": "forged-agent",
                "agent_id": "agent-001",
            },
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "reserved internal evidence type"
