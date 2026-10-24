"""POST /sessions, POST /sessions/{id}/answer (text), POST /sessions/{id}/end, GET /sessions/{id}/report."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.base import AgentOutputError
from app.agents.orchestrator import (
    Orchestrator, SessionClosed, SessionNotFinished, SessionNotFound, TurnResult,
)
from app.agents.planner import PlanInvalid
from app.agents.question_generator import QuestionGenerator
from app.config import settings
from app.db.session import get_db
from app.llm.claude_client import LLMError
from app.llm.factory import make_llm
from app.llm.local_client import LocalClient
from app.services.retriever import Filters

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSession(BaseModel):
    profile: str
    level: str | None = None
    company: str | None = None
    topic: str | None = None
    user_id: str | None = None


class Answer(BaseModel):
    text: str = Field(max_length=10_000)


def get_llm():
    return make_llm()


def get_generator():
    """The fine-tuned question generator, or None when the offline fake is on."""
    if settings.fake_llm:
        return None
    return QuestionGenerator(LocalClient(settings.llama_server_url, settings.generator_timeout_s))


def get_orchestrator(db: Session = Depends(get_db), llm=Depends(get_llm), generator=Depends(get_generator)):
    return Orchestrator(db, llm, generator=generator)


def _turn(t: TurnResult) -> dict:
    return {
        "kind": t.kind, "text": t.text, "done": t.done, "progress": t.progress, "question_id": t.question_id,
        "evaluation": {"satisfaction": t.evaluation.satisfaction} if t.evaluation else None,
    }


async def _guard(call):
    try:
        return await call
    except SessionNotFound:
        raise HTTPException(404, "Session not found")
    except SessionClosed:
        raise HTTPException(409, "This interview is already finished")
    except SessionNotFinished:
        raise HTTPException(409, "The interview is still running")
    except (ValueError, PlanInvalid) as exc:
        raise HTTPException(422, str(exc))
    except (AgentOutputError, LLMError) as exc:
        raise HTTPException(502, f"The interviewer could not respond, please try again ({exc})")


@router.post("")
async def create_session(body: CreateSession, o: Orchestrator = Depends(get_orchestrator)) -> dict:
    result = await _guard(o.start(
        Filters(profile=body.profile, level=body.level, company=body.company, topic=body.topic), body.user_id
    ))
    return {
        "session_id": result.session_id, "messages": [asdict(m) for m in result.messages],
        "text": result.text, "progress": result.progress,
    }


@router.post("/{session_id}/answer")
async def answer(session_id: str, body: Answer, o: Orchestrator = Depends(get_orchestrator)) -> dict:
    return _turn(await _guard(o.answer(session_id, body.text)))


@router.post("/{session_id}/end")
async def end(session_id: str, o: Orchestrator = Depends(get_orchestrator)) -> dict:
    return _turn(await _guard(o.end(session_id)))


@router.get("/{session_id}/report")
async def report(session_id: str, o: Orchestrator = Depends(get_orchestrator)) -> dict:
    return (await _guard(o.report(session_id))).model_dump()
