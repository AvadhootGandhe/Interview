from pathlib import Path

import httpx
import pytest

from app.agents.question_generator import (
    GeneratorUnavailable,
    QuestionGenerator,
    build_prompt,
    clean_output,
)
from app.llm.local_client import LocalClient

FIXTURE = Path(__file__).parent / "fixtures" / "generator_prompt.txt"


def test_build_prompt_matches_training_format_byte_for_byte():
    assert build_prompt("Backend", "Architect/Principal", "gRPC") == FIXTURE.read_text()


def test_clean_output_strips_whitespace_and_think_blocks():
    assert clean_output("  <think>hmm</think>\nWhat is gRPC?  ") == "What is gRPC?"


@pytest.mark.parametrize("raw", ["", "   ", "x" * 401])
def test_clean_output_rejects_empty_or_too_long(raw):
    assert clean_output(raw) is None


def _client(handler):
    return LocalClient("http://llama", transport=httpx.MockTransport(handler))


async def test_client_sends_expected_sampling_params():
    seen = {}

    def handler(request):
        seen.update(__import__("json").loads(request.content))
        return httpx.Response(200, json={"content": "What is gRPC?"})

    gen = QuestionGenerator(_client(handler))
    q = await gen.generate("Backend", "Architect/Principal", "gRPC")
    assert q == "What is gRPC?"
    assert seen["prompt"] == FIXTURE.read_text()
    assert seen["stop"] == ["<|im_end|>"]
    assert seen["temperature"] == 0.8
    assert seen["top_p"] == 0.9
    assert seen["n_predict"] == 100


async def test_dedupes_against_already_asked():
    replies = iter(["What is gRPC?", "How does gRPC streaming work?"])

    def handler(request):
        return httpx.Response(200, json={"content": next(replies)})

    gen = QuestionGenerator(_client(handler))
    q = await gen.generate("Backend", "SDE-2/3", "gRPC", asked=["what is grpc?"])
    assert q == "How does gRPC streaming work?"


async def test_server_down_raises_generator_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused")

    gen = QuestionGenerator(_client(handler))
    with pytest.raises(GeneratorUnavailable):
        await gen.generate("Backend", "SDE-1", "gRPC")
