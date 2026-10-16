"""External-content isolation: text that comes from outside the user's own message.

Retrieved RAG chunks (and any other external text that reaches a model) are DATA, never
policy. Two defenses, both deterministic:

  1. Neutralize: instruction-like phrases, fake role markers ("[SYSTEM]", "<|im_start|>")
     and our own wrapper tag are replaced with "[filtered]" so they cannot masquerade as a
     privileged channel. Every neutralization is logged as a `security` event.
  2. Wrap: the cleaned text is enclosed in <untrusted_source> tags. The system prompt
     (rule 12) tells the model that tagged content is reference material only.

The wrapped text always travels in the `user` role message (see rag.generate_answer); it is
never merged into the `system` role.

Note on tools: ticket and inventory tool results are rendered into the answer by
`nodes.render_tool_results` WITHOUT any model call, so tool text cannot steer a model.
Their final text still goes through the output guards.
"""

from __future__ import annotations

import re

from .input_guards import INJECTION_PATTERNS
from .observability import record_event

TAG = "untrusted_source"
FILTERED = "[filtered]"

_WRAPPER_TAG_RE = re.compile(rf"<\s*/?\s*{TAG}[^>]*>", re.IGNORECASE)
_ROLE_MARKER_RE = re.compile(
    r"\[\s*(?:system|assistant|developer|admin)\s*\]|<\|[^|>]*\|>|<\s*/?\s*system\s*>",
    re.IGNORECASE,
)


def sanitize_untrusted(text: str) -> tuple[str, int]:
    """Return (cleaned_text, number_of_neutralized_spans)."""
    count = 0

    def _sub(pattern: re.Pattern, value: str) -> str:
        nonlocal count
        value, n = pattern.subn(FILTERED, value)
        count += n
        return value

    text = _sub(_WRAPPER_TAG_RE, text or "")
    text = _sub(_ROLE_MARKER_RE, text)
    for name, pattern in INJECTION_PATTERNS.items():
        if name == "fake_system_marker":
            continue  # already handled by _ROLE_MARKER_RE
        text = _sub(pattern, text)
    return text, count


def wrap_untrusted(text: str, source: str = "knowledge_base") -> tuple[str, int]:
    clean, flagged = sanitize_untrusted(text)
    return f'<{TAG} name="{source}">\n{clean}\n</{TAG}>', flagged


def wrap_chunks(chunks: list[dict], source: str = "knowledge_base") -> list[dict]:
    """Wrap every retrieved chunk. Returns NEW dicts; the originals are untouched."""
    wrapped: list[dict] = []
    for chunk in chunks:
        text, flagged = wrap_untrusted(chunk.get("text", ""), source)
        if flagged:
            record_event(
                "external_content_injection",
                "security",
                "sanitize",
                f"{flagged} instruction-like span(s) neutralized in {source}",
            )
        wrapped.append({**chunk, "text": text})
    return wrapped
