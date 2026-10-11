"""Vantage advisory detector adapter. Never grants execution permissions.

Heuristic matches are signals, not authorization. Existing ExecutionSafetyGate
remains the only executor. Unknown input sources fail closed.
"""
from __future__ import annotations
import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass

TRUSTED_SOURCES = frozenset({"verified_api", "known_partner", "user_upload", "public_web", "anonymous_tool"})
SIGNATURES = (
    ("override", r"ignore\s+all\s+previous|zignoruj\s+wszystkie"),
    ("system_impersonation", r"system\s*message|wiadomość\s+systemowa"),
    ("secret_exfiltration", r"(?:send|upload|email|post|wyślij).{0,80}(?:secret|password|hasło|token)"),
    ("privilege_escalation", r"privilege\s+escalation|escalate\s+privileges"),
)
TRANSLATION = str.maketrans({"і": "i", "ο": "o", "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x"})


@dataclass(frozen=True)
class VantageAssessment:
    verdict: str
    signals: tuple[str, ...]
    source: str
    policy: str = "advisory-deny-by-default"


def assess(text: str, source: str = "user_upload") -> VantageAssessment:
    if not isinstance(text, str) or source not in TRUSTED_SOURCES:
        return VantageAssessment("BLOCK", ("invalid_input_or_source",), str(source))
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(" " if unicodedata.category(ch) == "Cf" else ch for ch in normalized).translate(TRANSLATION)
    candidates = [normalized]
    for token in re.findall(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{16,}={0,2}(?![A-Za-z0-9+/])", normalized):
        try:
            decoded = base64.b64decode(token, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded.isprintable() and len(decoded) <= 4096:
            candidates.append(decoded)
    signals = tuple(sorted({name for candidate in candidates for name, pattern in SIGNATURES if re.search(pattern, candidate, re.I)}))
    verdict = "HUMAN_APPROVAL" if signals else "ALLOW"
    if "secret_exfiltration" in signals and ("override" in signals or "system_impersonation" in signals):
        verdict = "BLOCK"
    return VantageAssessment(verdict, signals, source)


def execution_risk(assessment: VantageAssessment) -> str:
    """ALLOW from advisory never overrides executor allowlist or human gate."""
    return "LOW" if assessment.verdict == "ALLOW" else "HIGH"
