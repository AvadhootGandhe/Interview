"""Claude via the official `anthropic` SDK.

Satisfies the `complete(prompt, **kwargs) -> str` protocol the agents use. Models come from config:
`claude_model` (Sonnet) for the evaluator, planner, interviewer and reporter, `claude_model_cheap`
(Haiku) for the company-profile summary. Structured output uses `output_config.format`.

Sampling parameters (temperature, top_p) are never sent: current Claude models reject non-default values.
"""
from __future__ import annotations

import copy
from typing import Any

from app.config import settings

CHEAP_TASKS = {"company_profile", "candidate"}  # "candidate" = eval-only simulated answers
_UNSUPPORTED = {
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength",
    "minItems", "maxItems", "default", "title", "examples",
}


class LLMError(Exception):
    """The model call failed, was refused, or came back empty."""


def strict_schema(schema: dict) -> dict:
    """A pydantic JSON schema reduced to what structured outputs accept.

    Drops unsupported keywords (pydantic still validates ranges afterwards), closes every object
    with `additionalProperties: false` and marks every property required.
    """

    def walk(node: Any, names: bool = False) -> Any:  # names: keys are property/def names, keep all
        if isinstance(node, list):
            return [walk(n) for n in node]
        if not isinstance(node, dict):
            return node
        if names:
            return {k: walk(v) for k, v in node.items()}
        out = {
            k: walk(v, names=k in ("properties", "$defs"))
            for k, v in node.items() if k not in _UNSUPPORTED
        }
        if out.get("type") == "object" or "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out.get("properties", {}))
        return out

    return walk(copy.deepcopy(schema))


class ClaudeClient:
    def __init__(self, client: Any = None, api_key: str | None = None) -> None:
        self._client = client
        self._api_key = api_key

    def _sdk(self) -> Any:
        if self._client is None:
            key = self._api_key or settings.anthropic_api_key
            if not key:
                raise LLMError("ANTHROPIC_API_KEY is not set (or use FAKE_LLM=1 for the offline fake)")
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=key, timeout=settings.claude_timeout_s)
        return self._client

    @staticmethod
    def model_for(task: str | None) -> str:
        return settings.claude_model_cheap if task in CHEAP_TASKS else settings.claude_model

    async def complete(
        self,
        prompt: str,
        *,
        task: str | None = None,
        schema: dict | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
        **_: Any,
    ) -> str:
        sdk = self._sdk()
        output_config: dict[str, Any] = {"effort": settings.claude_effort}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": strict_schema(schema)}
        kwargs: dict[str, Any] = {
            "model": self.model_for(task),
            "max_tokens": max_tokens or settings.claude_max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": output_config,
        }
        if system:
            kwargs["system"] = system
        try:
            response = await sdk.messages.create(**kwargs)
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(f"Claude request failed: {exc}") from exc
        if response.stop_reason == "refusal":
            raise LLMError("Claude declined this request")
        text = next((b.text for b in response.content if b.type == "text"), "")
        if not text.strip():
            raise LLMError(f"Claude returned no text (stop_reason={response.stop_reason})")
        return text
