"""FastAPI app. Run: `uvicorn app.main:app --reload` from backend/."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import audio, catalog, sessions
from app.config import settings
from app.speech.deps import get_stt, get_tts
from app.speech.warmup import warm_up_speech


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Background task: the server answers /health at once; models load while the user fills in the setup screen.
    task = asyncio.create_task(warm_up_speech(get_stt(), get_tts()))
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="AI Mock Interview", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
)
app.include_router(catalog.router)
app.include_router(sessions.router)
app.include_router(audio.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
