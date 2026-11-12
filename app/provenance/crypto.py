"""Worker-local Ed25519 attestation helpers.

The private key is generated inside each one-shot worker and never leaves it.
The supervisor and IGOR receive only the ephemeral public key and signature.
"""

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ..canonical import canonical_json, digest_json


_ATTESTATION_DOMAIN = "OLA-WORKER-ATTESTATION-V1"


def worker_attestation_payload(
    *,
    schema_version,
    run_id,
    agent_id,
    agent_instance_id,
    specialist_role,
    execution_profile,
    capability,
    source_commit,
    worker_pid,
    worker_nonce,
    request_digest,
    input_digest,
    capability_input_digest,
    model_output_digest,
    capability_result,
):
    return {
        "domain": _ATTESTATION_DOMAIN,
        "schema_version": schema_version,
        "run_id": run_id,
        "agent_id": agent_id,
        "agent_instance_id": agent_instance_id,
        "specialist_role": specialist_role,
        "execution_profile": execution_profile,
        "capability": capability,
        "source_commit": source_commit,
        "worker_pid": worker_pid,
        "worker_nonce": worker_nonce,
        "request_digest": request_digest,
        "input_digest": input_digest,
        "capability_input_digest": capability_input_digest,
        "model_output_digest": model_output_digest,
        "capability_result": capability_result,
    }


def sign_worker_payload(payload):
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    signature = private_key.sign(canonical_json(payload).encode("utf-8"))
    return (
        base64.b64encode(public_key).decode("ascii"),
        base64.b64encode(signature).decode("ascii"),
    )


def verify_worker_signature(result, *, expected_request_digest=None,
                            expected_model_output_digest=None,
                            expected_capability_input_digest=None):
    try:
        payload = worker_attestation_payload(
            schema_version=result.schema_version,
            run_id=result.run_id,
            agent_id=result.agent_id,
            agent_instance_id=result.agent_instance_id,
            specialist_role=result.specialist_role,
            execution_profile=result.execution_profile,
            capability=result.capability,
            source_commit=result.source_commit,
            worker_pid=result.worker_pid,
            worker_nonce=result.worker_nonce,
            request_digest=result.request_digest,
            input_digest=result.input_digest,
            capability_input_digest=result.capability_input_digest,
            model_output_digest=result.model_output_digest,
            capability_result=result.capability_result,
        )
        if digest_json(payload) != result.output_digest:
            return False
        if expected_request_digest is not None and result.request_digest != expected_request_digest:
            return False
        if expected_model_output_digest is not None and result.model_output_digest != expected_model_output_digest:
            return False
        if (
            expected_capability_input_digest is not None
            and result.capability_input_digest != expected_capability_input_digest
        ):
            return False
        public_key = base64.b64decode(result.worker_public_key, validate=True)
        signature = base64.b64decode(result.worker_signature, validate=True)
        if len(public_key) != 32 or len(signature) != 64:
            return False
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature,
            canonical_json(payload).encode("utf-8"),
        )
        return True
    except (AttributeError, TypeError, ValueError, InvalidSignature):
        return False
