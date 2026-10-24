"""Evaluator: scores a question's whole thread and names exactly what was missing."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from app.agents.base import LLM, complete_validated

PROMPT = (Path(__file__).parents[1] / "prompts" / "evaluator.md").read_text()

RUBRICS = {
    "Fresher": (
        "Fresher: reward correct fundamentals and clear definitions with a simple example. "
        "Do not expect production experience, scale or trade-off analysis."
    ),
    "SDE-1": (
        "SDE-1: correct fundamentals applied to a small, concrete case; basic debugging and testing "
        "instincts. Light trade-offs are a bonus, not required."
    ),
    "SDE-1/2": (
        "SDE-1/2: correct and practical; explains why, names common failure modes and at least one "
        "trade-off; has clearly built things end to end."
    ),
    "SDE-2/3": (
        "SDE-2/3: reasons about scale, reliability and cost; compares alternatives and justifies a choice "
        "with real production experience. Vague or purely textbook answers lose depth points."
    ),
    "Architect/Principal": (
        "Architect/Principal: expects system-wide design and explicit trade-offs across teams, cost, risk and "
        "long-term evolution; clear decision criteria and the ability to challenge assumptions. "
        "Correct but shallow answers are partial at best."
    ),
}
DEFAULT_RUBRIC = "Any level: check fundamentals first, then reward depth, practical judgement and clear reasoning."


def rubric_for(level: str | None) -> str:
    return RUBRICS.get(level or "", DEFAULT_RUBRIC)


class Scores(BaseModel):
    correctness: int = Field(ge=0, le=100)
    depth: int = Field(ge=0, le=100)
    clarity: int = Field(ge=0, le=100)
    communication: int = Field(ge=0, le=100)


class Evaluation(BaseModel):
    satisfaction: int = Field(ge=0, le=100)
    scores: Scores
    covered_points: list[str] = []
    missing_points: list[str] = []
    follow_up_focus: str = ""
    mentioned_terms: list[str] = []
    red_flags: list[str] = []


@dataclass
class ThreadTurn:
    role: str  # "candidate" | "interviewer"
    text: str


@dataclass
class EvalContext:
    question: str
    thread: list[ThreadTurn] = field(default_factory=list)  # main answer + earlier follow-ups, in order
    level: str | None = None
    profile: str | None = None
    topic: str | None = None


class Evaluator:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def build_prompt(self, ctx: EvalContext) -> str:
        thread = "\n".join(
            f"{'Candidate' if t.role == 'candidate' else 'Interviewer (follow-up)'}: {t.text}" for t in ctx.thread
        )
        return (
            PROMPT.replace("__PROFILE__", ctx.profile or "software")
            .replace("__LEVEL__", ctx.level or "unspecified")
            .replace("__TOPIC__", ctx.topic or "general")
            .replace("__RUBRIC__", rubric_for(ctx.level))
            .replace("__QUESTION__", ctx.question)
            .replace("__THREAD__", thread or "(no answer yet)")
        )

    async def run(self, ctx: EvalContext) -> Evaluation:
        """Raises AgentOutputError if the output is still invalid after one retry."""
        return await complete_validated(self.llm, self.build_prompt(ctx), Evaluation, task="evaluator")
