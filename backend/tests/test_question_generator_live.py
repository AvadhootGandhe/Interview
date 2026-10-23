"""Phase 1, Mac only: real generations from llama-server running the fine-tuned GGUF."""
from __future__ import annotations

import pytest

from app.agents.question_generator import QuestionGenerator
from app.config import settings
from app.llm.local_client import LocalClient

pytestmark = pytest.mark.local


async def test_three_live_generations_are_single_questions():
    gen = QuestionGenerator(LocalClient(settings.llama_server_url))
    asked: list[str] = []
    for _ in range(3):
        q = await gen.generate("Backend", "Architect/Principal", "gRPC", already_asked=asked)
        asked.append(q)
        assert q.count("?") <= 2, q
        assert "\n\n" not in q, q
    assert len(set(asked)) == 3
