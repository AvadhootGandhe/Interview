"""Shared fixtures: fake LLM, STT and TTS so cloud runs need no model, mic or key."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_QUESTIONS = REPO_ROOT / "data" / "sample_questions.json"
FIXTURES = Path(__file__).parent / "fixtures"


class FakeLLM:
    """Returns queued replies in order and records every prompt it got."""

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[dict] = []

    async def complete(self, prompt: str, **kwargs) -> str:
        self.calls.append({"prompt": prompt, **kwargs})
        if not self.replies:
            raise AssertionError("FakeLLM ran out of replies")
        return self.replies.pop(0)


class FakeSTT:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.calls: list[bytes] = []

    async def transcribe(self, audio: bytes) -> str:
        self.calls.append(audio)
        return self.text


class FakeTTS:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def synthesize(self, text: str) -> str:
        self.calls.append(text)
        return f"/audio/fake-{len(self.calls)}.wav"


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def fake_stt() -> FakeSTT:
    return FakeSTT()


@pytest.fixture
def fake_tts() -> FakeTTS:
    return FakeTTS()


@pytest.fixture
def sample_questions_path() -> Path:
    return SAMPLE_QUESTIONS


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
