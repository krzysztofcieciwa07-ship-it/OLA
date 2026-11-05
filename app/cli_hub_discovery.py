"""Read-only adapter for the two registries used by CLI-Hub.

The adapter reads catalogue metadata only. It never installs, updates,
uninstalls, launches, or executes a discovered CLI.
"""
import hashlib
import json

import httpx


REGISTRY_URL = "https://hkuds.github.io/CLI-Anything/registry.json"
PUBLIC_REGISTRY_URL = "https://hkuds.github.io/CLI-Anything/public_registry.json"
MAX_QUERY_LENGTH = 120
MAX_REGISTRY_BYTES = 524288
MAX_TOTAL_REGISTRY_BYTES = 1048576
MAX_RESULTS = 20
TIMEOUT = httpx.Timeout(8.0, connect=3.0)


class CliHubError(RuntimeError):
    """The CLI-Hub catalogues could not be safely read."""


def _fetch_registry(url):
    body = bytearray()
    try:
        with httpx.stream(
            "GET",
            url,
            headers={"Accept": "application/json", "User-Agent": "OLA-CLI-Hub-Discovery/0.1"},
            timeout=TIMEOUT,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > MAX_REGISTRY_BYTES:
                    raise CliHubError("CLI-Hub registry exceeds 524288-byte limit")
                body.extend(chunk)
    except CliHubError:
        raise
    except httpx.TimeoutException as exc:
        raise CliHubError(f"CLI-Hub registry request timed out: {url}") from exc
    except httpx.HTTPError as exc:
        raise CliHubError(f"CLI-Hub registry request failed: {url}") from exc

    raw = bytes(body)
    try:
        registry = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CliHubError(f"CLI-Hub registry returned invalid JSON: {url}") from exc
    if not isinstance(registry, dict) or not isinstance(registry.get("clis"), list):
        raise CliHubError(f"CLI-Hub registry schema is invalid: {url}")
    return registry, raw


def search_catalog(query):
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_LENGTH:
        raise ValueError("CLI-Hub query must contain 1 to 120 characters")
    query = query.strip().casefold()

    harness, harness_raw = _fetch_registry(REGISTRY_URL)
    public, public_raw = _fetch_registry(PUBLIC_REGISTRY_URL)
    if len(harness_raw) + len(public_raw) > MAX_TOTAL_REGISTRY_BYTES:
        raise CliHubError("combined CLI-Hub registries exceed 1048576-byte limit")

    matches = []
    for source, registry in (("harness", harness), ("public", public)):
        for item in registry["clis"]:
            if not isinstance(item, dict):
                continue
            searchable_fields = (
                item.get("name", ""),
                item.get("display_name", ""),
                item.get("description", ""),
                item.get("category", ""),
            )
            if not any(query in str(value).casefold() for value in searchable_fields):
                continue
            # Registry-provided install commands, executable paths, and source
            # instructions are untrusted and never passed to the model.
            result = {
                key: item[key]
                for key in ("name", "display_name", "version", "description", "category", "requires")
                if isinstance(item.get(key), (str, int, float))
            }
            result["catalog_source"] = source
            matches.append(result)
            if len(matches) >= MAX_RESULTS:
                break
        if len(matches) >= MAX_RESULTS:
            break

    harness_meta = harness.get("meta") if isinstance(harness.get("meta"), dict) else {}
    public_meta = public.get("meta") if isinstance(public.get("meta"), dict) else {}
    return {
        "provider": "cli-hub",
        "operation": "search",
        "query": query,
        "coverage": "HARNESS_AND_PUBLIC",
        "registry_updated": harness_meta.get("updated") if isinstance(harness_meta.get("updated"), str) else None,
        "public_registry_updated": public_meta.get("updated") if isinstance(public_meta.get("updated"), str) else None,
        "matches": matches,
        "match_count": len(matches),
        "registry_sha256": hashlib.sha256(harness_raw).hexdigest(),
        "public_registry_sha256": hashlib.sha256(public_raw).hexdigest(),
        "registry_bytes": len(harness_raw),
        "public_registry_bytes": len(public_raw),
        "sources": [REGISTRY_URL, PUBLIC_REGISTRY_URL],
    }
