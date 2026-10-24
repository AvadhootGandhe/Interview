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


# --- Phase 2: an ingested sample database ----------------------------------

@pytest.fixture(scope="session")
def ingested_db_file(tmp_path_factory) -> Path:
    """Ingest the sample once per run; each test gets its own copy."""
    from app.db.session import make_engine
    from scripts.ingest import ingest

    path = tmp_path_factory.mktemp("db") / "sample.db"
    engine = make_engine(f"sqlite:///{path}")
    ingest(SAMPLE_QUESTIONS, engine)
    engine.dispose()
    return path


@pytest.fixture
def db_url(ingested_db_file, tmp_path) -> str:
    import shutil

    path = tmp_path / "test.db"
    shutil.copy(ingested_db_file, path)
    return f"sqlite:///{path}"


@pytest.fixture
def db(db_url):
    from sqlalchemy.orm import Session

    from app.db.session import make_engine

    engine = make_engine(db_url)
    with Session(engine) as session:
        yield session
    engine.dispose()


# --- Phase 3: shared fixtures for agents, flow and orchestrator -----------------

@pytest.fixture
def pool() -> list:
    from helpers import make_pool

    return make_pool()


@pytest.fixture
def train_log(tmp_path, monkeypatch):
    """Redirect data/followup_train.jsonl so tests never touch the real file."""
    from app.config import settings

    path = tmp_path / "followup_train.jsonl"
    monkeypatch.setattr(settings, "followup_train_path", str(path))
    return path
