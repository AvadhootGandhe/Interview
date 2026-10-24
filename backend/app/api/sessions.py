"""POST /sessions, POST /sessions/{id}/answer, POST /sessions/{id}/end, GET /sessions/{id}/report."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.evaluator import EvaluationError
from app.agents.orchestrator import Orchestrator, Reply, ReportNotReady, SessionClosed
from app.agents.planner import PlanError
from app.agents.question_generator import QuestionGenerator
from app.agents.reporter import Report
from app.config import settings
from app.db.session import get_db
from app.llm.claude_client import ClaudeError
from app.llm.factory import get_llm  # noqa: F401  (re-exported: tests override this dependency)
from app.llm.local_client import LocalClient
from app.services.retriever import Filters

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_generator():
    if settings.fake_llm:
        return None
    return QuestionGenerator(LocalClient(settings.llama_server_url, settings.generator_timeout_s))


class CreateSession(BaseModel):
    profile: str
    level: str
    company: str | None = None
    topic: str | None = None
    user_id: str | None = None


class AnswerBody(BaseModel):
    text: str = Field(min_length=1)


class EvaluationSummary(BaseModel):
    satisfaction: int
    missing_points: list[str]
    mentioned_terms: list[str]


class SessionReply(BaseModel):
    session_id: str
    text: str
    kind: str
    state: str
    done: bool
    question_index: int
    total_questions: int
    messages: list[dict]
    audio_url: str | None = None  # filled by TTS in Phase 4
    evaluation: EvaluationSummary | None = None


def _out(r: Reply) -> SessionReply:
    ev = r.evaluation
    return SessionReply(
        session_id=r.session_id, text=r.text, kind=r.kind, state=r.state, done=r.done,
        question_index=r.question_index, total_questions=r.total_questions, messages=r.messages,
        evaluation=EvaluationSummary(satisfaction=ev.satisfaction, missing_points=ev.missing_points,
                                     mentioned_terms=ev.mentioned_terms) if ev else None,
    )


def get_orchestrator(db: Session = Depends(get_db), llm=Depends(get_llm), generator=Depends(get_generator)) -> Orchestrator:
    return Orchestrator(db, llm, generator)


def _wrap(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(404, "session not found")
    if isinstance(exc, (SessionClosed, ReportNotReady)):
        return HTTPException(409, "the interview is already over" if isinstance(exc, SessionClosed)
                             else "the interview is not finished yet")
    if isinstance(exc, (ValueError, PlanError)):
        return HTTPException(422, str(exc))
    if isinstance(exc, (EvaluationError, ClaudeError)):
        return HTTPException(502, "the interviewer is unavailable, please try again")
    raise exc


@router.post("", response_model=SessionReply)
async def create_session(body: CreateSession, orch: Orchestrator = Depends(get_orchestrator)) -> SessionReply:
    try:
        return _out(await orch.start(
            Filters(profile=body.profile, level=body.level, company=body.company, topic=body.topic), body.user_id))
    except Exception as exc:
        raise _wrap(exc) from exc


@router.post("/{session_id}/answer", response_model=SessionReply)
async def answer(session_id: str, body: AnswerBody, orch: Orchestrator = Depends(get_orchestrator)) -> SessionReply:
    try:
        return _out(await orch.answer(session_id, body.text))
    except Exception as exc:
        raise _wrap(exc) from exc


@router.post("/{session_id}/end", response_model=SessionReply)
async def end(session_id: str, orch: Orchestrator = Depends(get_orchestrator)) -> SessionReply:
    try:
        return _out(await orch.end(session_id))
    except Exception as exc:
        raise _wrap(exc) from exc


@router.get("/{session_id}/report", response_model=Report)
async def report(session_id: str, orch: Orchestrator = Depends(get_orchestrator)) -> Report:
    try:
        return await orch.report(session_id)
    except Exception as exc:
        raise _wrap(exc) from exc
