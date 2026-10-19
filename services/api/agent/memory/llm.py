"""The ONLY place where the memory package calls the generation model.

Same gateway and settings as data/pipelines/rag.py, so there is no new configuration.
Tests replace `chat_text` with a fake, so no live model is ever needed.
"""

from __future__ import annotations

import json
import re

import httpx

from data.pipelines.rag import _generation_settings

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def chat_text(messages: list[dict], temperature: float = 0.0, timeout: float = 60.0) -> str:
    base_url, api_key, model = _generation_settings()
    response = httpx.post(
        f"{base_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "temperature": temperature, "messages": messages},
        timeout=timeout,
    )
    response.raise_for_status()
    return (response.json()["choices"][0]["message"]["content"] or "").strip()


def parse_json_object(text: str) -> dict:
    """Extract the first JSON object from a model answer (tolerates ```json fences)."""
    cleaned = _FENCE.sub("", (text or "").strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON answer is not an object")
    return data
