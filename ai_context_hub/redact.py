from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .models import Conversation


HIGH_RISK = {"private_key", "github_token", "api_key", "authorization", "cookie"}


@dataclass
class RedactionResult:
    text: str
    findings: dict[str, int] = field(default_factory=dict)

    @property
    def high_risk(self) -> bool:
        return any(self.findings.get(name, 0) for name in HIGH_RISK)


PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?"
            r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED:private_key]",
    ),
    (
        "github_token",
        re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})"),
        "[REDACTED:github_token]",
    ),
    (
        "api_key",
        re.compile(
            r"(?:sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|"
            r"AKIA[0-9A-Z]{16})"
        ),
        "[REDACTED:api_key]",
    ),
    (
        "authorization",
        re.compile(
            r"(?im)^(\s*authorization\s*:\s*)(?:bearer\s+)?"
            r"(?!\s*\[REDACTED:authorization\])[^\s]+"
        ),
        r"\1[REDACTED:authorization]",
    ),
    (
        "cookie",
        re.compile(
            r"(?im)^(\s*(?:set-)?cookie\s*:\s*)"
            r"(?!\s*\[REDACTED:cookie\]).+$"
        ),
        r"\1[REDACTED:cookie]",
    ),
    (
        "secret_assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|client[_-]?secret|access[_-]?token|"
            r"refresh[_-]?token|token|password|passwd)\b"
            r"(\s*[:=]\s*)(['\"]?)(?!\[REDACTED:)([^\s'\"`]{8,})\3"
        ),
        r"\1\2[REDACTED:secret]",
    ),
    (
        "env_value",
        re.compile(
            r"(?m)^([A-Z][A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|COOKIE))"
            r"\s*=\s*(?!\s*\[REDACTED:|<hidden>)(\S{8,})$"
        ),
        r"\1=[REDACTED:env_value]",
    ),
    (
        "email",
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        "[REDACTED:email]",
    ),
    (
        "phone",
        re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"),
        "[REDACTED:phone]",
    ),
    (
        "local_path",
        re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+(?:\\[^\s]+)*"),
        "[REDACTED:local_path]",
    ),
]


PLACEHOLDER_RE = re.compile(
    r"\[REDACTED:[^\]]+\]|(?:example|sample|dummy|replace[-_]?me|your[-_]?token)",
    re.IGNORECASE,
)


def redact_text(text: str) -> RedactionResult:
    findings: dict[str, int] = {}
    result = text.replace("\x00", "")
    result = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", result)
    for name, pattern, replacement in PATTERNS:
        result, count = pattern.subn(replacement, result)
        if count:
            findings[name] = findings.get(name, 0) + count
    return RedactionResult(text=result, findings=findings)


def merge_findings(items: Iterable[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for item in items:
        for key, value in item.items():
            merged[key] = merged.get(key, 0) + value
    return merged


def redact_conversation(conversation: Conversation) -> tuple[Conversation, dict[str, int]]:
    redacted = conversation.model_copy(deep=True)
    findings: list[dict[str, int]] = []
    title_result = redact_text(redacted.title)
    redacted.title = title_result.text
    findings.append(title_result.findings)
    for message in redacted.messages:
        result = redact_text(message.text)
        message.text = result.text
        findings.append(result.findings)
    return redacted, merge_findings(findings)


def has_high_risk(findings: dict[str, int]) -> bool:
    return any(findings.get(name, 0) for name in HIGH_RISK)
