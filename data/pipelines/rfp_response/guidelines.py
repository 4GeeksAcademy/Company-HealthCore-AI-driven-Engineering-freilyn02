"""Company guideline checklist used by the compliance evaluator.

This is a deterministic checklist (rule ids + code), NOT a free-style opinion of
the model. Every rule comes from what the HealthCore CONTEXT already decided in
Part 1 (currency by client country, BAA / DPA, no PHI, no invented figures).
Keep RULES in sync with the CONTEXT: add or rename a rule here and in check_guidelines.
"""
import json
import re
from typing import Any

from ..rfp_intake.phi import scan_and_redact

RULES: dict[str, str] = {
    "GUIDELINE_NO_PHI": "The draft must not contain patient identifiers (HIPAA / UK GDPR).",
    "GUIDELINE_CURRENCY_MATCHES_COUNTRY": "Amounts use the currency of the client country (US=USD, UK=GBP) and the revenue section states it.",
    "GUIDELINE_LEGAL_INSTRUMENT_BY_COUNTRY": "Compliance section names a BAA (US client) or a DPA under UK GDPR (UK client).",
    "GUIDELINE_NO_INVENTED_FIGURES": "Every amount or percentage must come from the RFP findings; otherwise write 'to be confirmed'.",
    "GUIDELINE_NO_UNVERIFIED_GUARANTEES": "No guarantees or risk-free promises that the RFP findings do not support.",
}

CURRENCY_MARKERS: dict[str, tuple[str, ...]] = {
    "USD": ("USD", "$"),
    "GBP": ("GBP", "£"),
}

MONEY_RE = re.compile(r"[$£€]\s?\d[\d,]*(?:\.\d+)?")
PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s?%")
GUARANTEE_RE = re.compile(r"\b(guarantee[sd]?|zero risk|risk-free)\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    return re.sub(r"[,\s]", "", text)


def _allowed_text(handoff: dict[str, Any]) -> str:
    """Everything the generator was allowed to use as a source of figures."""
    source = {
        "client": handoff.get("client"),
        "summary": handoff.get("summary"),
        "key_aspects": handoff.get("key_aspects"),
        "open_questions": handoff.get("open_questions"),
    }
    return _normalize(json.dumps(source, default=str))


def check_guidelines(department: str, content: str, handoff: dict[str, Any]) -> dict[str, Any]:
    """Returns {"pass", "rule_ids", "violations"} (lists are parallel, one message per rule)."""
    found: dict[str, list[str]] = {}

    def add(rule_id: str, message: str) -> None:
        found.setdefault(rule_id, []).append(message)

    # 1. PHI: only the TYPES are reported, never the values.
    _, phi = scan_and_redact(content)
    if phi.get("contains_phi"):
        kinds = ", ".join(sorted((phi.get("findings") or {}).keys())) or "unspecified"
        add("GUIDELINE_NO_PHI", f"The draft contains patient identifiers (types: {kinds}). Remove them.")

    # 2. Currency decided by the client country.
    currency = handoff.get("currency")
    if currency in CURRENCY_MARKERS:
        wrong = [
            marker
            for code, markers in CURRENCY_MARKERS.items()
            if code != currency
            for marker in markers
            if marker in content
        ]
        if wrong:
            add("GUIDELINE_CURRENCY_MATCHES_COUNTRY", f"Amounts must be in {currency} only; found {', '.join(wrong)}.")
        if department == "revenue" and not any(m in content for m in CURRENCY_MARKERS[currency]):
            add("GUIDELINE_CURRENCY_MATCHES_COUNTRY", f"The revenue section must state the currency ({currency}).")

    # 3. Legal instrument by client country (compliance section only).
    country = (handoff.get("client") or {}).get("client_country")
    if department == "compliance":
        lowered = content.lower()
        if country == "US" and not (re.search(r"\bbaa\b", lowered) or "business associate agreement" in lowered):
            add("GUIDELINE_LEGAL_INSTRUMENT_BY_COUNTRY", "US client: the section must include a Business Associate Agreement (BAA) clause.")
        if country == "UK" and not (
            ("dpa" in lowered or "data processing agreement" in lowered) and "uk gdpr" in lowered
        ):
            add("GUIDELINE_LEGAL_INSTRUMENT_BY_COUNTRY", "UK client: the section must include a Data Processing Agreement (DPA) clause referencing UK GDPR.")

    # 4. Figures must come from the findings (heuristic: the number must appear in the source).
    allowed = _allowed_text(handoff)
    invented: list[str] = []
    for token in MONEY_RE.findall(content) + PERCENT_RE.findall(content):
        number = re.sub(r"[^\d.]", "", token).rstrip(".")
        if number and number not in allowed and token.strip() not in invented:
            invented.append(token.strip())
    if invented:
        add(
            "GUIDELINE_NO_INVENTED_FIGURES",
            f"Figures not found in the RFP findings: {', '.join(invented)}. Remove them or write 'to be confirmed'.",
        )

    # 5. No unverified guarantees.
    if GUARANTEE_RE.search(content):
        add("GUIDELINE_NO_UNVERIFIED_GUARANTEES", "Remove guarantee / risk-free wording: the RFP findings do not support it.")

    rule_ids = list(found.keys())
    return {
        "pass": not rule_ids,
        "rule_ids": rule_ids,
        "violations": ["; ".join(found[rule_id]) for rule_id in rule_ids],
    }
