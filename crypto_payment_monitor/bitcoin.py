"""Read-only Bitcoin address adapter for an Esplora-compatible HTTPS endpoint."""
import json
import urllib.request

class Esplora:
    def __init__(self, endpoint: str):
        if not endpoint.startswith("https://"):
            raise ValueError("HTTPS endpoint required")
        self.endpoint = endpoint.rstrip("/")

    def address_transactions(self, address: str) -> list[dict]:
        # Caller must validate address/network before querying.
        req = urllib.request.Request(f"{self.endpoint}/address/{address}/txs", headers={"Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read())
        if not isinstance(data, list):
            raise ValueError("unexpected Esplora response")
        return data
