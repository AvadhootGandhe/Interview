"""Mac only: print 3 questions from the fine-tuned generator and how long each took.

Start the server first:
  llama-server -m models/interviewer-q4_k_m.gguf --port 8081 -c 2048 -ngl 99
Then, from backend/:
  python -m scripts.check_model [--profile Backend --level Architect/Principal --topic gRPC]
"""
from __future__ import annotations

import argparse
import asyncio
import time

from app.agents.question_generator import QuestionGenerator
from app.config import settings
from app.llm.local_client import LocalClient


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", default="Backend")
    p.add_argument("--level", default="Architect/Principal")
    p.add_argument("--topic", default="gRPC")
    args = p.parse_args()

    gen = QuestionGenerator(LocalClient(settings.llama_server_url, settings.generator_timeout_s))
    asked: list[str] = []
    for _ in range(3):
        t0 = time.perf_counter()
        q = await gen.generate(args.profile, args.level, args.topic, already_asked=asked)
        asked.append(q)
        print(f"- ({time.perf_counter() - t0:.2f}s) {q}")


if __name__ == "__main__":
    asyncio.run(main())
