"""Shared agent plumbing: the `Agent` protocol and validated structured-output calls."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

Ctx = TypeVar("Ctx", contravariant=True)
Result = TypeVar("Result", covariant=True)
M = TypeVar("M", bound=BaseModel)


class Agent(Protocol, Generic[Ctx, Result]):
    """Every agent: one context in, one result out."""

    async def run(self, ctx: Ctx) -> Result: ...


class LLM(Protocol):
    async def complete(self, prompt: str, **kwargs: Any) -> str: ...


class AgentOutputError(Exception):
    """The model's output was still invalid after the retry."""


def extract_json(raw: str) -> Any:
    """Parse JSON, tolerating a ```json fence or text around one object."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def parse_model(raw: str, model: type[M]) -> M:
    try:
        return model.model_validate(extract_json(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"invalid output: {str(exc)[:400]}") from exc


async def complete_validated(
    llm: LLM,
    prompt: str,
    model: type[M],
    *,
    task: str,
    check: Callable[[M], list[str]] | None = None,
    retries: int = 1,
    **kwargs: Any,
) -> M:
    """Ask for JSON matching `model`; validate it (and `check` rules); retry with the errors.

    Raises AgentOutputError after `retries` extra attempts. LLM transport errors propagate.
    """
    errors: list[str] = []
    for attempt in range(retries + 1):
        full = prompt
        if errors:
            full += (
                "\n\nYour previous answer was invalid. Fix these problems and return only the JSON:\n- "
                + "\n- ".join(errors)
            )
        raw = await llm.complete(full, task=task, schema=model.model_json_schema(), **kwargs)
        try:
            result = parse_model(raw, model)
        except ValueError as exc:
            errors = [str(exc)]
            continue
        errors = check(result) if check else []
        if not errors:
            return result
    raise AgentOutputError(f"{task}: " + "; ".join(errors))
