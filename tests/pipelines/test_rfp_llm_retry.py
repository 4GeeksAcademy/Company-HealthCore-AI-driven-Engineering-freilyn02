"""Unit tests for the LLM retry wrapper. No network and no real waiting."""
import pytest

from data.pipelines.rfp_intake import llm
from data.pipelines.rfp_response import config
from data.pipelines.rfp_response.llm_retry import chat_json_resilient


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(config, "LLM_RETRY_BASE_DELAY", 0)


def test_retries_after_a_transient_error_and_then_succeeds(monkeypatch):
    calls = []

    def flaky(system, user, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise llm.LLMError("429 too many requests")
        return {"ok": True}

    monkeypatch.setattr(llm, "chat_json", flaky)
    assert chat_json_resilient("s", "u") == {"ok": True}
    assert len(calls) == 3


def test_raises_after_the_last_attempt(monkeypatch):
    calls = []

    def always_fails(system, user, **kwargs):
        calls.append(1)
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "chat_json", always_fails)
    with pytest.raises(llm.LLMError):
        chat_json_resilient("s", "u")
    assert len(calls) == config.LLM_ATTEMPTS
