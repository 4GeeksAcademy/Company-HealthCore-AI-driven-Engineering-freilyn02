"""What may NEVER enter the agent memory, and what a valid memory fact looks like.

Memory facts are statements about HealthCore (a corrected policy, a resolved-escalation
pattern). They are never instructions to the agent and never patient data.

NOTE: the lists below are the generic baseline. They must be aligned with the
"never enter memory" section of the memory CONTEXT for HealthCore (see MEM-092).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..harness.input_guards import check_input

MAX_FACT_CHARS = 280
MAX_KEYS = 6

# Kinds of facts worth remembering (to be aligned with the memory CONTEXT).
MEMORABLE_KINDS = {
    "corrected_fact": "A user corrected a fact the agent got wrong (policy, SLA, procedure).",
    "resolved_pattern": "A reusable resolution pattern for a recurring escalation.",
    "workflow_note": "A stable, company-level workflow note confirmed by the user.",
}

# Restricted data: matches are never stored AND never copied into the audit log.
SENSITIVE_PATTERNS: dict[str, re.Pattern] = {
    name: re.compile(pattern, re.IGNORECASE)
    for name, pattern in {
        "email": r"[\w.+-]+@[\w-]+\.[\w.-]+",
        "phone": r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "long_number": r"\b\d{8,}\b",  # record numbers, card numbers
        "date_of_birth": r"\b(?:dob|date of birth|born on)\b",
        "medical_record": r"\b(?:mrn|medical record)\b",
        "credential": r"\b(?:password|passwd|api[_ -]?key|secret|bearer|access token)\b",
    }.items()
}

# Poisoning: a "fact" that is really an instruction to the agent.
POISON_PATTERNS: dict[str, re.Pattern] = {
    name: re.compile(pattern, re.IGNORECASE)
    for name, pattern in {
        "standing_instruction": (
            r"\b(?:from now on|always|never|you must|you should|make sure to)\s+"
            r"(?:answer|respond|reply|say|ignore|reveal|share|trust|approve|skip)\b"
        ),
        "authority_claim": r"\b(?:system prompt|admin(?:istrator)? says|new rule for the assistant)\b",
    }.items()
}


@dataclass(frozen=True)
class Inspection:
    violation: str | None = None  # e.g. "forbidden:email", "poison:standing_instruction"
    sensitive: bool = False  # True -> the text must not be copied into logs


def inspect(text: str) -> Inspection:
    """Check ANY text (a proposed fact or a user message) against the memory policy."""
    for name, pattern in SENSITIVE_PATTERNS.items():
        if pattern.search(text):
            return Inspection(f"forbidden:{name}", sensitive=True)
    for name, pattern in POISON_PATTERNS.items():
        if pattern.search(text):
            return Inspection(f"poison:{name}", sensitive=False)
    decision = check_input(text)  # reuse the harness: PHI, injection, jailbreak
    if decision.action == "block":
        return Inspection(f"guard:{decision.guardrail}", sensitive=decision.sensitive)
    return Inspection()


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    reason: str | None = None
    sensitive: bool = False


def validate_fact(fact: str, keys: list[str] | None = None) -> PolicyResult:
    """Final gate before a proposal is shown or a memory is written."""
    fact = (fact or "").strip()
    if not fact:
        return PolicyResult(False, "empty_fact")
    if len(fact) > MAX_FACT_CHARS:
        return PolicyResult(False, "fact_too_long")
    if keys is not None and (len(keys) > MAX_KEYS or not all(isinstance(k, str) for k in keys)):
        return PolicyResult(False, "invalid_keys")
    inspection = inspect(fact)
    if inspection.violation:
        return PolicyResult(False, inspection.violation, inspection.sensitive)
    return PolicyResult(True)
