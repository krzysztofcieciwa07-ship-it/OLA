"""Read-only adapter for the official CLI-Hub public registry.

The adapter reads catalogue metadata only. It never installs, updates,
uninstalls, launches, or executes a discovered CLI.
"""
import hashlib
import json

import httpx


REGISTRY_URL = "https://clianything.cc/registry.json"
MAX_QUERY_LENGTH = 120
MAX_REGISTRY_BYTES = 524288
MAX_RESULTS = 20
TIMEOUT = httpx.Timeout(8.0, connect=3.0)


class CliHubError(RuntimeError):
    """The public CLI-Hub catalogue could not be safely read."""


def search_catalog(query):
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_LENGTH:
        raise ValueError("CLI-Hub query must contain 1 to 120 characters")
    query = query.strip()
    terms = tuple(term for term in query.casefold().split() if term)
    body = bytearray()

    try:
        with httpx.stream(
            "GET",
            REGISTRY_URL,
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
        raise CliHubError("CLI-Hub registry request timed out") from exc
    except httpx.HTTPError as exc:
        raise CliHubError("CLI-Hub registry request failed") from exc

    raw = bytes(body)
    try:
        registry = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CliHubError("CLI-Hub registry returned invalid JSON") from exc
    if not isinstance(registry, dict) or not isinstance(registry.get("clis"), list):
        raise CliHubError("CLI-Hub registry schema is invalid")

    matches = []
    for item in registry["clis"]:
        if not isinstance(item, dict):
            continue
        searchable = " ".join(
            str(item.get(key, "")) for key in ("name", "display_name", "description", "category")
        ).casefold()
        if not all(term in searchable for term in terms):
            continue
        # Never return install commands, source instructions, or executable paths
        # from the external registry to the model as trusted instructions.
        matches.append({
            key: item.get(key)
            for key in ("name", "display_name", "version", "description", "category", "requires")
            if isinstance(item.get(key), (str, int, float))
        })
        if len(matches) >= MAX_RESULTS:
            break

    meta = registry.get("meta") if isinstance(registry.get("meta"), dict) else {}
    return {
        "provider": "cli-hub",
        "operation": "search",
        "query": query,
        "registry_updated": meta.get("updated") if isinstance(meta.get("updated"), str) else None,
        "matches": matches,
        "match_count": len(matches),
        "registry_sha256": hashlib.sha256(raw).hexdigest(),
        "registry_bytes": len(raw),
        "source": REGISTRY_URL,
    }
