"""POST /sessions, POST /sessions/{id}/answer, POST /sessions/{id}/end, GET /sessions/{id}/report."""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile
from pydantic import BaseModel, Field, ValidationError
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
from app.speech.deps import get_stt, get_tts

log = logging.getLogger(__name__)
NO_SPEECH = "I didn't catch that. Could you say it again?"

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
    audio_url: str | None = None  # spoken version of `text`; null if speech is off or TTS failed
    transcript: str | None = None  # what the candidate said (STT) or typed; set on /answer
    evaluation: EvaluationSummary | None = None


def _out(r: Reply) -> SessionReply:
    ev = r.evaluation
    return SessionReply(
        session_id=r.session_id, text=r.text, kind=r.kind, state=r.state, done=r.done,
        question_index=r.question_index, total_questions=r.total_questions, messages=r.messages,
        evaluation=EvaluationSummary(satisfaction=ev.satisfaction, missing_points=ev.missing_points,
                                     mentioned_terms=ev.mentioned_terms) if ev else None,
    )


async def _speak(out: SessionReply, tts, timings: dict[str, float]) -> None:
    """Attach audio_url. Never raises: if TTS fails the text still goes out."""
    if tts is None or not out.text.strip():
        return
    t0 = time.perf_counter()
    try:
        out.audio_url = await tts.synthesize(out.text)
        if len(out.messages) == 1:
            out.messages[0]["audio_url"] = out.audio_url
    except Exception:  # noqa: BLE001
        log.warning("TTS failed; returning text only", exc_info=True)
    finally:
        timings["tts"] = (time.perf_counter() - t0) * 1000


def _server_timing(timings: dict[str, float], t_start: float) -> str:
    timings = {**timings, "total": (time.perf_counter() - t_start) * 1000}
    return ", ".join(f"{k};dur={v:.1f}" for k, v in timings.items())


def _problem(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": message, "code": code})


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
async def create_session(body: CreateSession, response: Response, orch: Orchestrator = Depends(get_orchestrator),
                         tts=Depends(get_tts)) -> SessionReply:
    t0 = time.perf_counter()
    try:
        reply = await orch.start(
            Filters(profile=body.profile, level=body.level, company=body.company, topic=body.topic), body.user_id)
    except Exception as exc:
        raise _wrap(exc) from exc
    out = _out(reply)
    timings = dict(reply.timings)
    await _speak(out, tts, timings)
    response.headers["Server-Timing"] = _server_timing(timings, t0)
    return out


async def _read_answer(request: Request, stt, timings: dict[str, float]) -> tuple[str | None, JSONResponse | None]:
    """Return (text, None) or (None, error response). Multipart carries `audio`; otherwise JSON {"text"}."""
    if request.headers.get("content-type", "").startswith("multipart/"):
        form = await request.form()
        upload = form.get("audio")
        if not isinstance(upload, UploadFile):
            raise HTTPException(422, "send the recording in the `audio` field")
        data = await upload.read()
        if stt is None:
            return None, _problem(503, "speech_unavailable", "Voice answers are not available. Please type your answer.")
        if not data:
            return None, _problem(422, "no_speech", NO_SPEECH)
        t0 = time.perf_counter()
        try:
            text = (await stt.transcribe(data) or "").strip()
        except Exception:  # noqa: BLE001
            log.warning("STT failed", exc_info=True)
            return None, _problem(502, "stt_failed", "I couldn't process that recording. Please try again.")
        finally:
            timings["stt"] = (time.perf_counter() - t0) * 1000
        if not text:
            return None, _problem(422, "no_speech", NO_SPEECH)
        return text, None
    try:
        return AnswerBody.model_validate_json(await request.body()).text, None
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


@router.post("/{session_id}/answer", response_model=SessionReply)
async def answer(session_id: str, request: Request, response: Response, orch: Orchestrator = Depends(get_orchestrator),
                 stt=Depends(get_stt), tts=Depends(get_tts)):
    t0 = time.perf_counter()
    timings: dict[str, float] = {}
    try:
        orch._session(session_id)  # 404 before spending time on STT
    except Exception as exc:
        raise _wrap(exc) from exc
    text, problem = await _read_answer(request, stt, timings)
    if problem is not None:
        return problem
    try:
        reply = await orch.answer(session_id, text)
    except Exception as exc:
        raise _wrap(exc) from exc
    out = _out(reply)
    out.transcript = text
    timings.update(reply.timings)
    await _speak(out, tts, timings)
    response.headers["Server-Timing"] = _server_timing(timings, t0)
    return out


@router.post("/{session_id}/end", response_model=SessionReply)
async def end(session_id: str, response: Response, orch: Orchestrator = Depends(get_orchestrator),
              tts=Depends(get_tts)) -> SessionReply:
    t0 = time.perf_counter()
    try:
        reply = await orch.end(session_id)
    except Exception as exc:
        raise _wrap(exc) from exc
    out = _out(reply)
    timings = dict(reply.timings)
    await _speak(out, tts, timings)
    response.headers["Server-Timing"] = _server_timing(timings, t0)
    return out


@router.get("/{session_id}/report", response_model=Report)
async def report(session_id: str, orch: Orchestrator = Depends(get_orchestrator)) -> Report:
    try:
        return await orch.report(session_id)
    except Exception as exc:
        raise _wrap(exc) from exc
