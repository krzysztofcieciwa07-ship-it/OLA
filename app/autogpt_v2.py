"""Optional AutoGPT Platform API v2 bridge; never grants OLA verification.

The remote service runs a library agent, not an OLA execution capability.
Remote completion is an observation; IGOR and Human Gate stay independent.
No AutoGPT Platform source code is embedded here.
"""

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


_STATUSES = frozenset({
    "INCOMPLETE", "QUEUED", "RUNNING", "COMPLETED", "TERMINATED", "FAILED", "REVIEW",
})
_MAX_RESPONSE = 262_144


class AutoGPTBridgeError(RuntimeError):
    """Only safe, credential-free messages may leave this boundary."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class AutoGPTV2Client:
    def __init__(self, *, base_url, api_key, agent_id, input_field, allowed_hosts,
                 allow_local_http=False, timeout=10, opener=None):
        parsed = urlsplit(base_url)
        allowed = {item.strip().lower() for item in allowed_hosts if item.strip()}
        if (not parsed.hostname or parsed.hostname.lower() not in allowed
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path.rstrip("/") != "/api/v2"
                or not (parsed.scheme == "https" or
                        (allow_local_http and parsed.scheme == "http"
                         and parsed.hostname in {"localhost", "127.0.0.1"}))):
            raise AutoGPTBridgeError("AutoGPT API origin is not allowlisted")
        if not isinstance(api_key, str) or not api_key.strip():
            raise AutoGPTBridgeError("AutoGPT API credentials are not configured")
        if not isinstance(agent_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", agent_id):
            raise AutoGPTBridgeError("AutoGPT library agent ID is not configured")
        if not isinstance(input_field, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", input_field):
            raise AutoGPTBridgeError("AutoGPT agent input field is not configured")
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
            raise AutoGPTBridgeError("AutoGPT request timeout outside policy")
        self._base = base_url.rstrip("/")
        self._key = api_key.strip()
        self.agent_id = agent_id
        self.input_field = input_field
        self._timeout = timeout
        self._opener = opener or build_opener(_NoRedirect())

    @classmethod
    def from_environment(cls):
        return cls(
            base_url=os.getenv("OLA_AUTOGPT_API_URL", "https://backend.agpt.co/api/v2"),
            api_key=os.getenv("OLA_AUTOGPT_API_KEY", ""),
            agent_id=os.getenv("OLA_AUTOGPT_AGENT_ID", ""),
            input_field=os.getenv("OLA_AUTOGPT_INPUT_FIELD", ""),
            allowed_hosts=os.getenv("OLA_AUTOGPT_ALLOWED_HOSTS", "backend.agpt.co").split(","),
            allow_local_http=os.getenv("OLA_AUTOGPT_ALLOW_LOCAL_HTTP") == "1",
        )

    def _call(self, path, *, method, payload=None, idempotency_key=None, expected_status):
        headers = {"X-API-Key": self._key, "Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request = Request(self._base + path, headers=headers, data=data, method=method)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != expected_status:
                    raise AutoGPTBridgeError("AutoGPT returned an unexpected HTTP status")
                raw = response.read(_MAX_RESPONSE + 1)
        except HTTPError as exc:
            # Never return headers, bodies or request URLs: they may contain secrets.
            raise AutoGPTBridgeError(f"AutoGPT request rejected (HTTP {exc.code})") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise AutoGPTBridgeError("AutoGPT connection unavailable") from None
        if len(raw) > _MAX_RESPONSE:
            raise AutoGPTBridgeError("AutoGPT response exceeds size policy")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise AutoGPTBridgeError("AutoGPT returned invalid JSON") from None
        if (not isinstance(result, dict) or not isinstance(result.get("id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", result["id"])
                or result.get("status") not in _STATUSES):
            raise AutoGPTBridgeError("AutoGPT run response does not match v2 contract")
        return result

    def start(self, task, *, idempotency_key):
        if not isinstance(task, str) or not task.strip() or len(task) > 2000:
            raise AutoGPTBridgeError("task outside policy")
        if not isinstance(idempotency_key, str) or not re.fullmatch(r"[a-f0-9]{64}", idempotency_key):
            raise AutoGPTBridgeError("idempotency key outside policy")
        response = self._call(
            "/library/agents/" + quote(self.agent_id, safe="") + "/runs",
            method="POST", payload={"inputs": {self.input_field: task.strip()}},
            idempotency_key=idempotency_key, expected_status=202,
        )
        return {"run_id": response["id"], "remote_status": response["status"]}

    def poll(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", run_id):
            raise AutoGPTBridgeError("invalid run ID")
        response = self._call("/runs/" + quote(run_id, safe=""), method="GET", expected_status=200)
        if response["id"] != run_id:
            raise AutoGPTBridgeError("AutoGPT run identity mismatch")
        return {"run_id": run_id, "remote_status": response["status"],
                "outputs": response.get("outputs") if response["status"] == "COMPLETED" else None}
