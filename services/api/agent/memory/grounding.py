"""Deterministic guards for memory proposals (MEM-092).

The model is NOT trusted to follow prompt rules, so two checks run in code:
  - ungrounded_words(): a proposed fact may only use words the user actually said.
  - scrub_reply(): sentences where the agent claims it saved/noted something, or promises
    a review or follow-up, are removed (only the system stores memory, and only after approval).
"""

from __future__ import annotations

import re

FALLBACK_REPLY = "Thank you for the correction."

_STOPWORDS = {
    "the", "and", "for", "are", "was", "with", "that", "this", "from", "have", "has", "not",
    "now", "its", "our", "all", "any", "than", "then", "into", "also", "per", "but", "who",
    "how", "what", "when", "where", "which", "will", "would", "can", "may",
}
_ALLOWED = {"healthcore"}  # the company name may appear even if the user did not type it

_PROMISE = re.compile(
    r"\b(?:i|we)(?:['’]ve|\s+have)\s+(?:noted|recorded|saved|stored|logged)\b"
    r"|\b(?:i|we)(?:['’]ll|\s+will)\s+(?:remember|note|record|save|store|use|escalate|forward|flag|pass)\b"
    r"|\bwill\s+be\s+(?:considered|noted|recorded|reviewed|escalated|forwarded|passed)\b"
    r"|\b(?:for|under)\s+review\b"
    r"|\b(?:be|been)\s+(?:reviewed|escalated|forwarded)\b"
    r"|\breviewed\s+by\b",
    re.IGNORECASE,
)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _forms(word: str) -> set[str]:
    """The word plus its likely singular forms (fees -> fee, applies -> apply)."""
    forms = {word}
    if word.endswith("ies") and len(word) > 4:
        forms.add(word[:-3] + "y")
    for suffix in ("es", "s"):
        if word.endswith(suffix) and len(word) > 3:
            forms.add(word[: -len(suffix)])
    return forms


def ungrounded_words(fact: str, message: str) -> list[str]:
    """Words of `fact` that the user never said in `message` (numbers included)."""
    said: set[str] = set()
    for word in _words(message):
        said |= _forms(word)
    missing: list[str] = []
    for word in _words(fact):
        if word in _STOPWORDS or word in _ALLOWED:
            continue
        if len(word) < 3 and not word.isdigit():
            continue
        if _forms(word) & said:
            continue
        missing.append(word)
    return missing


def scrub_reply(reply: str) -> str:
    """Remove sentences that claim a save or promise a review/follow-up. Keeps line structure."""
    lines_out: list[str] = []
    changed = False
    for line in reply.split("\n"):
        sentences = re.split(r"(?<=[.!?])\s+", line)
        kept = [s for s in sentences if not _PROMISE.search(s)]
        if len(kept) != len(sentences):
            changed = True
        lines_out.append(" ".join(kept))
    if not changed:
        return reply
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines_out)).strip()
    return text or FALLBACK_REPLY
