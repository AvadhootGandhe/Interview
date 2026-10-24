"""Serve cached interviewer audio: GET /audio/{file}."""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.speech import tts

router = APIRouter()
AUDIO_DIR = tts.AUDIO_DIR
PENDING_WAIT_S = 30
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*\.wav$")


@router.get("/audio/{file}")
async def get_audio(file: str) -> FileResponse:
    if not _SAFE_NAME.fullmatch(file):
        raise HTTPException(404, "not found")
    path = (AUDIO_DIR / file).resolve()
    pending = tts.PENDING.get(file)
    if pending is not None and not path.is_file():  # still rendering in the background: wait for it
        await asyncio.to_thread(pending.wait, PENDING_WAIT_S)
    if path.parent != AUDIO_DIR.resolve() or not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type="audio/wav")
