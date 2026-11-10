"""Generate Ed25519 trust keys for OLA provenance observers."""

import argparse
import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_keypair(private_path, public_path):
    private_path = Path(private_path)
    public_path = Path(public_path)
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    private_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_path.write_text(base64.b64encode(public_bytes).decode("ascii") + "\n", encoding="ascii")
    if os.name == "posix":
        private_path.chmod(0o600)
        public_path.chmod(0o644)
    return {"private_key_path": str(private_path), "public_key_path": str(public_path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--public-key", required=True)
    args = parser.parse_args()
    print(generate_keypair(args.private_key, args.public_key))


if __name__ == "__main__":
    main()
