"""LLM call with exponential backoff, used by generators and the relevance evaluator.

It calls `llm.chat_json` through the module, so tests can still monkeypatch it.
"""
import time
from typing import Any

from ..rfp_intake import llm
from . import config


def chat_json_resilient(system: str, user: str) -> dict[str, Any]:
    last_error: llm.LLMError | None = None
    for attempt in range(config.LLM_ATTEMPTS):
        try:
            return llm.chat_json(system, user)
        except llm.LLMError as exc:
            last_error = exc
            if attempt < config.LLM_ATTEMPTS - 1:
                time.sleep(config.LLM_RETRY_BASE_DELAY * (2**attempt))
    assert last_error is not None
    raise last_error
