import asyncio

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
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
    transcript: str | None = None
    audio_urls: list[str] = []


class Created(BaseModel):
    session_id: str
    messages: list[str]
    audio_urls: list[str] = []


async def _speak(request: Request, messages: list[str]) -> list[str]:
    tts = request.app.state.tts
    if tts is None:
        return []
    urls = await asyncio.gather(*(tts.synthesize(m) for m in messages))
    return urls if all(urls) else []


def _known_profile(request: Request, profile: str) -> bool:
    with request.app.state.engine.connect() as conn:
        return conn.execute(text("select 1 from profiles where name = :n"), {"n": profile}).first() is not None


@router.post("")
async def create(body: CreateSession, request: Request) -> Created:
    if not _known_profile(request, body.profile):
        raise HTTPException(422, f"unknown profile: {body.profile}")
    started = await request.app.state.orchestrator.start(Filters(**body.model_dump()))
    return Created(session_id=started.session_id, messages=started.messages,
                   audio_urls=await _speak(request, started.messages))


async def _run(call, request: Request, transcript: str | None = None):
    try:
        reply = await call
    except KeyError:
        raise HTTPException(404, "session not found")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return Turn(messages=reply.messages, kind=reply.kind, state=reply.state,
                satisfaction=reply.evaluation.satisfaction if reply.evaluation else None,
                transcript=transcript, audio_urls=await _speak(request, reply.messages))


@router.post("/{session_id}/answer")
async def answer(session_id: str, body: Answer, request: Request) -> Turn:
    if not body.text.strip():
        raise HTTPException(422, "answer is empty")
    return await _run(request.app.state.orchestrator.answer(session_id, body.text.strip()), request)


@router.post("/{session_id}/audio")
async def answer_audio(session_id: str, request: Request, audio: UploadFile = File(...)) -> Turn:
    stt = request.app.state.stt
    if stt is None:
        raise HTTPException(501, "speech input is not enabled")
    transcript = (await stt.transcribe(await audio.read())).strip()
    if not transcript:
        raise HTTPException(422, "Sorry, I couldn't hear that. Please try again.")
    return await _run(request.app.state.orchestrator.answer(session_id, transcript), request, transcript)


@router.post("/{session_id}/end")
async def end(session_id: str, request: Request) -> Turn:
    return await _run(request.app.state.orchestrator.end(session_id), request)


@router.get("/{session_id}/report")
async def report(session_id: str, request: Request) -> Report:
    try:
        return await build_report(request.app.state.engine, request.app.state.llm, session_id)
    except KeyError:
        raise HTTPException(404, "session not found")
