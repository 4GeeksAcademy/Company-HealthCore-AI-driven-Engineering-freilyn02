"""Minimal LLM client (httpx), same env vars as data/pipelines/rag.py.

Agents call `llm.chat_json(...)` through the module (not `from llm import ...`)
so unit tests can monkeypatch it without any network access.
"""
import json
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

CHAT_PATH = os.getenv("LLM_CHAT_PATH", "/v1/chat/completions")
TIMEOUT_SECONDS = 120.0


class LLMError(Exception):
    """Raised when the LLM call fails or does not return valid JSON."""


def _settings() -> tuple[str, str, str]:
    base_url = os.getenv("LLM_BASE_URL", "https://llm.4geeks.ai").rstrip("/")
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("GENERATION_MODEL")
    if not api_key or not model:
        raise LLMError("Set LLM_API_KEY and GENERATION_MODEL in your .env file.")
    return base_url, api_key, model


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    raise LLMError("The model did not return valid JSON.")


def chat_json(system: str, user: str, *, retries: int = 1) -> dict[str, Any]:
    """Sends one chat request and returns the parsed JSON object."""
    base_url, api_key, model = _settings()
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    last_error: Exception | None = None
    for _ in range(retries + 1):
        try:
            response = httpx.post(
                f"{base_url}{CHAT_PATH}",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return _extract_json(content)
        except (httpx.HTTPError, KeyError, LLMError) as exc:
            last_error = exc
    raise LLMError(f"LLM call failed: {last_error}")
