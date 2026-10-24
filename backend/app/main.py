"""FastAPI app. Run: `uvicorn app.main:app --reload` from backend/."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import audio, catalog, sessions
from app.config import settings

app = FastAPI(title="AI Mock Interview")
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
)
app.include_router(catalog.router)
app.include_router(sessions.router)
app.include_router(audio.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
