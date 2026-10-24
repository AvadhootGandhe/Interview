"""Reporter: honest end-of-interview feedback. Scores are computed in code; the model writes the words."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from app.agents.base import LLM, complete_validated

log = logging.getLogger(__name__)
PROMPT = (Path(__file__).parents[1] / "prompts" / "feedback.md").read_text()


@dataclass
class QuestionResult:
    question_id: str
    topic: str
    question: str
    final_score: float
    followups: int = 0
    covered_points: list[str] = field(default_factory=list)
    missing_points: list[str] = field(default_factory=list)


@dataclass
class ReportContext:
    profile: str | None
    level: str | None
    company: str | None
    topic: str | None
    questions: list[QuestionResult]


class Narrative(BaseModel):
    verdict: str
    strengths: list[str]
    gaps: list[str]
    next_steps: list[str] = []


class QuestionReport(BaseModel):
    question_id: str
    topic: str
    question: str
    final_score: int
    followups: int = 0
    covered_points: list[str] = []
    missing_points: list[str] = []


class Report(BaseModel):
    overall_score: int
    verdict: str
    questions: list[QuestionReport]
    strengths: list[str]
    gaps: list[str]
    next_steps: list[str] = []


def _score(x: float) -> int:
    return max(0, min(100, round(x)))


def _dedupe(items: list[str], limit: int) -> list[str]:
    seen, out = set(), []
    for i in items:
        if i.lower() not in seen:
            seen.add(i.lower())
            out.append(i)
    return out[:limit]


def fallback_narrative(overall: int, qs: list[QuestionReport]) -> Narrative:
    """Deterministic feedback built from the evaluator's points, used if the model fails twice."""
    best = sorted(qs, key=lambda q: -q.final_score)
    worst = sorted(qs, key=lambda q: q.final_score)
    strengths = _dedupe([p for q in best for p in q.covered_points], 4) or ["You completed the interview."]
    gaps = _dedupe([p for q in worst for p in q.missing_points], 4) or ["No major gaps were found."]
    tone = "strong" if overall >= 80 else "solid" if overall >= 60 else "a good start with clear room to grow"
    steps = [f"Review {q.topic}" for q in worst[:2] if q.final_score < 70] or ["Keep practising at this level."]
    return Narrative(verdict=f"Overall this was {tone} ({overall}/100).", strengths=strengths, gaps=gaps, next_steps=steps)


class Reporter:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    async def run(self, ctx: ReportContext) -> Report:
        qs = [
            QuestionReport(
                question_id=r.question_id, topic=r.topic, question=r.question,
                final_score=_score(r.final_score), followups=r.followups,
                covered_points=r.covered_points, missing_points=r.missing_points,
            )
            for r in ctx.questions
        ]
        if not qs:
            return Report(
                overall_score=0, questions=[], strengths=[], gaps=[],
                verdict="The interview ended before any question was answered, so there is nothing to score yet.",
            )
        overall = _score(sum(q.final_score for q in qs) / len(qs))
        try:
            narrative = await complete_validated(
                self.llm, self._prompt(ctx, qs, overall), Narrative, task="reporter"
            )
        except Exception as exc:  # feedback must always render
            log.warning("reporter fell back to point-based feedback: %s", exc)
            narrative = fallback_narrative(overall, qs)
        return Report(
            overall_score=overall, verdict=narrative.verdict, questions=qs,
            strengths=narrative.strengths, gaps=narrative.gaps, next_steps=narrative.next_steps,
        )

    @staticmethod
    def _prompt(ctx: ReportContext, qs: list[QuestionReport], overall: int) -> str:
        role = " ".join(x for x in (ctx.level, ctx.profile) if x) or "software"
        if ctx.company:
            role += f" at {ctx.company}"
        lines = []
        for i, q in enumerate(qs, 1):
            lines.append(
                f"{i}. [{q.topic}] {q.question}\n   score {q.final_score}/100, follow-ups needed: {q.followups}\n"
                f"   covered: {'; '.join(q.covered_points) or 'nothing noted'}\n"
                f"   missed: {'; '.join(q.missing_points) or 'nothing noted'}"
            )
        return (PROMPT.replace("__ROLE__", role).replace("__OVERALL__", str(overall))
                .replace("__QUESTIONS__", "\n".join(lines)))
