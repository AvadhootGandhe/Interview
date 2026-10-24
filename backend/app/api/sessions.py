from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

from app.agents.reporter import Report, build_report
from app.services.retriever import Filters

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSession(BaseModel):
    profile: str
    level: str | None = None
    company: str | None = None
    topic: str | None = None


class Answer(BaseModel):
    text: str


class Turn(BaseModel):
    messages: list[str]
    kind: str
    state: str
    satisfaction: int | None = None


class Created(BaseModel):
    session_id: str
    messages: list[str]


def _known_profile(request: Request, profile: str) -> bool:
    with request.app.state.engine.connect() as conn:
        return conn.execute(text("select 1 from profiles where name = :n"), {"n": profile}).first() is not None


@router.post("")
async def create(body: CreateSession, request: Request) -> Created:
    if not _known_profile(request, body.profile):
        raise HTTPException(422, f"unknown profile: {body.profile}")
    started = await request.app.state.orchestrator.start(Filters(**body.model_dump()))
    return Created(session_id=started.session_id, messages=started.messages)


async def _run(call):
    try:
        reply = await call
    except KeyError:
        raise HTTPException(404, "session not found")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return Turn(messages=reply.messages, kind=reply.kind, state=reply.state,
                satisfaction=reply.evaluation.satisfaction if reply.evaluation else None)


@router.post("/{session_id}/answer")
async def answer(session_id: str, body: Answer, request: Request) -> Turn:
    if not body.text.strip():
        raise HTTPException(422, "answer is empty")
    return await _run(request.app.state.orchestrator.answer(session_id, body.text.strip()))


@router.post("/{session_id}/end")
async def end(session_id: str, request: Request) -> Turn:
    return await _run(request.app.state.orchestrator.end(session_id))


@router.get("/{session_id}/report")
async def report(session_id: str, request: Request) -> Report:
    try:
        return await build_report(request.app.state.engine, request.app.state.llm, session_id)
    except KeyError:
        raise HTTPException(404, "session not found")
