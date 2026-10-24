"""Evaluator: scores a candidate's answer (whole question thread) against a level-specific rubric."""
from __future__ import annotations

from dataclasses import dataclass

from app.agents.base import LLM, Msg, complete_validated, render, render_thread
from app.agents.schemas import Evaluation
from app.config import settings

RUBRICS = {
    "Fresher": (
        "Fresher: reward correct fundamentals and clear definitions with a simple example. Do not expect "
        "production experience, scale numbers or trade-off analysis; a correct, plain answer can score 80+."
    ),
    "SDE-1": (
        "SDE-1: reward correct fundamentals applied to a small feature, basic debugging and testing instincts. "
        "Trade-offs may be shallow; vague or memorised answers should score below 60."
    ),
    "SDE-1/2": (
        "SDE-1/2: reward ownership of a feature end to end, awareness of common failure modes and a stated "
        "trade-off or two. Answers with no failure handling should stay below 75."
    ),
    "SDE-2/3": (
        "SDE-2/3: reward service-level design, reasoning about scale, reliability and cost, and real production "
        "experience. Correct but shallow answers without trade-offs or failure modes should stay below 70."
    ),
    "Architect/Principal": (
        "Architect/Principal: reward system-wide trade-offs across teams, long-term strategy, risk, cost and "
        "operability, and clear justification of choices. Anything without explicit trade-offs, alternatives "
        "considered and failure/ops thinking should stay below 65."
    ),
}
DEFAULT_RUBRIC = "Any level: reward correctness first, then depth and clarity; do not reward length for its own sake."


class EvaluationError(Exception):
    """The evaluator model did not return a valid evaluation (after one retry)."""


@dataclass
class EvalInput:
    question: str
    thread: list[Msg]  # the main question, the answer and any earlier follow-ups; the last message is the answer to score
    profile: str | None = None
    level: str | None = None
    topic: str | None = None


class Evaluator:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def build_prompt(self, inp: EvalInput) -> str:
        answers = [m for m in inp.thread if m.role == "candidate"]
        return render(
            "evaluator",
            profile=inp.profile or "any",
            level=inp.level or "any level",
            topic=inp.topic or "any",
            rubric=RUBRICS.get(inp.level or "", DEFAULT_RUBRIC),
            question=inp.question,
            thread=render_thread(inp.thread),
            latest_answer=answers[-1].text if answers else "",
            threshold=settings.satisfaction_threshold,
        )

    async def run(self, inp: EvalInput) -> Evaluation:
        try:
            evaluation, _ = await complete_validated(
                self.llm, self.build_prompt(inp), Evaluation,
                task="evaluate", model=settings.evaluator_model, effort=settings.evaluator_effort, max_tokens=1500,
            )
        except ValueError as exc:
            raise EvaluationError(str(exc)) from exc
        return evaluation
