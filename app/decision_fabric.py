"""OLA Decision Fabric.

Typed decision layer inspired by TypeSafe/Jev, but owned by OLA:
- Choice: closed-set routing
- Score: ordered rubric
- Noul: probability of a yes/no proposition

The provider is replaceable. Policy, execution, evidence and promotion remain
outside the model and stay fail-closed.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

import httpx


JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_JEV_MODEL = "jev-1.13.0"


class DecisionProvider(Protocol):
    name: str

    def evaluate(
        self,
        *,
        state: Any,
        questions: Mapping[str, Mapping[str, Any]],
        model: str,
    ) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class DecisionResult:
    provider: str
    model: str
    answers: dict[str, Any]
    request_sha256: str
    response_sha256: str
    request_id: str | None
    status: str
    reason: str = ""


@dataclass(frozen=True)
class DecisionPolicy:
    min_choice_confidence: float = 0.70
    min_score_confidence: float = 0.70
    noul_yes_threshold: float = 0.80
    noul_no_threshold: float = 0.20

    def classify(self, answer: Mapping[str, Any]) -> str:
        kind = answer.get("type")
        if kind == "choice":
            confidence = float(answer.get("confidence", 0.0))
            return "ACCEPT" if confidence >= self.min_choice_confidence else "REVIEW"
        if kind == "score":
            confidence = float(answer.get("confidence", 0.0))
            return "ACCEPT" if confidence >= self.min_score_confidence else "REVIEW"
        if kind == "noul":
            value = float(answer.get("noul", 0.5))
            if value >= self.noul_yes_threshold:
                return "YES"
            if value <= self.noul_no_threshold:
                return "NO"
            return "REVIEW"
        return "BLOCK"


class JevProvider:
    """Thin HTTP provider for TypeSafe System One.

    No API key means BLOCK/UNKNOWN at the OLA boundary; there is no silent
    deterministic fallback. This keeps model availability separate from
    OLA's authorization policy.
    """

    name = "typesafe-jev"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 2,
        endpoint: str = JEV_ENDPOINT,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("TYPESAFE_API_KEY")
        self.timeout = timeout
        self.max_retries = max_retries
        self.endpoint = endpoint
        self._client = client

    def evaluate(
        self,
        *,
        state: Any,
        questions: Mapping[str, Mapping[str, Any]],
        model: str,
    ) -> Mapping[str, Any]:
        if not self.api_key:
            raise RuntimeError("TYPESAFE_API_KEY is not configured")

        payload = {
            "model": model,
            "state": state,
            "questions": dict(questions),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            last_error: Exception | None = None
            for attempt in range(self.max_retries + 1):
                try:
                    response = client.post(self.endpoint, json=payload, headers=headers)
                    if response.status_code in {401, 422}:
                        response.raise_for_status()
                    if response.status_code in {408, 429, 500, 502, 503, 504, 529}:
                        if attempt < self.max_retries:
                            time.sleep(2**attempt)
                            continue
                    response.raise_for_status()
                    return {
                        "body": response.json(),
                        "request_id": response.headers.get("x-request-id"),
                    }
                except (httpx.HTTPError, ValueError) as exc:
                    last_error = exc
                    if attempt < self.max_retries:
                        time.sleep(2**attempt)
                        continue
                    raise
            raise RuntimeError(str(last_error or "Jev request failed"))
        finally:
            if owns_client:
                client.close()


class DecisionFabric:
    """Coordinates typed judgments without owning terminal authorization."""

    def __init__(
        self,
        provider: DecisionProvider | None = None,
        *,
        model: str = DEFAULT_JEV_MODEL,
        policy: DecisionPolicy | None = None,
    ) -> None:
        self.provider = provider or JevProvider()
        self.model = model
        self.policy = policy or DecisionPolicy()

    @staticmethod
    def _sha(value: Any) -> str:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def evaluate(
        self,
        *,
        state: Any,
        questions: Mapping[str, Mapping[str, Any]],
    ) -> DecisionResult:
        request = {"model": self.model, "state": state, "questions": dict(questions)}
        request_sha = self._sha(request)
        try:
            raw = self.provider.evaluate(
                state=state,
                questions=questions,
                model=self.model,
            )
            body = dict(raw.get("body", raw))
            answers = dict(body.get("answers", {}))
            if set(answers) != set(questions):
                return DecisionResult(
                    provider=self.provider.name,
                    model=self.model,
                    answers=answers,
                    request_sha256=request_sha,
                    response_sha256=self._sha(body),
                    request_id=raw.get("request_id") if isinstance(raw, Mapping) else None,
                    status="BLOCK",
                    reason="provider answer set does not match requested questions",
                )
            return DecisionResult(
                provider=self.provider.name,
                model=str(body.get("model", self.model)),
                answers=answers,
                request_sha256=request_sha,
                response_sha256=self._sha(body),
                request_id=raw.get("request_id") if isinstance(raw, Mapping) else None,
                status="READY",
            )
        except Exception as exc:
            return DecisionResult(
                provider=self.provider.name,
                model=self.model,
                answers={},
                request_sha256=request_sha,
                response_sha256=self._sha({"error": exc.__class__.__name__}),
                request_id=None,
                status="BLOCK",
                reason=f"decision provider unavailable: {exc.__class__.__name__}",
            )

    def classify(self, result: DecisionResult) -> dict[str, str]:
        if result.status != "READY":
            return {name: "BLOCK" for name in result.answers}
        return {name: self.policy.classify(answer) for name, answer in result.answers.items()}

    def evidence(self, result: DecisionResult) -> dict[str, Any]:
        return {
            "schema": "ola.decision.v1",
            "provider": result.provider,
            "model": result.model,
            "status": result.status,
            "reason": result.reason,
            "request_sha256": result.request_sha256,
            "response_sha256": result.response_sha256,
            "request_id": result.request_id,
            "answers": result.answers,
            "classifications": self.classify(result),
        }
