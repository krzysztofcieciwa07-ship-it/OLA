import hashlib
from pathlib import Path

import pytest

from app.agent_firewall.digest import action_digest
from app.agent_firewall.targets import TargetRegistry, TargetRegistryUnavailable


def _inventory(tmp_path: Path, *, host="staging.example.internal", critical=False):
    import base64
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

    host_key = Ed25519PrivateKey.generate()
    host_pub = host_key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
    host_key_data = base64.b64decode(host_pub.split()[1])
    host_fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(host_key_data).digest()).decode("ascii").rstrip("=")
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_bytes(host.encode("ascii") + b" " + host_pub + b"\n")
    known_hosts.chmod(0o600)

    identity_key = Ed25519PrivateKey.generate()
    identity = tmp_path / "id_ed25519"
    identity.write_bytes(identity_key.private_bytes(
        Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()
    ))
    identity.chmod(0o600)
    identity_pub = identity_key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
    identity_digest = hashlib.sha256(identity_pub).hexdigest()

    config = tmp_path / "targets.toml"
    config.write_text(
        "[targets.staging-api]\n"
        'environment = "staging"\n'
        f'host = "{host}"\n'
        'port = 22\n'
        'user = "ola-gateway"\n'
        f'host_fingerprint = "{host_fingerprint}"\n'
        f'known_hosts_file = "{known_hosts}"\n'
        f'identity_file = "{identity}"\n'
        f'identity_public_key_sha256 = "{identity_digest}"\n'
        'allowed_units = ["ola-api.service"]\n'
        f'critical = {str(critical).lower()}\n'
    )
    return config, known_hosts, identity


def test_target_registry_loads_server_owned_inventory_and_allows_only_named_unit(tmp_path):
    config, _, _ = _inventory(tmp_path)
    target = TargetRegistry.from_file(config).resolve("staging-api")

    assert target is not None
    assert target.environment == "staging"
    assert target.allows_unit("ola-api.service") is True
    assert target.allows_unit("other.service") is False
    assert target.config_digest


def test_target_registry_blocks_missing_inventory(tmp_path):
    with pytest.raises(TargetRegistryUnavailable):
        TargetRegistry.from_file(tmp_path / "missing.toml")


def test_target_registry_rejects_known_hosts_pin_change_without_config_update(tmp_path):
    config, known_hosts, _ = _inventory(tmp_path)
    target = TargetRegistry.from_file(config).resolve("staging-api")
    assert target.config_digest
    known_hosts.write_text("staging.example.internal ssh-ed25519 AAAAChangedKey\n")
    with pytest.raises(TargetRegistryUnavailable):
        TargetRegistry.from_file(config)


def test_private_key_with_group_or_world_permissions_is_rejected(tmp_path):
    config, _, identity = _inventory(tmp_path)
    identity.chmod(0o644)

    with pytest.raises(TargetRegistryUnavailable):
        TargetRegistry.from_file(config)


def test_target_inventory_rejects_shell_metacharacters_in_allowed_units(tmp_path):
    config, _, _ = _inventory(tmp_path)
    content = config.read_text().replace("ola-api.service", "ola-api.service;rm")
    config.write_text(content)

    with pytest.raises(TargetRegistryUnavailable):
        TargetRegistry.from_file(config)


def test_action_digest_binds_action_target_environment_tenant_agent_and_policy():
    common = {
        "action_type": "systemd.restart",
        "unit": "ola-api.service",
        "target_id": "staging-api",
        "target_config_digest": "a" * 64,
        "environment": "staging",
        "tenant_id": "tenant-a",
        "agent_id": "agent-a",
        "policy_version": "agent-firewall-v0.2.0",
    }
    baseline = action_digest(**common)
    for field, changed in (
        ("unit", "other.service"),
        ("target_id", "production-api"),
        ("environment", "production"),
        ("tenant_id", "tenant-b"),
        ("agent_id", "agent-b"),
        ("policy_version", "agent-firewall-v0.2.1"),
        ("target_config_digest", "b" * 64),
    ):
        altered = dict(common)
        altered[field] = changed
        assert action_digest(**altered) != baseline


def test_action_digest_rejects_unpaired_surrogate_text():
    with pytest.raises(ValueError, match="non-UTF-8"):
        action_digest(
            action_type="systemd.restart",
            unit="bad\ud800.service",
            target_id="staging-api",
            target_config_digest="a" * 64,
            environment="staging",
            tenant_id="tenant-a",
            agent_id="agent-a",
            policy_version="agent-firewall-v0.2.0",
        )
