import json
import re
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db import models as m

PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "reporter.md").read_text()


class TurnOut(BaseModel):
    role: str
    kind: str
    text: str


class QuestionReport(BaseModel):
    index: int
    topic: str
    question: str
    score: int
    followups: int
    covered_points: list[str]
    missing_points: list[str]
    thread: list[TurnOut]


class Report(BaseModel):
    session_id: str
    profile: str
    level: str | None
    company: str | None
    overall_score: int
    verdict: str
    strengths: list[str]
    gaps: list[str]
    questions: list[QuestionReport]


def _load_questions(db: Session, s: m.InterviewSession) -> list[QuestionReport]:
    plan = json.loads(db.scalars(select(m.Plan).where(m.Plan.session_id == s.id)
                                 .order_by(m.Plan.version.desc())).first().plan_json)["segments"]
    pool = {p["id"]: p for p in json.loads(s.pool_json)}
    out: list[QuestionReport] = []
    for final in db.scalars(select(m.Evaluation).where(m.Evaluation.session_id == s.id,
                                                       m.Evaluation.final_score.is_not(None))
                            .order_by(m.Evaluation.segment_index)):
        idx = final.segment_index
        seed = pool[plan[idx]["seed_question_id"]]
        attempts = db.scalars(select(m.Evaluation).where(m.Evaluation.session_id == s.id,
                                                         m.Evaluation.segment_index == idx)
                              .order_by(m.Evaluation.attempt)).all()
        last = json.loads(final.data_json)
        turns = db.scalars(select(m.Turn).where(m.Turn.session_id == s.id, m.Turn.segment_index == idx,
                                                m.Turn.kind.not_in(("greeting", "closing"))).order_by(m.Turn.id)).all()
        out.append(QuestionReport(
            index=idx, topic=seed["topic"], question=seed["text"], score=final.final_score,
            followups=len(attempts) - 1, covered_points=last.get("covered_points", []),
            missing_points=last.get("missing_points", []),
            thread=[TurnOut(role=t.role, kind=t.kind, text=t.text) for t in turns]))
    return out


def _fallback(questions: list[QuestionReport], overall: int) -> tuple[str, list[str], list[str]]:
    strengths = [p for q in sorted(questions, key=lambda q: -q.score) for p in q.covered_points][:3]
    gaps = [p for q in sorted(questions, key=lambda q: q.score) for p in q.missing_points][:3]
    return (f"Overall score {overall} out of 100.",
            list(dict.fromkeys(strengths)) or ["Completed the interview"],
            list(dict.fromkeys(gaps)) or ["No major gaps identified"])


async def build_report(engine: Engine, llm, session_id: str) -> Report:
    with Session(engine) as db:
        s = db.get(m.InterviewSession, session_id)
        if s is None:
            raise KeyError(session_id)
        questions = _load_questions(db, s)
        meta = dict(session_id=s.id, profile=s.profile, level=s.level, company=s.company)
    overall = round(sum(q.score for q in questions) / len(questions)) if questions else 0

    results = "\n".join(
        f"- {q.topic}: score {q.score}, follow-ups {q.followups}; covered: {', '.join(q.covered_points) or 'n/a'}; "
        f"missing: {', '.join(q.missing_points) or 'n/a'}" for q in questions)
    prompt = (PROMPT.replace("{profile}", meta["profile"]).replace("{level}", meta["level"] or "unspecified")
              .replace("{results}", results))
    verdict = strengths = gaps = None
    try:
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", (await llm.complete(prompt, max_tokens=500, model=settings.cheap_model)).strip())
        data = json.loads(raw)
        verdict, strengths, gaps = str(data["verdict"]), list(data["strengths"]), list(data["gaps"])
    except Exception:
        pass
    if not (verdict and strengths and gaps):
        verdict, strengths, gaps = _fallback(questions, overall)
    return Report(**meta, overall_score=overall, verdict=verdict, strengths=strengths, gaps=gaps,
                  questions=questions)
