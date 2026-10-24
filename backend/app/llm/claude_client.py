import anthropic

from app.config import settings

THINK_MIN_TOKENS = 4000  # thinking tokens count against max_tokens


class ClaudeClient:
    """Async text-completion wrapper over the Anthropic SDK, shaped like the fake LLM used in tests.

    Sampling params (temperature/top_p) are accepted and ignored: current models reject them.
    Default path is fast: thinking off, low effort. Pass think=True for planner/evaluator-style calls.
    """

    def __init__(self, model: str | None = None, sdk_client=None):
        self.model = model or settings.evaluator_model
        self._sdk = sdk_client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)

    async def complete(self, prompt: str, *, model: str | None = None, max_tokens: int = 1024,
                       think: bool = False, effort: str | None = None, **_ignored) -> str:
        model = model or self.model
        params: dict = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        if think:
            params["max_tokens"] = max(max_tokens, THINK_MIN_TOKENS)
            params["output_config"] = {"effort": effort or "medium"}
        else:
            params["max_tokens"] = max_tokens
            params["output_config"] = {"effort": effort or "low"}
            params["thinking"] = ({"type": "disabled"} if "haiku" in model else {"type": "between_tools"})
        response = await self._sdk.messages.create(**params)
        if response.stop_reason == "refusal":
            raise RuntimeError("model refused the request")
        return "".join(b.text for b in response.content if b.type == "text").strip()
