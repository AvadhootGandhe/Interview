"""Text to speech: split into sentences, synthesize each, join into one cached wav.

`TextToSpeech.synthesize(text) -> "/audio/<hash>.wav"` matches the FakeTTS in tests/conftest.py.
Kokoro is imported lazily, so cloud tests never need it.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import wave
from pathlib import Path
from typing import Protocol

AUDIO_DIR = Path(__file__).resolve().parents[2] / "audio_cache"  # git-ignored
VOICE = os.environ.get("TTS_VOICE", "af_heart")
SAMPLE_RATE = 24000
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class TTSEngine(Protocol):
    def synth_wav(self, text: str) -> bytes: ...


def split_sentences(text: str, max_chars: int = 300) -> list[str]:
    """Sentences, with oversized ones broken at word boundaries; each piece <= max_chars."""
    out: list[str] = []
    for sent in _SENTENCE_END.split(text.strip()):
        sent = sent.strip()
        while len(sent) > max_chars:
            cut = sent.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            out.append(sent[:cut].strip())
            sent = sent[cut:].strip()
        if sent:
            out.append(sent)
    return out


class KokoroEngine:
    def __init__(self, voice: str = VOICE) -> None:
        self.voice = voice
        self._pipeline = None

    def _get(self):
        if self._pipeline is None:
            from kokoro import KPipeline  # lazy: Mac-only dependency

            self._pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
        return self._pipeline

    def synth_wav(self, text: str) -> bytes:
        import numpy as np

        chunks = [np.asarray(audio, dtype="float32") for _, _, audio in self._get()(text, voice=self.voice) if audio is not None]
        pcm = (np.clip(np.concatenate(chunks), -1, 1) * 32767).astype("<i2") if chunks else np.zeros(0, "<i2")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())
        return buf.getvalue()


def _join_wavs(wavs: list[bytes]) -> bytes:
    buf = io.BytesIO()
    out = None
    for data in wavs:
        with wave.open(io.BytesIO(data)) as w:
            if out is None:
                out = wave.open(buf, "wb")
                out.setparams(w.getparams())
            out.writeframes(w.readframes(w.getnframes()))
    out.close()
    return buf.getvalue()


class TextToSpeech:
    def __init__(self, engine: TTSEngine | None = None, cache_dir: Path | None = None, voice: str = VOICE) -> None:
        self.engine = engine or KokoroEngine(voice)
        self.cache_dir = Path(cache_dir) if cache_dir else AUDIO_DIR
        self.voice = voice

    def _name(self, text: str) -> str:
        return hashlib.sha256(f"{self.voice}\n{text}".encode()).hexdigest()[:32] + ".wav"

    async def synthesize(self, text: str) -> str:
        text = " ".join(text.split())
        if not text:
            raise ValueError("cannot synthesize empty text")
        name = self._name(text)
        path = self.cache_dir / name
        if not path.exists():
            await asyncio.to_thread(self._render, text, path)
        return f"/audio/{name}"

    def _render(self, text: str, path: Path) -> None:
        wavs = [self.engine.synth_wav(s) for s in split_sentences(text)]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(_join_wavs(wavs))
        tmp.replace(path)
