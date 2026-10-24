"""Interviewer: speaks the greeting, questions, follow-ups, transitions and closing in the company's style."""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.base import LLM
from app.agents.evaluator import ThreadTurn
from app.config import settings

MODES = ("greeting", "ask", "follow_up", "transition", "closing")
EXAMPLES_SHOWN = 3


def _sections() -> dict[str, str]:
    text = (Path(__file__).parents[1] / "prompts" / "interviewer.md").read_text()
    parts = re.split(r"^## (\w+)\n", text, flags=re.M)
    return {name: body.strip() for name, body in zip(parts[1::2], parts[2::2])}


SECTIONS = _sections()

Judge = Callable[[str, str], Awaitable[bool]]  # (seed question, spoken text) -> same intent?


@dataclass
class InterviewerContext:
    mode: str
    profile: str | None = None
    level: str | None = None
    company: str | None = None
    topic: str | None = None
    company_summary: str = ""
    theme: str = ""
    seed_question: str = ""
    examples: list[str] = field(default_factory=list)  # similar retrieved questions, as style examples
    bridge: str | None = None
    last_answer_summary: str = ""
    follow_up_focus: str = ""
    missing_points: list[str] = field(default_factory=list)
    thread: list[ThreadTurn] = field(default_factory=list)


def clean_speech(text: str, max_words: int | None = None) -> str:
    """Plain speakable text: no markdown, lists, labels or quotes, at most ~max_words words."""
    max_words = max_words or settings.max_spoken_words
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)", "", text, flags=re.M)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"^\s*(?:interviewer|assistant)\s*:\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"\s+", " ", text).strip().strip('"“”').strip()
    words = text.split()
    if len(words) <= max_words:
        return text
    out = ""
    for sentence in re.findall(r"[^.!?]+[.!?]+|[^.!?]+$", text):
        if len((out + sentence).split()) > max_words:
            break
        out += sentence
    return out.strip() or " ".join(words[:max_words])


class Interviewer:
    def __init__(self, llm: LLM, judge: Judge | None = None) -> None:
        self.llm = llm
        self.judge = judge  # optional intent check for rephrased questions (one extra call, off by default)

    def build_prompt(self, c: InterviewerContext) -> str:
        if c.mode not in MODES:
            raise ValueError(f"unknown interviewer mode {c.mode!r}")
        role = " ".join(x for x in (c.level, c.profile) if x) or "software"
        parts = [SECTIONS["common"], SECTIONS[c.mode]]
        parts.append(f"Interview: {role} role" + (f" at {c.company}" if c.company else "")
                     + (f", topic {c.topic}" if c.topic else "") + ".")
        if c.company_summary:
            parts.append(f"How this company interviews: {c.company_summary}")

        if c.mode == "ask":
            parts.append(f"Segment theme: {c.theme}")
            parts.append(f"Seed question (keep its intent): {c.seed_question}")
            if c.examples:
                shown = "\n".join(f"- {e}" for e in c.examples[:EXAMPLES_SHOWN])
                parts.append(f"Similar questions this company asks (for style only, do not ask these):\n{shown}")
            if c.bridge:
                parts.append(f"Bridge note: {c.bridge}")
            if c.last_answer_summary:
                parts.append(f"Summary of the previous answer: {c.last_answer_summary}")
        elif c.mode == "follow_up":
            parts.append(f"Original question: {c.seed_question}")
            if c.thread:
                convo = "\n".join(
                    f"{'Candidate' if t.role == 'candidate' else 'Interviewer'}: {t.text}" for t in c.thread
                )
                parts.append(f"Conversation so far:\n{convo}")
            parts.append(f"Follow-up focus: {c.follow_up_focus}")
            if c.missing_points:
                parts.append("What the answer missed: " + "; ".join(c.missing_points))
        elif c.mode in ("transition", "closing") and c.last_answer_summary:
            label = "Last answer" if c.mode == "transition" else "How the interview went"
            parts.append(f"{label}: {c.last_answer_summary}")
        return "\n\n".join(parts)

    async def run(self, c: InterviewerContext) -> str:
        raw = await self.llm.complete(
            self.build_prompt(c), task="interviewer", max_tokens=300
        )
        text = clean_speech(raw)
        if c.mode == "ask" and self.judge and c.seed_question:
            if not await self.judge(c.seed_question, text):
                text = clean_speech(f"Alright, next question. {c.seed_question}")
        return text
