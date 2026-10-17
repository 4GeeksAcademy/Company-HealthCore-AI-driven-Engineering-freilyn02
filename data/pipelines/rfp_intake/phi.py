"""PHI guard: deterministic detection and redaction of patient identifiers.

HealthCore operates under HIPAA (US) and UK GDPR (UK). The raw document text is
scanned BEFORE any LLM agent, log, database column or Markdown file sees it.

Design decisions:
- Deterministic regex rules, NOT an LLM: sending the raw text to a model to ask
  "does this contain PHI?" would already be a PHI leak.
- Findings only contain COUNTS by type, never the detected values.
- It is a heuristic guard (labelled fields such as "Patient name:", "DOB:",
  "MRN:", "Diagnosis:", ...). It does not replace the Compliance human review,
  which is exactly why a detection blocks the handoff to Part 2.
"""
import re
from typing import Any

TOKENS = {
    "patient_name": "[REDACTED_PATIENT_NAME]",
    "dob": "[REDACTED_DOB]",
    "record_id": "[REDACTED_RECORD_ID]",
    "ssn": "[REDACTED_SSN]",
    "nhs_number": "[REDACTED_NHS_NUMBER]",
    "diagnosis": "[REDACTED_DIAGNOSIS]",
}

_NAME = r"(?:(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+)?[A-Z][a-zA-Z'\-]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-zA-Z'\-]+)+"

# (type, regex). Every regex has a named group `v` = the sensitive value to replace.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "patient_name",
        re.compile(
            r"(?P<label>(?i:\b(?:patient(?:'s)?\s+name|name\s+of\s+(?:the\s+)?patient|patient|pt)\s*[:\-\u2013]\s*))"
            rf"(?P<v>{_NAME})"
        ),
    ),
    (
        "dob",
        re.compile(
            r"(?P<label>(?i:\b(?:dob|d\.o\.b\.|date\s+of\s+birth|born(?:\s+on)?)\s*[:\-]?\s*))"
            r"(?P<v>\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2}"
            r"|[A-Z][a-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[A-Z][a-z]+\s+\d{4})"
        ),
    ),
    (
        "record_id",
        re.compile(
            r"(?P<label>(?i:\b(?:mrn|medical\s+record(?:\s+(?:number|no\.?|\#))?|patient\s+(?:id|number)"
            r"|chart\s+(?:number|no\.?)|member\s+id)\s*[:\#\-]?\s*))"
            r"(?P<v>(?=[A-Za-z0-9\-]*\d)[A-Za-z0-9][A-Za-z0-9\-]{3,})"
        ),
    ),
    ("ssn", re.compile(r"\b(?P<v>\d{3}-\d{2}-\d{4})\b")),
    (
        "nhs_number",
        re.compile(
            r"(?P<label>(?i:\bnhs\s*(?:number|no\.?|\#)?\s*[:\#\-]?\s*))"
            r"(?P<v>\d{3}[ \-]?\d{3}[ \-]?\d{4})\b"
        ),
    ),
    (
        "diagnosis",
        re.compile(
            r"(?P<label>(?i:\b(?:diagnosis|diagnoses|dx)\s*[:\-\u2013]\s*|diagnosed\s+with\s+))"
            r"(?P<v>[^.\n;]{3,120})"
        ),
    ),
    # "Jane Doe, a 54-year-old ..." (a person described by age, no label)
    (
        "patient_name",
        re.compile(r"(?P<v>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)(?=,?\s+(?:a\s+)?\d{1,3}[- ]year[- ]old)"),
    ),
]


def _replacer(token: str):
    def _repl(match: re.Match[str]) -> str:
        full = match.group(0)
        start, end = match.span("v")
        base = match.start()
        return full[: start - base] + token + full[end - base :]

    return _repl


def scan_and_redact(text: str) -> tuple[str, dict[str, Any]]:
    """Returns (redacted_text, {"contains_phi": bool, "findings": {type: count}})."""
    findings: dict[str, int] = {}
    for kind, pattern in _RULES:
        text, count = pattern.subn(_replacer(TOKENS[kind]), text)
        if count:
            findings[kind] = findings.get(kind, 0) + count
    return text, {"contains_phi": bool(findings), "findings": findings}


def redact_text(text: str) -> str:
    """Redacts a string and drops the findings (used as a last-line defense)."""
    return scan_and_redact(text)[0]


def scrub_obj(obj: Any) -> Any:
    """Recursively redacts every string inside dicts/lists (e.g. before persisting)."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {key: scrub_obj(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [scrub_obj(value) for value in obj]
    return obj
