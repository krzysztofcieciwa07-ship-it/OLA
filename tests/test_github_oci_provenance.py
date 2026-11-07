import base64
import json
import subprocess

from app.customer_bundle.github_provenance import (
    OIDC_ISSUER,
    PREDICATE_TYPE,
    SCHEMA,
    verify_github_oci_provenance,
)

REPOSITORY = "krzysztofcieciwa07-ship-it/OLA"
REPOSITORY_ID = "212613049"
SOURCE_SHA = "a" * 40
SOURCE_REF = "refs/heads/main"
IMAGE_NAME = "ghcr.io/krzysztofcieciwa07-ship-it/ola"
IMAGE_DIGEST = "sha256:" + "b" * 64
WORKFLOW_IDENTITY = (
    "https://github.com/krzysztofcieciwa07-ship-it/OLA/"
    ".github/workflows/supply-chain-evidence.yml@refs/heads/main"
)


def _materials():
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{
            "name": IMAGE_NAME,
            "digest": {"sha256": "b" * 64},
        }],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "buildDefinition": {
                "resolvedDependencies": [{
                    "uri": f"git+https://github.com/{REPOSITORY}@{SOURCE_REF}",
                    "digest": {"gitCommit": SOURCE_SHA},
                }],
            },
        },
    }
    result = [{
        "verificationResult": {
            "signature": {
                "certificate": {
                    "sourceRepositoryIdentifier": REPOSITORY_ID,
                    "issuer": OIDC_ISSUER,
                },
            },
            "statement": statement,
        },
    }]
    return json.dumps(result), json.dumps({"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"}), json.dumps({"trustedRoot": "test"})


def _payload():
    output, bundle, root = _materials()
    return json.dumps({
        "schema": SCHEMA,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "source_sha": SOURCE_SHA,
        "source_ref": SOURCE_REF,
        "workflow_identity": WORKFLOW_IDENTITY,
        "image_name": IMAGE_NAME,
        "image_digest": IMAGE_DIGEST,
        "attestation_bundle_b64": base64.b64encode(bundle.encode()).decode(),
        "trusted_root_b64": base64.b64encode((root + "\\n").encode()).decode(),
    }).encode()


def _success(command, **kwargs):
    return subprocess.CompletedProcess(
        command, 0, stdout=_materials()[0], stderr="",
    )


def _verify(monkeypatch, payload=None, **overrides):
    arguments = {
        "expected_repository": REPOSITORY,
        "expected_repository_id": REPOSITORY_ID,
        "expected_workflow_identity": WORKFLOW_IDENTITY,
        "expected_source_ref": SOURCE_REF,
        "expected_image_name": IMAGE_NAME,
    }
    arguments.update(overrides)
    return verify_github_oci_provenance(
        _payload() if payload is None else payload,
        SOURCE_SHA,
        IMAGE_DIGEST,
        **arguments,
    )


def test_verifies_real_bundle_and_trusted_root_with_exact_oci_and_workflow_policy(monkeypatch):
    commands = []

    def capture(command, **kwargs):
        commands.append(command)
        return _success(command, **kwargs)

    monkeypatch.setattr(
        "app.customer_bundle.github_provenance.subprocess.run", capture,
    )

    assert _verify(monkeypatch) is True
    command = commands[0]
    assert command[:3] == ["gh", "attestation", "verify"]
    assert command[3] == f"oci://{IMAGE_NAME}@{IMAGE_DIGEST}"
    assert "--bundle" in command
    assert "--custom-trusted-root" in command
    assert command[command.index("--cert-identity") + 1] == WORKFLOW_IDENTITY
    assert command[command.index("--cert-oidc-issuer") + 1] == OIDC_ISSUER
    assert command[command.index("--predicate-type") + 1] == PREDICATE_TYPE


def test_rejects_statement_for_different_image_digest(monkeypatch):
    output, bundle, root = _materials()
    results = json.loads(output)
    results[0]["verificationResult"]["statement"]["subject"][0]["digest"]["sha256"] = "c" * 64
    monkeypatch.setattr(
        "app.customer_bundle.github_provenance.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(results), stderr="",
        ),
    )
    assert _verify(monkeypatch) is False


def test_rejects_statement_for_different_source_commit(monkeypatch):
    output, bundle, root = _materials()
    results = json.loads(output)
    results[0]["verificationResult"]["statement"]["predicate"]["buildDefinition"]["resolvedDependencies"][0]["digest"]["gitCommit"] = "c" * 40
    monkeypatch.setattr(
        "app.customer_bundle.github_provenance.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(results), stderr="",
        ),
    )
    assert _verify(monkeypatch) is False


def test_rejects_repository_identity_mismatch_even_when_cli_succeeds(monkeypatch):
    output, bundle, root = _materials()
    results = json.loads(output)
    results[0]["verificationResult"]["signature"]["certificate"]["sourceRepositoryIdentifier"] = "999999"
    monkeypatch.setattr(
        "app.customer_bundle.github_provenance.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(results), stderr="",
        ),
    )
    assert _verify(monkeypatch) is False


def test_rejects_nonzero_cli_verification(monkeypatch):
    monkeypatch.setattr(
        "app.customer_bundle.github_provenance.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, stdout="", stderr="signature invalid",
        ),
    )
    assert _verify(monkeypatch) is False


def test_rejects_tampered_payload_metadata_before_cli(monkeypatch):
    payload = json.loads(_payload())
    payload["source_sha"] = "d" * 40
    called = []
    monkeypatch.setattr(
        "app.customer_bundle.github_provenance.subprocess.run",
        lambda command, **kwargs: called.append(command),
    )
    assert _verify(monkeypatch, json.dumps(payload).encode()) is False
    assert called == []
