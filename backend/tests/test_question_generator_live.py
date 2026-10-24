import pytest

from app.agents.question_generator import QuestionGenerator
from app.llm.local_client import LocalClient

pytestmark = pytest.mark.local


async def test_three_real_generations_are_single_questions():
    gen = QuestionGenerator(LocalClient("http://localhost:8081"))
    asked: list[str] = []
    for _ in range(3):
        q = await gen.generate("Backend", "Architect/Principal", "gRPC", asked=asked)
        assert q.count("?") <= 1
        asked.append(q)
