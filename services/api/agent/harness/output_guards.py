"""Output guardrails: validate the final answer BEFORE it is returned to the user.

Checks (in order):
  structural -> empty / non-text / too long / internal markers (<untrusted_source>, role tags)
  content    -> system-prompt leak (8-word window overlap with the real prompts)
  content    -> credentials or tokens
  content    -> patient-identifying data (SSN, MRN, DOB, member id) per HealthCore CONTEXT

"Trusting the model not to leak" is not a defense, so this layer runs on every answer,
whatever path produced it (RAG, tools, refusals).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..prompts.system import (
    CASUAL_SYSTEM_PROMPT,
    EMPTY_OUTPUT_MESSAGE,
    SAFE_OUTPUT_MESSAGE,
    SYSTEM_PROMPT,
)
from .external_content import _ROLE_MARKER_RE, _WRAPPER_TAG_RE
from .input_guards import PHI_PATTERNS, normalize

MAX_ANSWER_CHARS = 4000
LEAK_WINDOW_WORDS = 8

# Credentials / tokens that must never appear in an answer.
SECRET_PATTERNS: dict[str, re.Pattern] = {
    name: re.compile(p, re.IGNORECASE)
    for name, p in {
        "bearer_token": r"\bbearer\s+[a-z0-9._~+/-]{16,}",
        "jwt": r"\beyj[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}",
        "api_key_prefix": r"\bsk-[a-z0-9_-]{16,}",
        "env_secret": r"\b(?:llm_api_key|api[_-]?key|client[_-]?secret|password)\s*[=:]\s*\S{6,}",
    }.items()
}

# Only the identifiers that must never leave the system. Phones/emails are NOT scanned in
# outputs because the knowledge base legitimately contains clinic contact details.
OUTPUT_PHI_KEYS = ("ssn", "medical_record_number", "date_of_birth", "member_id")


def _windows(prompt: str, size: int = LEAK_WINDOW_WORDS) -> set[str]:
    words = normalize(prompt).split()
    return {" ".join(words[i : i + size]) for i in range(max(len(words) - size + 1, 0))}


_PROMPT_WINDOWS = _windows(SYSTEM_PROMPT) | _windows(CASUAL_SYSTEM_PROMPT)


def leaks_system_prompt(answer: str) -> bool:
    words = " ".join(normalize(answer).split())
    return any(window in words for window in _PROMPT_WINDOWS)


@dataclass
class Finding:
    guardrail: str
    failure_type: str  # "structural" | "content"
    action: str  # "sanitize" | "replace"
    sensitive: bool = False


@dataclass
class OutputVerdict:
    answer: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.findings)


def guard_output(answer: object) -> OutputVerdict:
    """Return the (possibly replaced) answer plus what was found. Never raises."""
    # --- structural ---------------------------------------------------------------
    if not isinstance(answer, str) or not answer.strip():
        return OutputVerdict(EMPTY_OUTPUT_MESSAGE, [Finding("empty_output", "structural", "replace")])

    findings: list[Finding] = []
    text = answer

    stripped = _ROLE_MARKER_RE.sub("", _WRAPPER_TAG_RE.sub("", text))
    if stripped != text:
        text = stripped.strip()
        findings.append(Finding("internal_marker", "structural", "sanitize"))

    if len(text) > MAX_ANSWER_CHARS:
        text = text[:MAX_ANSWER_CHARS].rstrip() + "..."
        findings.append(Finding("answer_too_long", "structural", "sanitize"))

    # --- content: anything below replaces the whole answer with a safe refusal ------
    if leaks_system_prompt(text):
        return OutputVerdict(SAFE_OUTPUT_MESSAGE, findings + [Finding("system_prompt_leak", "content", "replace")])

    for name, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            return OutputVerdict(
                SAFE_OUTPUT_MESSAGE,
                findings + [Finding(f"credential_leak:{name}", "content", "replace", sensitive=True)],
            )

    for key in OUTPUT_PHI_KEYS:
        if PHI_PATTERNS[key].search(text):
            return OutputVerdict(
                SAFE_OUTPUT_MESSAGE,
                findings + [Finding(f"phi_in_output:{key}", "content", "replace", sensitive=True)],
            )

    return OutputVerdict(text, findings)
