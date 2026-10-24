"""Which LLM the app uses: the real Claude client, or the offline deterministic fake (FAKE_LLM=1)."""
from __future__ import annotations

from app.config import settings
from app.llm.claude_client import ClaudeClient
from app.llm.fake_llm import DeterministicFakeLLM


def make_llm():
    return DeterministicFakeLLM() if settings.fake_llm else ClaudeClient()
