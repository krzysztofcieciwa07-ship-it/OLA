"""Server-owned SSH target inventory for the systemd-only firewall connector."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tomllib

from cryptography.hazmat.primitives import serialization


_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,31}$")
_UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,126}\.service$")
_FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class TargetRegistryUnavailable(ValueError):
    """The trusted target inventory cannot be loaded safely."""


@dataclass(frozen=True)
class SystemdTarget:
    target_id: str
    environment: str
    host: str
    port: int
    user: str
    host_fingerprint: str
    known_hosts_file: str
    identity_file: str
    identity_public_key_sha256: str
    allowed_units: tuple[str, ...]
    critical: bool
    connect_timeout_s: int
    execution_timeout_s: int
    config_digest: str

    def allows_unit(self, unit: str) -> bool:
        return isinstance(unit, str) and unit in self.allowed_units and bool(_UNIT_RE.fullmatch(unit))


class TargetRegistry:
    """Read-only inventory; request bodies can select an ID, never a host or key."""

    def __init__(self, targets: dict[str, SystemdTarget]):
        self._targets = dict(targets)

    @classmethod
    def from_file(cls, path: str | Path) -> "TargetRegistry":
        path = Path(path)
        try:
            raw = path.read_bytes()
            if not raw or len(raw) > 128 * 1024:
                raise ValueError("target inventory size is invalid")
            parsed = tomllib.loads(raw.decode("utf-8"))
            target_rows = parsed["targets"]
            if not isinstance(target_rows, dict) or not target_rows:
                raise ValueError("target inventory is empty")
            targets = {}
            for target_id, row in target_rows.items():
                targets[target_id] = _parse_target(target_id, row)
            return cls(targets)
        except (OSError, UnicodeDecodeError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
            raise TargetRegistryUnavailable("trusted target inventory is unavailable") from exc

    def resolve(self, target_id: str) -> SystemdTarget | None:
        return self._targets.get(target_id)


def _require_file(path_value: str, *, owner_only: bool) -> tuple[Path, bytes]:
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise ValueError("SSH key and known_hosts paths must be absolute")
    path = Path(path_value)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("SSH key and known_hosts paths must be regular files")
    mode = stat.S_IMODE(info.st_mode)
    if owner_only and os.name == "posix" and mode & 0o077:
        raise ValueError("SSH private key must be owner-only")
    if not owner_only and os.name == "posix" and mode & 0o022:
        raise ValueError("known_hosts file must not be group/world writable")
    content = path.read_bytes()
    if not content or len(content) > 1024 * 1024:
        raise ValueError("SSH trust file is empty or too large")
    return path, content


def _ssh_public_key_fingerprint(public_key_line: bytes) -> str:
    try:
        fields = public_key_line.decode("ascii").strip().split()
        if len(fields) < 2:
            raise ValueError("invalid OpenSSH public key")
        key_bytes = base64.b64decode(fields[1], validate=True)
    except (UnicodeDecodeError, ValueError):
        raise ValueError("invalid OpenSSH public key") from None
    digest = base64.b64encode(hashlib.sha256(key_bytes).digest()).decode("ascii").rstrip("=")
    return "SHA256:" + digest


def _verify_host_pin(host: str, port: int, known_hosts: bytes, expected_fingerprint: str) -> None:
    expected_host = host if port == 22 else f"[{host}]:{port}"
    matches = []
    for raw_line in known_hosts.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(b"#"):
            continue
        try:
            fields = line.decode("ascii").split()
        except UnicodeDecodeError:
            raise ValueError("known_hosts must be ASCII OpenSSH format") from None
        if len(fields) != 3 or fields[0].startswith("@") or fields[0].startswith("|"):
            continue
        if expected_host not in fields[0].split(","):
            continue
        matches.append(_ssh_public_key_fingerprint(" ".join(fields[1:]).encode("ascii")))
    if not matches or expected_fingerprint not in matches:
        raise ValueError("configured host fingerprint does not match the pinned known_hosts entry")


def _parse_target(target_id: str, row: dict) -> SystemdTarget:
    if not isinstance(target_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", target_id):
        raise ValueError("target ID is invalid")
    if not isinstance(row, dict):
        raise ValueError("target entry is invalid")

    environment = row.get("environment")
    host = row.get("host")
    user = row.get("user")
    port = row.get("port", 22)
    fingerprint = row.get("host_fingerprint")
    identity_public_key_sha256 = row.get("identity_public_key_sha256")
    allowed_units = row.get("allowed_units")
    critical = row.get("critical", False)
    connect_timeout_s = row.get("connect_timeout_s", 5)
    execution_timeout_s = row.get("execution_timeout_s", 30)

    if environment not in {"staging", "production"}:
        raise ValueError("target environment must be staging or production")
    if not isinstance(host, str) or not _HOST_RE.fullmatch(host):
        raise ValueError("target host must be a DNS name or IPv4 literal")
    if not isinstance(user, str) or not _USER_RE.fullmatch(user):
        raise ValueError("SSH user is invalid")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("SSH port is invalid")
    if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise ValueError("pinned host fingerprint is invalid")
    if not isinstance(identity_public_key_sha256, str) or not _HEX64_RE.fullmatch(identity_public_key_sha256):
        raise ValueError("SSH public-key fingerprint must be lowercase SHA-256")
    if not isinstance(allowed_units, list) or not allowed_units:
        raise ValueError("allowed_units must be a non-empty list")
    if any(not isinstance(unit, str) or not _UNIT_RE.fullmatch(unit) for unit in allowed_units):
        raise ValueError("allowed_units contains an invalid systemd unit")
    if len(set(allowed_units)) != len(allowed_units):
        raise ValueError("allowed_units must be unique")
    if type(critical) is not bool:
        raise ValueError("critical must be a boolean")
    if type(connect_timeout_s) is not int or not 1 <= connect_timeout_s <= 15:
        raise ValueError("connect_timeout_s must be between 1 and 15")
    if type(execution_timeout_s) is not int or not 5 <= execution_timeout_s <= 60:
        raise ValueError("execution_timeout_s must be between 5 and 60")

    known_hosts_path, known_hosts_bytes = _require_file(
        row.get("known_hosts_file"), owner_only=False
    )
    identity_path, identity_bytes = _require_file(
        row.get("identity_file"), owner_only=True
    )
    try:
        private_key = serialization.load_ssh_private_key(identity_bytes, password=None)
        public_line = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
    except Exception:
        raise ValueError("SSH private key is invalid or encrypted") from None
    actual_identity_digest = hashlib.sha256(public_line).hexdigest()
    if actual_identity_digest != identity_public_key_sha256:
        raise ValueError("SSH private key does not match configured public-key fingerprint")
    _verify_host_pin(host, port, known_hosts_bytes, fingerprint)

    known_hosts_sha256 = hashlib.sha256(known_hosts_bytes).hexdigest()
    material = {
        "schema": "ola.agent-firewall.target.v1",
        "target_id": target_id,
        "environment": environment,
        "host": host,
        "port": port,
        "user": user,
        "host_fingerprint": fingerprint,
        "known_hosts_sha256": known_hosts_sha256,
        "identity_public_key_sha256": identity_public_key_sha256,
        "allowed_units": sorted(allowed_units),
        "critical": critical,
        "connect_timeout_s": connect_timeout_s,
        "execution_timeout_s": execution_timeout_s,
        "remote_helper": "/usr/local/libexec/ola-systemd-exec",
    }
    canonical = json.dumps(
        material, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    config_digest = hashlib.sha256(canonical).hexdigest()
    return SystemdTarget(
        target_id=target_id, environment=environment, host=host,
        port=port, user=user, host_fingerprint=fingerprint,
        known_hosts_file=str(known_hosts_path), identity_file=str(identity_path),
        identity_public_key_sha256=identity_public_key_sha256,
        allowed_units=tuple(sorted(allowed_units)), critical=critical,
        connect_timeout_s=connect_timeout_s, execution_timeout_s=execution_timeout_s,
        config_digest=config_digest,
    )
