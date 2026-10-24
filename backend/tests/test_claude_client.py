from types import SimpleNamespace

import pytest

from app.llm.claude_client import ClaudeClient


class FakeMessages:
    def __init__(self, blocks=None, stop_reason="end_turn"):
        self.kwargs = None
        self.blocks = blocks if blocks is not None else [SimpleNamespace(type="text", text="  hello  ")]
        self.stop_reason = stop_reason

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(content=self.blocks, stop_reason=self.stop_reason)


def make(**kw):
    messages = FakeMessages(**kw)
    return ClaudeClient(sdk_client=SimpleNamespace(messages=messages)), messages


async def test_returns_text_blocks_only():
    client, _ = make(blocks=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text="Hi"),
                             SimpleNamespace(type="text", text=" there")])
    assert await client.complete("p") == "Hi there"


async def test_never_sends_sampling_params():
    client, messages = make()
    await client.complete("p", temperature=0.7, top_p=0.9, max_tokens=200)
    assert "temperature" not in messages.kwargs and "top_p" not in messages.kwargs
    assert messages.kwargs["messages"] == [{"role": "user", "content": "p"}]
    assert messages.kwargs["model"] == "claude-sonnet-5-5"


async def test_fast_path_turns_thinking_off_at_low_effort():
    client, messages = make()
    await client.complete("p", max_tokens=200)
    assert messages.kwargs["thinking"] == {"type": "between_tools"}
    assert messages.kwargs["output_config"] == {"effort": "low"}
    assert messages.kwargs["max_tokens"] == 200


async def test_think_path_uses_adaptive_thinking_and_headroom():
    client, messages = make()
    await client.complete("p", max_tokens=700, think=True, effort="medium")
    assert "thinking" not in messages.kwargs
    assert messages.kwargs["output_config"] == {"effort": "medium"}
    assert messages.kwargs["max_tokens"] >= 4000


async def test_model_override_for_cheap_calls():
    client, messages = make()
    await client.complete("p", model="claude-haiku-5-5")
    assert messages.kwargs["model"] == "claude-haiku-5-5"
    assert messages.kwargs["thinking"] == {"type": "disabled"}


async def test_refusal_raises():
    client, _ = make(blocks=[], stop_reason="refusal")
    with pytest.raises(RuntimeError, match="refus"):
        await client.complete("p")
