"""Offline speech for SPEECH=fake (demos, benchmarks without models). Same interface as the real engines."""
from __future__ import annotations

import hashlib
import io
import wave
from pathlib import Path

from app.speech.tts import AUDIO_DIR


class FakeSpeechToText:
    async def transcribe(self, audio: bytes | None) -> str:
        return "This is a fake transcript of my spoken answer." if audio else ""


class FakeSpeechTTS:
    """Writes a short silent wav so /audio/ has something real to serve."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else AUDIO_DIR

    async def synthesize(self, text: str) -> str:
        text = " ".join(text.split())
        if not text:
            raise ValueError("cannot synthesize empty text")
        name = "fake-" + hashlib.sha256(text.encode()).hexdigest()[:24] + ".wav"
        path = self.cache_dir / name
        if not path.exists():
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(b"\x00\x00" * 800)
            path.write_bytes(buf.getvalue())
        return f"/audio/{name}"
