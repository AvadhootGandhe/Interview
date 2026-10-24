"""Reporter: an honest final report. Scores are computed in code; the model only writes the words."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.agents.base import LLM, Msg, complete_validated, render
from app.agents.schemas import Evaluation
from app.config import settings

log = logging.getLogger(__name__)


@dataclass
class QuestionRecord:
    question_id: str
    topic: str
    text: str
    final_score: int
    follow_ups: int
    thread: list[Msg]
    evaluation: Evaluation | None = None


@dataclass
class ReportInput:
    profile: str | None
    level: str | None
    company: str | None
    topic: str | None
    questions: list[QuestionRecord] = field(default_factory=list)


class ReportThreadMsg(BaseModel):
    role: str
    text: str


class ReportQuestion(BaseModel):
    question_id: str
    topic: str
    text: str
    final_score: int
    follow_ups: int
    thread: list[ReportThreadMsg]
    missing_points: list[str] = []


class ReportWords(BaseModel):
    verdict: str
    strengths: list[str]
    gaps: list[str]


class Report(BaseModel):
    overall_score: int
    verdict: str
    strengths: list[str]
    gaps: list[str]
    questions: list[ReportQuestion]


def _fallback_words(inp: ReportInput, overall: int) -> ReportWords:
    strengths, gaps = [], []
    for q in inp.questions:
        if q.evaluation:
            strengths += q.evaluation.covered_points[:1]
            gaps += q.evaluation.missing_points[:1]
    strengths = list(dict.fromkeys(strengths))[:4] or ["You completed the interview."]
    gaps = list(dict.fromkeys(gaps))[:4] or ["Keep practising to build depth on each topic."]
    verdict = ("A strong interview." if overall >= 80 else "A solid start with clear room to grow." if overall >= 55
               else "Plenty to work on; the gaps below are the best place to start.")
    return ReportWords(verdict=verdict, strengths=strengths, gaps=gaps)


class Reporter:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def build_prompt(self, inp: ReportInput, overall: int) -> str:
        lines = []
        for i, q in enumerate(inp.questions, 1):
            notes = ""
            if q.evaluation:
                notes = (f" Covered: {', '.join(q.evaluation.covered_points) or 'nothing noted'}."
                         f" Missing: {', '.join(q.evaluation.missing_points) or 'nothing'}.")
            lines.append(f"{i}. [{q.topic}] {q.text} -> {q.final_score}/100 ({q.follow_ups} follow-ups).{notes}")
        return render(
            "reporter", level=inp.level or "any level", profile=inp.profile or "technical",
            company_line=f" for {inp.company}" if inp.company else "", overall=overall, questions="\n".join(lines),
        )

    async def run(self, inp: ReportInput) -> Report:
        questions = [
            ReportQuestion(
                question_id=q.question_id, topic=q.topic, text=q.text, final_score=q.final_score,
                follow_ups=q.follow_ups, thread=[ReportThreadMsg(role=m.role, text=m.text) for m in q.thread],
                missing_points=q.evaluation.missing_points if q.evaluation else [],
            )
            for q in inp.questions
        ]
        if not inp.questions:
            return Report(overall_score=0, verdict="No questions were answered.", strengths=[], gaps=[], questions=[])
        overall = round(sum(q.final_score for q in inp.questions) / len(inp.questions))
        try:
            words, _ = await complete_validated(
                self.llm, self.build_prompt(inp, overall), ReportWords,
                task="report", model=settings.reporter_model, effort=settings.reporter_effort, max_tokens=1200,
            )
        except Exception as exc:  # a report must still be produced
            log.warning("reporter fell back to evaluation notes: %s", exc)
            words = _fallback_words(inp, overall)
        return Report(overall_score=overall, verdict=words.verdict, strengths=words.strengths,
                      gaps=words.gaps, questions=questions)
