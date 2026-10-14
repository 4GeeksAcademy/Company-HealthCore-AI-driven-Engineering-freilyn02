"""What may NEVER enter the agent memory, and what a valid memory fact looks like.

Aligned with the HealthCore memory CONTEXT (MEM-092):
  - Worth remembering: recurring operational corrections per clinic, known incident patterns
    WITHOUT patient data, and how a staff member wants operational information presented.
  - NEVER: any patient identifier (name, record number, date of birth, diagnosis, insurance
    number, or any combination that could re-identify a person) and any clinical content
    (notes, lab results, anything from a medical visit). No exceptions.

HealthCore operates under HIPAA (US) and UK GDPR (UK) at the same time, so every rule below
is mapped to BOTH frameworks in FRAMEWORK_COVERAGE (and documented in docs/agent-memory.md).
The checks are lexical (regular expressions): they are one layer of defense and they err on
the side of rejecting. They are NOT a replacement for the compliance review.

Memory facts are statements about HealthCore operations. They are never instructions to the
agent and never patient data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..harness.input_guards import check_input

MAX_FACT_CHARS = 280
MAX_KEYS = 6

# Kinds of facts worth remembering (from the HealthCore memory CONTEXT).
MEMORABLE_KINDS = {
    "clinic_operational_correction": (
        "A recurring operational correction for a clinic: a schedule change, a local front-desk "
        "protocol or an administrative exception, by clinic or by country (US vs. UK)."
    ),
    "incident_pattern": (
        "A known incident pattern with NO patient data, e.g. a system that fails at a predictable "
        "time and why."
    ),
    "staff_presentation_preference": (
        "How a clinical or admin staff member wants OPERATIONAL (never clinical) information "
        "presented to them."
    ),
}

_I = re.IGNORECASE
_IS = re.IGNORECASE | re.DOTALL

# Capitalized words that often follow the word "patient" without being a person's name.
_NOT_A_NAME = (
    "Portal|Safety|Services?|Experience|Care|Records?|Flow|Satisfaction|Access|Education|"
    "Engagement|Support|Intake|Registration|Referrals?|Transport|Advocates?|Relations|Billing|"
    "Data|Information|Privacy|Rights|Communications?|Management|Coordinators?"
)

# Restricted data: matches are never stored AND never copied into the audit log.
# Each entry is (regex, flags). Checked in this order; the first match wins.
_SENSITIVE: dict[str, tuple[str, int]] = {
    # --- direct identifiers --------------------------------------------------------------
    "email": (r"[\w.+-]+@[\w-]+\.[\w.-]+", _I),
    "nhs_number": (r"\bnhs\s*(?:number|no\.?|num|#)", _I),
    "phone": (r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)", _I),
    "ssn": (r"\b\d{3}-\d{2}-\d{4}\b", _I),
    "long_number": (r"\b\d{8,}\b", _I),  # record numbers, card numbers, account numbers
    "national_insurance": (r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", _I),
    "insurance_id": (
        r"\b(?:insurance|insurer|policy|member|subscriber|beneficiary|medicare|medicaid|health\s*plan)"
        r"\s*(?:id|number|no\.|#)",
        _I,
    ),
    "date_of_birth": (r"\b(?:dob|date of birth|born on|birth\s?day)\b", _I),
    "medical_record": (
        r"\b(?:mrn|medical record|health record|patient\s*(?:#|number\b|id\b|no\.\s*\d|no\s+\d))",
        _I,
    ),
    # --- a person who is a patient --------------------------------------------------------
    # "Patient Johnson", "patient John Smith", "the patient's name is...", "patient named...".
    # The name itself must be capitalized, so "patient cancelled" is not flagged but
    # "Patient Johnson" is. Lowercase names are a known limit (see docs/agent-memory.md).
    "patient_name": (
        r"(?i:\b(?:patients?|pt)\b)[:,]?\s+(?!(?:" + _NOT_A_NAME + r")\b)"
        r"(?:(?i:named|called)\s+)?(?:(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+)?[A-Z][a-z]+"
        r"|(?i:\b(?:patients?|pt)\b)(?:['\u2019]s)?\W+(?i:name|named|called)\b",
        0,
    ),
    "patient_address": (
        r"\b(?:patients?|pt)\b.{0,40}\b(?:address|lives?|living|reside[sd]?|residen\w+|postcode|zip\s?code)\b",
        _IS,
    ),
    "patient_date": (
        r"\b(?:patients?|pt)\b.{0,60}\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        _IS,
    ),
    # --- clinical content: notes, results, anything from a medical visit -------------------
    "clinical_content": (
        r"\b(?:diagnos(?:is|es|ed|tic)|prognosis|prescri(?:be|bed|ption|ptions)|medications?|dosage|"
        r"lab results?|test results?|blood (?:test|work|pressure)|biopsy|symptoms?|treatment plan|"
        r"clinical notes?|visit notes?|chart notes?|discharge (?:summary|notes?)|"
        r"(?:x-?ray|mri|ct|scan|ultrasound) results?)\b",
        _I,
    ),
    # A named condition counts only next to a patient reference or a personal pronoun.
    "patient_condition": (
        r"\b(?:patients?|pt|he|she|his|her)\b.{0,60}\b(?:diabet\w+|cancer|hiv|aids|asthma|"
        r"hypertension|depress\w+|anxiety|pregnan\w+|covid|tuberculosis|epilepsy|stroke|dementia|"
        r"schizophreni\w+|bipolar|infection|fracture|surgery)\b",
        _IS,
    ),
    "credential": (r"\b(?:password|passwd|api[_ -]?key|secret|bearer|access token)\b", _I),
}

SENSITIVE_PATTERNS: dict[str, re.Pattern] = {
    name: re.compile(pattern, flags) for name, (pattern, flags) in _SENSITIVE.items()
}

# Every category except credentials is patient or personal information (PHI / personal data).
PHI_CATEGORIES = frozenset(name for name in _SENSITIVE if name != "credential")

# How each category is covered by the two frameworks HealthCore operates under.
FRAMEWORK_COVERAGE: dict[str, str] = {
    "email": "HIPAA identifier (email address) / UK GDPR personal data (online identifier)",
    "phone": "HIPAA identifier (phone and fax numbers) / UK GDPR personal data",
    "ssn": "HIPAA identifier (Social Security number) / UK GDPR personal data",
    "long_number": "HIPAA identifiers (medical record, health plan and account numbers) / UK GDPR identification number",
    "national_insurance": "UK GDPR personal data (National Insurance number) / HIPAA 'any other unique identifier'",
    "nhs_number": "UK GDPR identifier linked to health data (NHS number) / HIPAA 'any other unique identifier'",
    "insurance_id": "HIPAA identifier (health plan beneficiary number) / UK GDPR personal data",
    "date_of_birth": "HIPAA identifier (dates related to an individual) / UK GDPR personal data",
    "medical_record": "HIPAA identifier (medical record number) / UK GDPR identification number",
    "patient_name": "HIPAA identifier (names) / UK GDPR personal data (name of a data subject)",
    "patient_address": "HIPAA identifier (geographic data smaller than a state) / UK GDPR personal data (location)",
    "patient_date": "HIPAA identifier (dates related to an individual) / UK GDPR personal data",
    "clinical_content": "HIPAA protected health information / UK GDPR special category data (health, Art. 9)",
    "patient_condition": "HIPAA protected health information / UK GDPR special category data (health, Art. 9)",
    "credential": "Security rule (not patient data): secrets never belong in memory",
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
    phi: bool = False  # True -> patient or personal information (HIPAA / UK GDPR)


def inspect(text: str) -> Inspection:
    """Check ANY text (a proposed fact or a user message) against the memory policy."""
    for name, pattern in SENSITIVE_PATTERNS.items():
        if pattern.search(text):
            return Inspection(f"forbidden:{name}", sensitive=True, phi=name in PHI_CATEGORIES)
    for name, pattern in POISON_PATTERNS.items():
        if pattern.search(text):
            return Inspection(f"poison:{name}", sensitive=False)
    decision = check_input(text)  # reuse the harness: PHI, injection, jailbreak
    if decision.action == "block":
        return Inspection(f"guard:{decision.guardrail}", sensitive=decision.sensitive, phi=decision.sensitive)
    return Inspection()


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    reason: str | None = None
    sensitive: bool = False
    phi: bool = False


def validate_fact(fact: str, keys: list[str] | None = None) -> PolicyResult:
    """Final gate before a proposal is shown, a memory is written or a memory is consolidated."""
    fact = (fact or "").strip()
    if not fact:
        return PolicyResult(False, "empty_fact")
    if len(fact) > MAX_FACT_CHARS:
        return PolicyResult(False, "fact_too_long")
    if keys is not None and (len(keys) > MAX_KEYS or not all(isinstance(k, str) for k in keys)):
        return PolicyResult(False, "invalid_keys")
    inspection = inspect(fact)
    if inspection.violation:
        return PolicyResult(False, inspection.violation, inspection.sensitive, inspection.phi)
    # The keywords are stored and searched too, so they must pass the same policy.
    for key in keys or []:
        key_inspection = inspect(key)
        if key_inspection.violation:
            return PolicyResult(False, f"key_{key_inspection.violation}", key_inspection.sensitive,
                                key_inspection.phi)
    return PolicyResult(True)
