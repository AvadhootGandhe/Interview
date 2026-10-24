import re

import httpx

from app.llm.local_client import LocalClient

# Must match the LoRA's training format exactly; do not edit without retraining.
PROMPT_TEMPLATE = (
    "<|im_start|>system\nYou are a technical interviewer. Ask exactly one interview question "
    "that matches the requested profile, experience level and topic.<|im_end|>\n"
    "<|im_start|>user\nProfile: {profile}\nLevel: {level}\nTopic: {topic}\n\n"
    "Ask one interview question.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
)
MAX_QUESTION_CHARS = 400
MAX_ATTEMPTS = 3


class GeneratorUnavailable(Exception):
    pass


def build_prompt(profile: str, level: str, topic: str) -> str:
    return PROMPT_TEMPLATE.format(profile=profile, level=level, topic=topic)


def clean_output(raw: str) -> str | None:
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if not text or len(text) > MAX_QUESTION_CHARS:
        return None
    return text


class QuestionGenerator:
    def __init__(self, client: LocalClient):
        self._client = client

    async def generate(self, profile: str, level: str, topic: str, asked: list[str] | None = None) -> str:
        seen = {q.strip().lower() for q in (asked or [])}
        prompt = build_prompt(profile, level, topic)
        for _ in range(MAX_ATTEMPTS):
            try:
                raw = await self._client.completion(
                    prompt, stop=["<|im_end|>"], temperature=0.8, top_p=0.9, n_predict=100
                )
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                raise GeneratorUnavailable(str(exc)) from exc
            question = clean_output(raw)
            if question and question.lower() not in seen:
                return question
        raise GeneratorUnavailable("no usable question after retries")
