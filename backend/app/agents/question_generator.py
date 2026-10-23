"""Fine-tuned Qwen3-4B question generator (served by llama-server).

The LoRA learned exactly one task: Profile + Level + Topic -> one question.
DO NOT change SYSTEM or build_prompt() without retraining; they must match the
training notebook byte for byte. Company flavour comes from the context pack.
"""
from __future__ import annotations

import re

from app.config import settings
from app.llm.local_client import LocalClient, LocalLLMError

SYSTEM = (
    "You are a technical interviewer. Ask exactly one interview question that "
    "matches the requested profile, experience level and topic."
)
STOP = ["<|im_end|>"]

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class GeneratorUnavailable(Exception):
    """llama-server is down; callers fall back to dataset questions."""


class InvalidGeneration(Exception):
    """The model output can't be used as a question."""


def build_prompt(profile: str, level: str, topic: str) -> str:
    user = f"Profile: {profile}\nLevel: {level}\nTopic: {topic}\n\nAsk one interview question."
    return (
        f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        f"<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def clean_output(raw: str, already_asked: list[str] | None = None) -> str:
    text = _THINK_BLOCK.sub("", raw).replace("<|im_end|>", "").strip()
    if not text or "<think>" in text:
        raise InvalidGeneration("empty or unfinished output")
    if len(text) > settings.generator_max_chars:
        raise InvalidGeneration(f"too long ({len(text)} chars)")
    if _norm(text) in {_norm(q) for q in already_asked or []}:
        raise InvalidGeneration("already asked")
    return text


class QuestionGenerator:
    def __init__(self, client: LocalClient) -> None:
        self.client = client

    async def generate(
        self, profile: str, level: str, topic: str, already_asked: list[str] | None = None
    ) -> str:
        try:
            raw = await self.client.complete(
                build_prompt(profile, level, topic),
                stop=STOP,
                temperature=settings.generator_temperature,
                top_p=settings.generator_top_p,
                n_predict=settings.generator_n_predict,
            )
        except LocalLLMError as exc:
            raise GeneratorUnavailable(str(exc)) from exc
        return clean_output(raw, already_asked)
