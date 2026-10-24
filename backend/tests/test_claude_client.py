"""Phase 3: the Claude client (anthropic SDK, injectable, never needs a key in tests)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.evaluator import Evaluation
from app.config import settings
from app.llm.claude_client import ClaudeClient, LLMError, strict_schema


class FakeMessages:
    def __init__(self, text="hello", stop_reason="end_turn"):
        self.calls: list[dict] = []
        self.text, self.stop_reason = text, stop_reason

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=self.text)],
            stop_reason=self.stop_reason, stop_details=None,
        )


def client(**kw) -> tuple[ClaudeClient, FakeMessages]:
    messages = FakeMessages(**kw)
    return ClaudeClient(client=SimpleNamespace(messages=messages)), messages


async def test_returns_the_first_text_block_and_sends_the_prompt():
    c, m = client(text="Great answer.")
    assert await c.complete("Say hi", task="interviewer", system="Be brief.") == "Great answer."
    call = m.calls[0]
    assert call["messages"] == [{"role": "user", "content": "Say hi"}]
    assert call["system"] == "Be brief." and call["max_tokens"] == settings.claude_max_tokens
    assert "temperature" not in call and "top_p" not in call  # rejected by current models


async def test_models_come_from_config_with_haiku_for_the_company_summary():
    c, m = client()
    for task in ("evaluator", "planner", "interviewer", "reporter", "company_profile", None):
        await c.complete("x", **({"task": task} if task else {}))
    models = [call["model"] for call in m.calls]
    assert models == [settings.claude_model] * 4 + [settings.claude_model_cheap, settings.claude_model]
    assert settings.claude_model == "claude-sonnet-5-5" and settings.claude_model_cheap == "claude-haiku-5-5"


async def test_structured_output_uses_output_config_format():
    c, m = client(text="{}")
    await c.complete("score it", task="evaluator", schema=Evaluation.model_json_schema())
    cfg = m.calls[0]["output_config"]
    assert cfg["format"]["type"] == "json_schema"
    schema = cfg["format"]["schema"]
    assert schema["additionalProperties"] is False and "satisfaction" in schema["properties"]
    assert cfg["effort"] == settings.claude_effort


async def test_plain_calls_have_no_format():
    c, m = client()
    await c.complete("hi")
    assert "format" not in m.calls[0]["output_config"]


def test_strict_schema_drops_unsupported_keywords_and_closes_objects():
    s = strict_schema(Evaluation.model_json_schema())
    text = str(s)
    for bad in ("minimum", "maximum", "'default'", "'title'"):
        assert bad not in text
    assert s["additionalProperties"] is False
    assert all(d.get("additionalProperties") is False for d in s["$defs"].values())
    assert set(s["required"]) >= {"satisfaction", "scores"}


async def test_refusal_and_empty_replies_raise():
    c, _ = client(stop_reason="refusal")
    with pytest.raises(LLMError):
        await c.complete("x")
    c, _ = client(text="")
    with pytest.raises(LLMError):
        await c.complete("x")


async def test_missing_key_raises_a_clear_error(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        await ClaudeClient().complete("x")


async def test_factory_returns_the_deterministic_fake_when_fake_llm_is_on(monkeypatch):
    from app.llm.factory import make_llm
    from app.llm.fake_llm import DeterministicFakeLLM

    monkeypatch.setattr(settings, "fake_llm", True)
    assert isinstance(make_llm(), DeterministicFakeLLM)
    monkeypatch.setattr(settings, "fake_llm", False)
    assert isinstance(make_llm(), ClaudeClient)
