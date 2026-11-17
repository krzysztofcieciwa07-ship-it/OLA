"""Pin the exact installed Ollama model digest into the local workstation lock."""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx


_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


def lock_model(model, *, base_url="http://127.0.0.1:11434", output_path=None):
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("model lock discovery is restricted to local Ollama loopback")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("an exact Ollama model tag is required")
    response = httpx.get(
        base_url.rstrip("/") + "/api/tags",
        timeout=10,
        trust_env=False,
    )
    response.raise_for_status()
    entries = response.json().get("models", [])
    match = next((item for item in entries if item.get("name") == model), None)
    if match is None:
        raise ValueError("requested Ollama model is not installed")
    digest = match.get("digest")
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise ValueError("installed Ollama model has no valid content digest")

    target = Path(output_path) if output_path else (
        Path(__file__).resolve().parents[1] / "workstation" / "provider-lock.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "providers": {"ollama": {"model": model, "model_digest": digest}},
    }
    fd, temporary = tempfile.mkstemp(prefix="provider-lock-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return {"model": model, "model_digest": digest, "path": str(target)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Exact installed Ollama model tag")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = lock_model(args.model, base_url=args.base_url, output_path=args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
