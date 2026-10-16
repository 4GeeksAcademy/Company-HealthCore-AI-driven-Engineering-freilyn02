"""Document metadata + readability metrics, computed on the Markdown body.

Purpose: anticipate processing cost (a dense, long RFP needs more LLM time),
not to grade the writing.
"""
import re
from typing import Any

import nltk


def _ensure_nltk() -> None:
    """py-readability-metrics needs NLTK's sentence tokenizer data."""
    for resource in ("punkt", "punkt_tab"):
        try:
            nltk.data.find(f"tokenizers/{resource}")
        except LookupError:
            nltk.download(resource, quiet=True)


def basic_metadata(markdown: str) -> dict[str, Any]:
    words = re.findall(r"\w+", markdown)
    first_heading = re.search(r"^#{1,3}\s+(.+)$", markdown, flags=re.MULTILINE)
    return {
        "title_guess": first_heading.group(1).strip() if first_heading else None,
        "word_count": len(words),
        "char_count": len(markdown),
        "estimated_tokens": len(markdown) // 4,  # rough rule of thumb
        "heading_count": len(re.findall(r"^#{1,6}\s", markdown, flags=re.MULTILINE)),
    }


def readability_scores(markdown: str) -> dict[str, Any]:
    """Each metric is optional: the library refuses very short texts."""
    from readability import Readability  # imported lazily (needs NLTK data)

    _ensure_nltk()
    scores: dict[str, Any] = {}
    try:
        reader = Readability(markdown)  # raises if fewer than 100 words
    except Exception as exc:
        return {"available": False, "reason": str(exc)}

    for name, method in (
        ("flesch_kincaid_grade", reader.flesch_kincaid),
        ("flesch_reading_ease", reader.flesch),
        ("gunning_fog", reader.gunning_fog),
    ):
        try:
            result = method()
            scores[name] = round(float(result.score), 2)
        except Exception:
            scores[name] = None

    scores["available"] = True
    grade = scores.get("gunning_fog") or scores.get("flesch_kincaid_grade")
    if grade is None:
        scores["complexity"] = "unknown"
    elif grade >= 16:
        scores["complexity"] = "high"
    elif grade >= 12:
        scores["complexity"] = "medium"
    else:
        scores["complexity"] = "low"
    return scores
