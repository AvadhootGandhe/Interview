import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def sample_questions() -> dict:
    return json.loads((ROOT / "data" / "sample_questions.json").read_text())


class FakeLLM:
    """Deterministic stand-in for the Claude client; returns queued replies in order."""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.calls: list[dict] = []

    async def complete(self, prompt: str, **kwargs) -> str:
        self.calls.append({"prompt": prompt, **kwargs})
        return self.replies.pop(0) if self.replies else ""


class FakeSTT:
    def __init__(self, text: str = ""):
        self.text = text

    async def transcribe(self, audio: bytes) -> str:
        return self.text


class FakeTTS:
    async def synthesize(self, text: str) -> str:
        return "/audio/fake.wav"


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def fake_stt():
    return FakeSTT()


@pytest.fixture
def fake_tts():
    return FakeTTS()
