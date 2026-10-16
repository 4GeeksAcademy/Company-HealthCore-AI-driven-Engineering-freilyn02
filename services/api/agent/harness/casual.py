"""Brief answers for casual / general questions (the "allowed but redirected" path).

The model sees ONLY the user's casual question and CASUAL_SYSTEM_PROMPT: no retrieved data,
no tool results. The redirect to HealthCore is appended by the graph node, not by the model,
so it can never be forgotten or talked out of.
"""

from __future__ import annotations

import httpx

from data.pipelines.rag import _generation_settings

from ..prompts.system import CASUAL_SYSTEM_PROMPT, GREETING_REPLY
from .input_guards import is_greeting

MAX_CASUAL_CHARS = 400


def casual_reply(question: str) -> str:
    """Return a short reply, or "" if no model is available. Never raises."""
    if is_greeting(question):
        return GREETING_REPLY
    try:
        base_url, api_key, model = _generation_settings()
        response = httpx.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": 0.3,
                "max_tokens": 120,
                "messages": [
                    {"role": "system", "content": CASUAL_SYSTEM_PROMPT},
                    {"role": "user", "content": question.strip()},
                ],
            },
            timeout=30.0,
        )
        response.raise_for_status()
        text = (response.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception:  # noqa: BLE001 - any failure falls back to the plain redirect
        return ""
    return text[:MAX_CASUAL_CHARS]
