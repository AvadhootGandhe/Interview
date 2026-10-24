"""Phase 3: the thin Anthropic SDK wrapper (no network: a fake SDK client is injected)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.schemas import Evaluation
from app.config import settings
from app.llm.claude_client import ClaudeClient, ClaudeError, LLMRefusal


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def reply(text="hello", stop_reason="end_turn", blocks=None):
    blocks = blocks or [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def client_with(messages) -> ClaudeClient:
    return ClaudeClient(sdk=SimpleNamespace(messages=messages))


async def test_complete_sends_model_system_and_max_tokens_and_returns_text():
    m = FakeMessages(reply("Hi there"))
    out = await client_with(m).complete("Say hi", model="claude-haiku-5-5", system="Be brief", max_tokens=200)
    call = m.calls[0]
    assert out == "Hi there"
    assert call["model"] == "claude-haiku-5-5" and call["system"] == "Be brief" and call["max_tokens"] == 200
    assert call["messages"] == [{"role": "user", "content": "Say hi"}]
    assert not {"temperature", "top_p", "top_k"} & set(call)  # removed on current models


async def test_default_model_is_the_evaluator_model_and_ignores_task_label():
    m = FakeMessages(reply())
    await client_with(m).complete("x", task="evaluate")
    assert m.calls[0]["model"] == settings.evaluator_model
    assert "task" not in m.calls[0]


async def test_text_blocks_only_thinking_is_skipped():
    blocks = [SimpleNamespace(type="thinking", thinking="hmm"), SimpleNamespace(type="text", text="answer")]
    assert await client_with(FakeMessages(reply(blocks=blocks))).complete("x") == "answer"


async def test_schema_becomes_a_json_schema_output_format():
    m = FakeMessages(reply("{}"))
    await client_with(m).complete("x", schema=Evaluation, effort="low")
    cfg = m.calls[0]["output_config"]
    assert cfg["effort"] == "low"
    assert cfg["format"]["type"] == "json_schema"
    assert cfg["format"]["schema"]["properties"]["satisfaction"]


async def test_refusal_raises():
    with pytest.raises(LLMRefusal):
        await client_with(FakeMessages(reply("", stop_reason="refusal"))).complete("x")


async def test_api_errors_are_wrapped():
    import anthropic

    err = anthropic.APIConnectionError(request=SimpleNamespace())
    with pytest.raises(ClaudeError):
        await client_with(FakeMessages(error=err)).complete("x")


def test_missing_key_is_a_clear_error():
    with pytest.raises(ClaudeError, match="ANTHROPIC_API_KEY"):
        ClaudeClient(api_key="")


def test_factory_prefers_the_demo_llm_when_fake_llm_is_set(monkeypatch):
    from app.llm import factory
    from app.llm.fake import DemoLLM

    monkeypatch.setattr(settings, "fake_llm", True)
    factory.get_llm.cache_clear()
    assert isinstance(factory.get_llm(), DemoLLM)
    factory.get_llm.cache_clear()
