import asyncio
import sys
import time

sys.path.insert(0, ".")
from app.agents.question_generator import QuestionGenerator  # noqa: E402
from app.llm.local_client import LocalClient  # noqa: E402


async def main() -> None:
    gen = QuestionGenerator(LocalClient("http://localhost:8081"))
    asked: list[str] = []
    for _ in range(3):
        start = time.perf_counter()
        q = await gen.generate("Backend", "Architect/Principal", "gRPC", asked=asked)
        asked.append(q)
        print(f"[{time.perf_counter() - start:.1f}s] {q}")


asyncio.run(main())
