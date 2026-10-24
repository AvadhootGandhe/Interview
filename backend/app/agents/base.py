"""Shared agent plumbing: the LLM protocol, thread messages, and validated-JSON calls with one retry."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

PROMPTS_DIR = Path(__file__).parents[1] / "prompts"
M = TypeVar("M", bound=BaseModel)


class LLM(Protocol):
    async def complete(self, prompt: str, **kwargs) -> str: ...


class Agent(Protocol):
    async def run(self, ctx: Any) -> Any: ...


@dataclass
class Msg:
    role: str  # "interviewer" | "candidate"
    text: str


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


def render(template: str, **values: object) -> str:
    """Fill `$name` placeholders (prompts contain literal braces, so str.format is not used)."""
    return Template(load_prompt(template) if "\n" not in template else template).safe_substitute(
        {k: str(v) for k, v in values.items()}
    )


def render_thread(thread: list[Msg]) -> str:
    return "\n".join(f"{'Interviewer' if m.role == 'interviewer' else 'Candidate'}: {m.text}" for m in thread)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(raw: str) -> Any:
    """Parse model output as JSON, tolerating a code fence or text around one object."""
    text = _FENCE.sub("", raw.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def parse_model(raw: str, model: type[M]) -> M:
    return model.model_validate(extract_json(raw))


async def complete_validated(
    llm: LLM, prompt: str, schema_model: type[M], *, check=None, retries: int = 1, **kwargs
) -> tuple[M, int]:
    """Call the LLM until the output parses into `schema_model` (and `check(obj)` returns no errors).

    Returns (object, attempts). On a bad attempt the next prompt says what was wrong.
    Raises ValueError listing the last problems when every attempt fails.
    """
    problems: list[str] = []
    for attempt in range(1, retries + 2):
        text = prompt if not problems else (
            prompt + "\n\nYour previous reply was rejected:\n- " + "\n- ".join(problems)
            + "\nReply again with corrected JSON only."
        )
        raw = await llm.complete(text, schema=schema_model, **kwargs)
        try:
            obj = parse_model(raw, schema_model)
            problems = list(check(obj)) if check else []
        except (json.JSONDecodeError, ValidationError) as exc:
            problems = [f"invalid JSON for the schema: {str(exc)[:300]}"]
        if not problems:
            return obj, attempt
    raise ValueError("; ".join(problems))
