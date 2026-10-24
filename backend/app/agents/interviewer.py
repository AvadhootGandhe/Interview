"""Interviewer: greeting / ask / follow_up / transition / closing, as plain speakable text.

The ask and transition modes keep the seed question's intent: if the reworded question drifts, the
seed question is asked verbatim instead.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.agents.base import LLM, load_prompt, render
from app.agents.schemas import Segment
from app.config import settings
from app.services.retriever import STOP_WORDS

MODES = ("greeting", "ask", "follow_up", "transition", "closing")


@dataclass
class InterviewerInput:
    mode: str
    profile: str = "technical"
    level: str = ""
    company: str | None = None
    company_summary: str = ""
    segment: Segment | None = None
    seed_text: str = ""
    similar: list[str] = field(default_factory=list)
    bridge: str | None = None
    last_answer_summary: str = ""
    follow_up_focus: str = ""
    missing_points: list[str] = field(default_factory=list)


def _sections() -> dict[str, str]:
    out: dict[str, str] = {}
    name = None
    for line in load_prompt("interviewer").splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            out[name] = ""
        elif name:
            out[name] += line + "\n"
    return out


def build_prompt(inp: InterviewerInput) -> str:
    if inp.mode not in MODES:
        raise ValueError(f"unknown interviewer mode: {inp.mode}")
    sections = _sections()
    similar = inp.similar[: settings.style_examples]
    values = dict(
        profile=inp.profile, level=inp.level or "any level", max_words=settings.speech_max_words,
        company_line=f" at {inp.company}" if inp.company and inp.company != "General" else "",
        company_style=(f"How this company interviews: {inp.company_summary}" if inp.company_summary else ""),
        theme=inp.segment.theme if inp.segment else "",
        seed=inp.seed_text,
        bridge_section=(f"Bridge: {inp.bridge}. Acknowledge this naturally as you move on.\n" if inp.bridge else ""),
        last_answer_section=(f"What the candidate just said (summary): {inp.last_answer_summary}\n"
                             if inp.last_answer_summary else ""),
        similar="\n".join(f"- {q}" for q in similar) or "- (none)",
        missing=", ".join(inp.missing_points) or "(not specified)",
        focus=inp.follow_up_focus or "the most important missing point",
    )
    return render(sections["common"], **values) + "\n" + render(sections[inp.mode], **values)


_MARKDOWN = re.compile(r"(\*\*|__|`|^#+\s*|^\s*[-*•]\s+|^\s*\d+[.)]\s+)", re.MULTILINE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def clean_speech(raw: str, max_words: int | None = None) -> str:
    """Plain speakable text: no markdown or lists, one paragraph, at most `max_words` words."""
    max_words = max_words or settings.speech_max_words
    text = _MARKDOWN.sub("", raw.replace("*", ""))
    text = " ".join(text.split())
    words = text.split()
    if len(words) <= max_words:
        return text
    kept, count = [], 0
    for sentence in _SENTENCE_END.split(text):
        n = len(sentence.split())
        if count + n > max_words:
            break
        kept.append(sentence)
        count += n
    return " ".join(kept) if kept else " ".join(words[:max_words])


def _stem(word: str) -> str:
    return word[:5]


def _content(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3 and w not in STOP_WORDS}


def same_intent(seed: str, spoken: str, min_overlap: float = 0.5) -> bool:
    """Cheap rule check that the reworded question is still about the seed question's subject."""
    seed_terms = _content(seed)
    if not seed_terms:
        return True
    return len(seed_terms & _content(spoken)) / len(seed_terms) >= min_overlap


class Interviewer:
    def __init__(self, llm: LLM, intent_check: Callable[[str, str], bool] = same_intent) -> None:
        self.llm = llm
        self.intent_check = intent_check

    async def run(self, inp: InterviewerInput) -> str:
        raw = await self.llm.complete(
            build_prompt(inp), task="interview", model=settings.interviewer_model,
            effort=settings.interviewer_effort, max_tokens=300,
        )
        spoken = clean_speech(raw)
        if inp.mode in ("ask", "transition") and inp.seed_text and not self.intent_check(inp.seed_text, spoken):
            lead = "Let's move on." if inp.mode == "transition" else "Alright."
            spoken = clean_speech(f"{lead} {inp.seed_text}")
        return spoken
