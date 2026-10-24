"""Pick the LLM: the real Claude client, or the offline DemoLLM when FAKE_LLM=1."""
from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.llm.claude_client import ClaudeClient
from app.llm.fake import DemoLLM


@lru_cache
def get_llm():
    return DemoLLM() if settings.fake_llm else ClaudeClient()
