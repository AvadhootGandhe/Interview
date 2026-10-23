"""Phase 1: fine-tuned question generator (llama-server faked)."""
from __future__ import annotations

import httpx
import pytest
import respx

from app.agents.question_generator import (
    GeneratorUnavailable,
    InvalidGeneration,
    QuestionGenerator,
    build_prompt,
    clean_output,
)
from app.llm.local_client import LocalClient

URL = "http://llama.test"


# --- prompt -----------------------------------------------------------------

def test_build_prompt_matches_training_format_byte_for_byte(fixtures_dir):
    expected = (fixtures_dir / "generator_prompt_backend_architect_grpc.txt").read_bytes()
    assert build_prompt("Backend", "Architect/Principal", "gRPC").encode("utf-8") == expected


# --- cleanup ----------------------------------------------------------------

def test_clean_strips_whitespace():
    assert clean_output("  How does gRPC streaming work?\n") == "How does gRPC streaming work?"


def test_clean_drops_leftover_think_blocks():
    raw = "<think>\nhmm\n</think>\n\nWhat is backpressure in gRPC?"
    assert clean_output(raw) == "What is backpressure in gRPC?"


def test_clean_drops_unclosed_think_and_im_end():
    assert clean_output("What is HTTP/2 multiplexing?<|im_end|>") == "What is HTTP/2 multiplexing?"
    with pytest.raises(InvalidGeneration):
        clean_output("<think>still thinking and never closed")


@pytest.mark.parametrize("raw", ["", "   ", "<think></think>"])
def test_clean_rejects_empty(raw):
    with pytest.raises(InvalidGeneration):
        clean_output(raw)


def test_clean_rejects_over_long():
    with pytest.raises(InvalidGeneration):
        clean_output("x" * 401)
    assert clean_output("x" * 400) == "x" * 400


def test_clean_rejects_already_asked_case_and_space_insensitive():
    asked = ["How does gRPC handle deadlines?"]
    with pytest.raises(InvalidGeneration):
        clean_output("  how does  gRPC handle deadlines? ", already_asked=asked)


# --- client -----------------------------------------------------------------

@respx.mock
async def test_client_sends_trained_sampling_params():
    route = respx.post(f"{URL}/completion").mock(
        return_value=httpx.Response(200, json={"content": "What is a gRPC interceptor?"})
    )
    gen = QuestionGenerator(LocalClient(URL))
    q = await gen.generate("Backend", "Architect/Principal", "gRPC")

    assert q == "What is a gRPC interceptor?"
    body = route.calls.last.request.read()
    import json

    sent = json.loads(body)
    assert sent["prompt"] == build_prompt("Backend", "Architect/Principal", "gRPC")
    assert sent["stop"] == ["<|im_end|>"]
    assert sent["temperature"] == 0.8
    assert sent["top_p"] == 0.9
    assert sent["n_predict"] == 100


@respx.mock
async def test_server_down_raises_generator_unavailable():
    respx.post(f"{URL}/completion").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(GeneratorUnavailable):
        await QuestionGenerator(LocalClient(URL)).generate("Backend", "SDE-1", "gRPC")


@respx.mock
async def test_server_error_status_raises_generator_unavailable():
    respx.post(f"{URL}/completion").mock(return_value=httpx.Response(503))
    with pytest.raises(GeneratorUnavailable):
        await QuestionGenerator(LocalClient(URL)).generate("Backend", "SDE-1", "gRPC")


@respx.mock
async def test_generate_dedupes_against_already_asked():
    respx.post(f"{URL}/completion").mock(
        return_value=httpx.Response(200, json={"content": "What is gRPC?"})
    )
    with pytest.raises(InvalidGeneration):
        await QuestionGenerator(LocalClient(URL)).generate(
            "Backend", "SDE-1", "gRPC", already_asked=["what is grpc?"]
        )
