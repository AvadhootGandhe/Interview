"""Async Anthropic SDK wrapper. Agents pass `task=` (a label for routing/logging) and `model=`."""
from __future__ import annotations

import anthropic
from pydantic import BaseModel

from app.config import settings


class ClaudeError(Exception):
    """The Claude API could not be used (missing key, network or API error)."""


class LLMRefusal(ClaudeError):
    """The model declined to answer (stop_reason == "refusal")."""


class ClaudeClient:
    def __init__(self, api_key: str | None = None, sdk: anthropic.AsyncAnthropic | None = None) -> None:
        if sdk is None:
            api_key = settings.anthropic_api_key if api_key is None else api_key
            if not api_key:
                raise ClaudeError("ANTHROPIC_API_KEY is not set (or set FAKE_LLM=1 to use the offline demo model)")
            sdk = anthropic.AsyncAnthropic(api_key=api_key, timeout=settings.claude_timeout_s)
        self.sdk = sdk

    async def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system: str | None = None,
        max_tokens: int = 2048,
        schema: type[BaseModel] | None = None,
        effort: str | None = None,
        task: str | None = None,  # routing label for fakes and logs; not sent to the API
    ) -> str:
        # No temperature/top_p/top_k: removed on current models. Thinking is left at the model default.
        params: dict = {
            "model": model or settings.evaluator_model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            params["system"] = system
        output_config: dict = {}
        if effort:
            output_config["effort"] = effort
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": anthropic.transform_schema(schema)}
        if output_config:
            params["output_config"] = output_config
        try:
            response = await self.sdk.messages.create(**params)
        except anthropic.APIError as exc:
            raise ClaudeError(f"{type(exc).__name__}: {exc}") from exc
        if response.stop_reason == "refusal":
            raise LLMRefusal("the model declined this request")
        return "".join(b.text for b in response.content if b.type == "text")
